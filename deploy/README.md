# 배포 가이드

**Git push → Jenkins webhook → SSH → Podman 호스트** 자동 배포.

- 대상 사용자: `dodsas` (기존 계정)
- 원격 작업 디렉토리: `/home/dodsas/work/ysclaude`
- 트리거: `main` 브랜치 push (다른 브랜치는 건너뜀)
- 노출 포트: `9090` (FastAPI)
- 헬스체크 경로: `/health`

## 1. 사전 준비 (1회)

### 1-1. Podman 호스트 (`dodsas`로 로그인 상태에서)

```bash
# rootless 컨테이너가 로그아웃/세션 종료 후에도 유지되도록
sudo loginctl enable-linger dodsas

# Podman 동작 확인
podman --version    # 4.9.4-rhel

# 작업 디렉토리 미리 생성 (Jenkins가 만들기도 하지만 권한 명확화 차원)
mkdir -p /home/dodsas/work/ysclaude
```

### 1-2. Claude CLI 인증 정보 준비 (yclaude 고유)

`/chat` 엔드포인트는 컨테이너 내부의 `claude` CLI를 subprocess 로 호출합니다. **호스트(=Podman을 띄운 메인 PC)에서 인증된 `~/.claude` 디렉토리를 컨테이너에 read-only 로 마운트**하여, 호스트와 동일한 자격으로 동작시킵니다.

```bash
# 호스트(dodsas)에서 — 최초 1회만
claude          # 인증 (브라우저 또는 토큰 방식). ~/.claude/ 에 자격증명 저장.
claude -p --model opus --output-format json "ping"   # 동작 검증
```

`deploy.sh`는 다음 우선순위로 마운트 대상을 결정합니다:

1. 환경변수 `CLAUDE_HOST_DIR`가 지정되어 있으면 그 경로
2. 호스트의 `~/.claude` 가 존재하고 비어있지 않으면 **자동으로 그 경로 사용** ← 기본 경로
3. 둘 다 해당 없으면 `<APP_DIR>/secrets/claude` 를 placeholder 로 생성

따라서 기본 사용 흐름에서는 추가 복사 단계가 필요하지 않습니다. 호스트에서 `claude` 토큰을 갱신해도 컨테이너에 즉시 반영됩니다 (재시작 불필요 — CLI는 호출마다 파일을 재로딩).

> 💡 **rootless Podman 권한 매핑** — `compose.yml`에 `userns_mode: "keep-id"` 가 설정되어 컨테이너 안 uid 1000(app)이 호스트 dodsas uid에 매핑됩니다. 이 설정 덕분에 `~/.claude` (호스트 dodsas 소유, mode 700)를 컨테이너에서 읽을 수 있습니다.

### 1-3. `.env` 작성

`/home/dodsas/work/ysclaude/.env` 에 운영 비밀값 작성. 첫 배포 시 파일이 없으면 `deploy.sh`가 `server/.env.example`을 복사하지만, **운영용으로 반드시 교체**해야 합니다.

```bash
cat > /home/dodsas/work/ysclaude/.env <<'EOF'
API_KEY=<32바이트+ 랜덤문자열>
JWT_SECRET=<32바이트+ 랜덤문자열>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
DEFAULT_MODEL=opus
CLAUDE_CLI_PATH=claude
CLAUDE_TIMEOUT=300
HOST=0.0.0.0
PORT=9090
EOF
chmod 600 /home/dodsas/work/ysclaude/.env
```

> 랜덤 생성 예시: `openssl rand -hex 32`

### 1-4. SSH 키 등록 — 기존 `ysadmin-deploy-ssh` 재사용

Jenkinsfile의 `SSH_CRED = 'ysadmin-deploy-ssh'` 로 설정되어 있어, **ysadmin 배포에 사용 중인 SSH credential과 authorized_keys 를 그대로 공유**합니다. 별도 키 생성/등록 작업이 필요하지 않습니다.

전제:
- Jenkins Credentials에 ID `ysadmin-deploy-ssh` 가 이미 등록되어 있음
- 그 키의 공개키가 dodsas `~/.ssh/authorized_keys` 에 이미 들어있음 (ysadmin 배포 중이면 자동 충족)

별도 키로 분리하고 싶다면 Jenkinsfile의 `SSH_CRED` 값을 새 ID로 바꾸고 표준 절차로 키를 만드세요.

