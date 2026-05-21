# ysclaude 배포 설정 체크리스트

처음 1회 진행하는 셋업 절차. 위에서부터 순서대로 진행.

- 대상 사용자: `dodsas`
- 원격 작업 경로: `/home/dodsas/work/ysclaude`
- 트리거: `main` 브랜치 push 시 자동 배포
- 노출 포트: `9091` (FastAPI)
- 헬스체크: `GET /health`

---

## ☐ 1단계 — 원격 Git 저장소 준비 및 푸시 (로컬)

```bash
cd /Users/nam-yuseon/IdeaProjects/yclaude

# 사내 GitLab/GitHub 등에서 빈 저장소 생성 후
git remote add origin <repo-url>

git add .
git commit -m "init: ysclaude API gateway + 배포 자산"
git branch -M main
git push -u origin main
```

검증: 원격 저장소 웹 UI에서 파일 목록 확인.

---

## ☐ 2단계 — Podman 호스트 준비 (`dodsas`로 SSH 접속해서)

```bash
# rootless 컨테이너가 세션 종료 후에도 살아있도록
sudo loginctl enable-linger dodsas

# 작업 디렉토리 생성
mkdir -p /home/dodsas/work/ysclaude

# Podman 동작 확인
podman --version              # 4.9.4-rhel
podman info | head -20        # rootless 확인

# podman-compose 설치 확인 (없으면 설치)
podman-compose --version || sudo dnf install -y podman-compose
# 또는 (dnf 패키지가 없는 경우): pip install --user podman-compose

# 9091 포트 방화벽 (firewalld 환경)
sudo firewall-cmd --permanent --add-port=9091/tcp
sudo firewall-cmd --reload
```

검증: `podman ps` 가 에러 없이 빈 목록 출력.

---

## ☐ 3단계 — Claude CLI 인증 정보 준비 (ysclaude 고유 단계)

`/chat` 엔드포인트는 컨테이너 안에서 `claude` CLI를 subprocess로 실행합니다. **호스트(=Podman을 띄운 메인 PC)에서 미리 인증된 `~/.claude` 디렉토리를 컨테이너에 read-only 로 마운트**해서 호스트와 동일한 자격으로 동작시킵니다.

> 💡 **rootless Podman 권한 매핑**
> `compose.yml`의 `userns_mode: "keep-id"`로 컨테이너 안 uid 1000(app)이 호스트의 `dodsas` uid로 매핑되어, `~/.claude`(호스트 dodsas 소유, mode 700)를 컨테이너에서도 읽을 수 있습니다. 이 옵션이 없으면 마운트는 되더라도 컨테이너 내부에서 "Permission denied"가 발생합니다.

### 3-1. 호스트(dodsas)에서 Claude CLI 설치 + 인증

```bash
# Claude CLI 설치 (이미 있으면 스킵)
which claude || sudo npm install -g @anthropic-ai/claude-code

# 최초 인증 (브라우저 또는 토큰 방식)
claude
# → 안내에 따라 인증 진행. ~/.claude/ 하위에 자격증명 저장됨.

# 인증 검증
claude -p --model opus --output-format json "ping"
# → JSON 응답에 is_error: false 확인
```

### 3-2. 컨테이너 마운트 경로 선택 (둘 중 하나)

#### (옵션 A) ★권장★ — 호스트 `~/.claude` 직접 마운트 (live)

`deploy.sh`가 자동으로 감지합니다. **별도 작업 불필요**:

```bash
# 호스트 ~/.claude 가 존재하고 비어있지 않으면 deploy.sh 가
# CLAUDE_HOST_DIR=$HOME/.claude 로 자동 설정해서 마운트합니다.
ls -la ~/.claude
```

장점:
- 호스트에서 `claude` 재인증 / 토큰 갱신 → **즉시 컨테이너에 반영** (재시작 불필요. 컨테이너는 매 호출마다 파일을 다시 읽음)
- 추가 동기화 작업 없음

주의:
- `restorecon -Rv ~/.claude` 같은 SELinux 라벨 재설정을 하지 마세요. compose.yml에서 `:Z` 라벨 옵션을 일부러 빼두었습니다 (호스트 디렉토리의 SELinux 컨텍스트 유지 목적).

#### (옵션 B) 배포 디렉토리 안에 복사 (snapshot)

호스트 `~/.claude`를 직접 쓰지 않고 별도 카피본을 두고 싶을 때:

```bash
mkdir -p /home/dodsas/work/ysclaude/secrets/claude
rsync -a ~/.claude/ /home/dodsas/work/ysclaude/secrets/claude/
chmod 700 /home/dodsas/work/ysclaude/secrets/claude
```

이 옵션을 쓰려면 `deploy.sh` 실행 전에 `unset CLAUDE_HOST_DIR` 하고, `~/.claude`를 비워두거나 옵션 A의 자동 감지를 피하기 위해 환경변수로 명시:
```bash
export CLAUDE_HOST_DIR=/home/dodsas/work/ysclaude/secrets/claude
```

⚠ 토큰 만료 / 재발급 시: `claude` 재인증 후 다시 `rsync`로 동기화. cron 자동화 가능.

---

## ☐ 4단계 — `.env` 작성

```bash
cat > /home/dodsas/work/ysclaude/.env <<EOF
API_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
DEFAULT_MODEL=opus
CLAUDE_CLI_PATH=claude
CLAUDE_TIMEOUT=300
HOST=0.0.0.0
PORT=9091
EOF
chmod 600 /home/dodsas/work/ysclaude/.env

# 발급된 API_KEY 확인 (클라이언트가 토큰 발급할 때 필요)
grep '^API_KEY=' /home/dodsas/work/ysclaude/.env
```

> 이 `.env`는 git에 커밋되지 않습니다. 호스트에서만 관리.

---

## ☐ 5단계 — SSH 자격증명 (기존 `ysadmin-deploy-ssh` 재사용)

`Jenkinsfile` 의 `SSH_CRED = 'ysadmin-deploy-ssh'` 로 설정되어, **ysadmin 배포에 쓰는 SSH credential을 그대로 재사용**합니다. 별도 키 생성·등록 작업이 필요하지 않습니다.

확인만 하세요:

### 5-1. Jenkins Credentials 에 `ysadmin-deploy-ssh` 가 있나
**Manage Jenkins → Credentials → System → Global** 목록에서 ID 컬럼에 `ysadmin-deploy-ssh` 존재 여부 확인.
- 있으면 ✅ 5단계 끝
- 없으면 ysadmin 쪽 SETUP을 먼저 따라가 등록 후 돌아오세요.

### 5-2. 그 키로 dodsas 에 접속 가능한가 (옵션, 의심될 때만)
ysadmin 배포가 정상 동작 중이면 이미 충족됩니다. 의심스러우면 Jenkins 머신에서:
```bash
# Jenkins 서버 셸 안에서 (예: docker exec / 노드 콘솔)
ssh -p 22311 -i <credential-as-file> dodsas@<podman-host> "podman --version"
```

### 분리하고 싶다면
ysclaude 전용 credential 로 따로 두려면 `Jenkinsfile` 의 `SSH_CRED` 값을 새 ID 로 바꾸고, 표준 절차(키 생성 → authorized_keys 등록 → Credentials 등록)를 따르면 됩니다.

---

## ☐ 6단계 — Jenkins Pipeline Item 생성

**New Item → Pipeline** (이름 예: `ysclaude-deploy`)

- Pipeline → Definition: **Pipeline script from SCM**
- SCM: **Git**
- Repository URL: 1단계의 git URL
- 필요 시 git 자격증명 추가
- Branch Specifier: `*/main`
- Script Path: `Jenkinsfile`
- Build Triggers: **환경에 따라 둘 중 하나 선택**

  **(A) Webhook 가능 환경** (GitHub이 Jenkins URL에 HTTP 도달 가능)
  - ☑ `GitHub hook trigger for GITScm polling`
  - → 이 옵션은 **7단계와 한 쌍**입니다. 7단계 미실시 시 트리거 동작 안 함

  **(B) Webhook 불가 환경** (사내망 / 방화벽으로 외부에서 Jenkins 접근 차단)
  - ☑ `Poll SCM`: `H/2 * * * *` (2분 주기 폴링)
  - → 7단계 불필요. 1~2분 지연 발생