### 1-5. Jenkins Pipeline Item 생성

- **New Item → Pipeline** 생성 (이름 예: `ysclaude-deploy`)
- **Pipeline → Definition: Pipeline script from SCM**
  - SCM: Git
  - Repository URL: 이 저장소 URL
  - Branch: `*/main` (또는 빈 값 = 전체)
  - Script Path: `Jenkinsfile`
- **Build Triggers**:
  - ☑ `GitHub hook trigger for GITScm polling` (GitHub 사용 시)
  - 또는 `Poll SCM` (자동, 2분 주기로 백업 동작)
- 첫 실행은 수동(**Build with Parameters**)으로 한 번 — 파라미터 기본값 검토
  - `DEPLOY_HOST`: Podman 호스트 명/IP
  - `DEPLOY_USER`: `dodsas` (기본)
  - `REMOTE_DIR`: `/home/dodsas/work/ysclaude` (기본)
  - `HOST_PORT`: `9090`
  - `DEPLOY_BRANCH`: `main`

### 1-6. Git 저장소 Webhook

**GitHub의 경우**: 저장소 **Settings → Webhooks → Add webhook**
- Payload URL: `http://<jenkins>:8080/github-webhook/`
- Content type: `application/json`
- Events: `Just the push event`

**GitLab의 경우**: 저장소 **Settings → Webhooks**
- URL: `http://<jenkins>:8080/project/ysclaude-deploy`
- Trigger: `Push events`
- (사내 Jenkins라면 GitLab Plugin 설치 필요)

**사내 자체 호스팅 / 방화벽으로 webhook 불가**: `Poll SCM`만 활성화. 최대 2분 지연 발생하지만 무인 자동 배포 자체는 동작.

## 2. 일상 운영

```bash
git push origin main    # ← 이것만으로 배포 완료
```

`main` 외 브랜치 push는 Jenkins가 빌드는 시작하더라도 `when` 가드로 배포 단계가 건너뛰어집니다. PR 머지 단계에서 자연스럽게 운영 반영.

수동 배포가 필요하면 Jenkins에서 **Build with Parameters** 실행.

## 3. 호스트 재부팅에도 살아남기 (선택, 권장)

compose의 `restart: always`는 Podman 서비스 차원의 재시작만 처리하고 호스트 OS 재부팅까진 살아남지 못합니다 (linger 적용 후에도 마찬가지 — linger는 user systemd만 유지하지 compose가 띄운 컨테이너를 자동 기동해주진 않음).

부팅 시 자동으로 `podman-compose up`을 실행하는 user-level systemd unit으로 해결:

```bash
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
```

전제: 1-1의 `enable-linger`가 적용되어 있어야 부팅 시 user systemd가 시작됨.

자세한 절차는 [SETUP.md §10](./SETUP.md)을 참고.

## 4. 운영 명령어

```bash
podman ps --filter name=ysclaude                 # 상태 확인
podman logs -f ysclaude                          # 로그 추적
podman exec -it ysclaude sh                      # 컨테이너 진입
podman volume inspect ysclaude-data              # 볼륨 경로
podman volume export ysclaude-data > backup.tar  # 데이터 백업

# Claude CLI 동작 확인 (컨테이너 안에서)
podman exec -it ysclaude claude --version
podman exec -it ysclaude claude -p --model opus --output-format json "hi"
```

## 5. 롤백

```bash
git revert <bad-commit>
git push origin main    # 자동 재배포
```

이미지는 매 빌드마다 새로 만들어지므로 별도 태그/레지스트리 없으면 git 측에서 롤백. 빌드 번호별 태그 보관이 필요해지면 `Jenkinsfile`에 `podman tag localhost/ysclaude:latest localhost/ysclaude:${BUILD_NUMBER}` 한 줄 추가 + 보관 정책 정의.

## Webhook vs 수동 트리거 트레이드오프

- ✅ **장점**: 배포 절차가 git 흐름과 일치, 사람 실수 없음, 어떤 커밋이 배포되었는지 git 이력과 1:1 매칭
- ⚠ **주의**: `main`에 잘못된 코드가 머지되면 즉시 운영 반영됨 → PR/리뷰 가드 필수, 또는 `release` 브랜치를 별도 배포 대상으로 두는 것도 가능 (`DEPLOY_BRANCH` 파라미터 변경)