webhook 도달 가능 여부 빠른 판단:
- Jenkins URL이 GitHub.com → Jenkins 방향으로 열려있나? (공인 IP / 사내 GitHub Enterprise 등)
- 모르면 일단 (B)로 시작 → 나중에 webhook 가능해지면 옵션 추가/변경

저장.

---

## ☐ 7단계 — Git Webhook 등록 (6단계에서 A 선택한 경우 **필수**)

> 6단계 (B) Poll SCM만 선택했다면 이 단계는 건너뛰세요.

**GitHub**: 저장소 → Settings → Webhooks → Add webhook
- Payload URL: `http://<jenkins-host>:8080/github-webhook/`
- Content type: `application/json`
- Events: `Just the push event`

**GitLab**: 저장소 → Settings → Webhooks
- URL: `http://<jenkins-host>:8080/project/ysclaude-deploy`
- Trigger: `Push events`

### 등록 후 동작 확인

GitHub 저장소 → Settings → Webhooks → 등록한 webhook 클릭 → **Recent Deliveries** 탭
- ✅ 초록 체크 + 200 응답 → webhook 정상
- ❌ 빨간 X (Connection refused / timeout) → Jenkins URL이 외부에서 접근 불가 → 6단계 (B)로 전환 권장

---

## ☐ 8단계 — 첫 배포 실행 (수동)

### 8-1. 6단계에서 만든 Item 화면으로 진입

1. Jenkins 첫 화면(**Dashboard**) 접속
2. 중앙 목록에서 **`ysclaude-deploy`** 클릭

### 8-2. 파라미터 입력 화면으로 진입

좌측 사이드바에서 **`Build with Parameters`** 클릭
- 한글 UI라면: **`파라미터와 함께 빌드`** 또는 **`매개변수와 함께 빌드`**

> 메뉴에 `Build with Parameters`가 안 보이고 `Build Now`만 보이면, **`Build Now`를 한 번 클릭**하세요. Jenkinsfile의 parameters 블록이 등록되면서 다음부터 `Build with Parameters`로 바뀝니다.

### 8-3. 파라미터 입력

| 파라미터 | 입력값 |
|---|---|
| DEPLOY_HOST | Podman 호스트의 실제 IP 또는 호스트명 ★ |
| DEPLOY_USER | `dodsas` |
| REMOTE_DIR | `/home/dodsas/work/ysclaude` |
| DEPLOY_BRANCH | `main` |

★ **DEPLOY_HOST만** 환경에 맞게 입력. 나머지는 기본값 그대로 두면 됩니다.

> `HOST_PORT` 는 Jenkinsfile `environment` 에 `9091` 로 고정되어 있어 파라미터에 노출되지 않습니다. 변경이 필요하면 Jenkinsfile 의 `HOST_PORT = '9091'` 한 줄을 수정 후 커밋하세요.

### 8-4. 빌드 실행 및 진행 상황 확인

하단 **`Build`** 버튼 클릭 → Item 화면 좌측 하단 **`Build History`** 에 새 빌드 번호(`#1`) 표시됨.

빌드 번호 클릭 → 좌측 **`Console Output`** 클릭 → 실시간 로그 확인.

### 8-5. 통과해야 할 5개 stage

1. **Checkout** — 저장소에서 코드 가져오기
2. **Package** — `git archive`로 tar.gz 생성
3. **Transfer** — Podman 호스트로 SCP 전송 및 압축 해제
4. **Deploy** — `deploy.sh` 실행 (podman-compose build/up)
5. **Smoke Test** — `GET /health` 응답 확인

성공 시 마지막 줄:
```
✓ 배포 성공: http://<DEPLOY_HOST>:9091  (image: localhost/ysclaude:b1-<sha>)
```

---

## ☐ 9단계 — 배포 검증

**Podman 호스트 (dodsas)** 에서:
```bash
podman ps --filter name=ysclaude
# STATUS: Up X seconds (healthy)

curl -s http://127.0.0.1:9091/health
# {"status":"ok"}

# 토큰 발급 (4단계 .env의 API_KEY 사용)
API_KEY=$(grep '^API_KEY=' /home/dodsas/work/ysclaude/.env | cut -d= -f2)
TOKEN=$(curl -s -X POST http://127.0.0.1:9091/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"${API_KEY}\",\"client_id\":\"smoke\"}" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# /chat 호출
curl -s -X POST http://127.0.0.1:9091/chat \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"question":"ping"}'
```

**브라우저**:
```
http://<podman-host>:9091/docs
```
Swagger UI 표시 확인.

---

## ☐ 10단계 — 자동 배포 검증

```bash
# 로컬에서 사소한 변경 후
git commit -am "test: trigger auto deploy"
git push origin main
```

Jenkins에서 자동 빌드 시작되면 webhook/polling 정상. 빌드 종료 후 브라우저 재접속.

---

## ☐ 11단계 — (선택, 권장) 호스트 재부팅 대응

compose의 `restart: always`는 **Podman 서비스 차원 재시작**만 처리하고 **호스트 OS 재부팅**까진 살아남지 못합니다. 재부팅 후 자동 기동이 필요하면 둘 중 선택:

### (a) 가장 간단 — 부팅 시 podman-compose up 자동 실행

dodsas 사용자 systemd unit으로 등록.

```bash
# Podman 호스트(dodsas)에서
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/ysclaude-compose.service <<'EOF'
[Unit]
Description=ysclaude (podman-compose)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/dodsas/work/ysclaude
ExecStart=/usr/bin/podman-compose up -d
ExecStop=/usr/bin/podman-compose down

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ysclaude-compose.service
systemctl --user status ysclaude-compose.service
```

**2단계의 `enable-linger`가 적용되어 있어야 부팅 시 자동 시작됩니다.**

### (b) `podman generate systemd`로 컨테이너 단위 unit 생성

```bash
cd /home/dodsas/work/ysclaude
podman-compose up -d                            # 일단 한 번 기동
podman generate systemd --new --files --name ysclaude
mv container-ysclaude.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now container-ysclaude.service
```

⚠ 옵션 (b) 적용 시 systemd가 컨테이너 라이프사이클을 직접 관리하므로 향후 배포 시 `deploy.sh`가 손대는 컨테이너와 충돌 가능. 이 경우 옵션 (a) 권장.

---

## 트러블슈팅 — 자주 막히는 지점

| 증상 | 원인 / 조치 |
|---|---|
| 5단계 SSH 연결 실패 (Permission denied) | SELinux가 authorized_keys 차단 → `restorecon -Rv ~/.ssh` |
| Deploy stage에서 podman 명령 실패 | linger 미적용 → 2단계 `loginctl enable-linger dodsas` 재확인 |
| 컨테이너는 떴는데 외부 접속 불가 | firewalld / 클라우드 보안그룹 / 사내 방화벽 (9091) 확인 |
| `podman build`에서 pip 네트워크 오류 | 사내 미러 설정 → Dockerfile에 `RUN pip config set global.index-url ...` 추가 |
| Jenkins가 webhook은 받는데 빌드 안 시작 | 6단계 Build Triggers 체크 빠뜨림 / GitHub plugin 미설치 |
| Smoke Test에서 502/Connection refused | 컨테이너 부팅 시간 부족 → `deploy.sh`의 헬스체크 대기 30초로는 부족할 가능성 (이미지 첫 빌드 시) |
| `/chat` 호출 시 502 "Claude CLI ..." | 3단계 `secrets/claude` 마운트가 비어있거나 토큰 만료 → 재인증 후 rsync |
| `Invalid API key` | 클라이언트의 `api_key`가 `.env`의 `API_KEY` 와 불일치 |

---

## 운영 명령어 빠른 참조

```bash
podman ps --filter name=ysclaude                 # 상태
podman logs -f ysclaude                          # 로그
podman exec -it ysclaude sh                      # 컨테이너 진입
podman volume inspect ysclaude-data              # 데이터 볼륨 경로
podman volume export ysclaude-data > backup.tar  # 백업

# Claude CLI 헬스체크
podman exec -it ysclaude claude --version
podman exec -it ysclaude claude -p --model opus --output-format json "hi"

# 롤백
git revert <bad-commit>
git push origin main
```
