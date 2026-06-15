# yclaude

로컬에 설치된 **Claude CLI**를 HTTP API로 노출시키는 경량 FastAPI 게이트웨이. 클라이언트는 마스터 `API_KEY`로 단기 JWT를 발급받아 `/chat` 엔드포인트에 자연어 질의를 보내고, 서버는 그 질의를 Claude CLI에 위임해 응답을 돌려준다.

```
[Client] --API_KEY--> /auth/token --JWT-->   [Client]
                                  ──Bearer──> /chat  ──subprocess──> Claude CLI
```

---

## 1. 사전 요구사항

| 항목 | 버전 / 비고 |
|---|---|
| Python | 3.11+ (3.13 검증됨) |
| Claude CLI | `claude` 명령이 PATH에 있어야 함. 사전 로그인 필요 (`claude` 실행 후 인증) |
| OS | macOS / Linux (Windows는 미검증) |

Claude CLI 동작 확인:
```bash
claude -p --model opus --output-format json "hello"
```
JSON 응답이 정상으로 나와야 서버가 사용 가능하다.

---

## 2. 설치 및 실행

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env       # 비밀값 수정 (아래 §3 참조)
.venv/bin/python main.py   # → http://0.0.0.0:9091
```

대체 포트로 띄우려면 환경변수 override:
```bash
PORT=8001 .venv/bin/python main.py
```

기동 확인:
```bash
curl http://localhost:9091/health
# {"status":"ok"}
```

Swagger UI: <http://localhost:9091/docs>
ReDoc:      <http://localhost:9091/redoc>
OpenAPI JSON: <http://localhost:9091/openapi.json>

---

## 3. 환경 변수 (`server/.env`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `API_KEY` | `change-me` | `/auth/token` 호출에 필요한 마스터 비밀. **운영 시 반드시 교체** |
| `JWT_SECRET` | `replace-with-a-long-random-secret` | JWT 서명 비밀. 32바이트+ 랜덤 권장 |
| `JWT_ALGORITHM` | `HS256` | JWT 서명 알고리즘 |
| `JWT_EXPIRE_MINUTES` | `60` | 발급 JWT 유효 시간(분) |
| `DEFAULT_MODEL` | `opus` | `/chat`에서 `model` 미지정 시 사용할 Claude 모델 |
| `CLAUDE_CLI_PATH` | `claude` | Claude CLI 실행 파일 경로. 절대경로 가능 |
| `CLAUDE_TIMEOUT` | `300` | Claude CLI 한 번 호출의 최대 대기 시간(초) |
| `ADMIN_USER` | `admin` | 관리 대시보드 로그인 아이디 |
| `ADMIN_PASSWORD` | (빈 값) | 관리 대시보드 로그인 비밀번호. **비어 있으면 로그인 불가**. 운영 시 Jenkins Credentials 로 주입 |
| `ADMIN_SESSION_MINUTES` | `480` | 관리 대시보드 세션(쿠키) 유효 시간(분) |
| `DATA_DIR` | `data` | 요청 수 집계 SQLite(`app.db`) 저장 디렉터리. 컨테이너에선 `/app/data` 볼륨 |
| `HOST` | `0.0.0.0` | 바인딩 주소 |
| `PORT` | `9091` | 바인딩 포트 |

`.env`는 `pydantic-settings`가 자동 로드한다 (`server/config.py`). 환경변수가 있으면 `.env`보다 우선.

---

## 4. 인증 흐름

2단계 구조다.

1. **API_KEY → JWT 발급**: 장기 비밀(`API_KEY`)을 1회만 사용해 단기 토큰(JWT)을 받는다.
2. **JWT → API 호출**: 매 요청에 `Authorization: Bearer <JWT>` 첨부.

| 항목 | API_KEY | JWT |
|---|---|---|
| 수명 | 영구 (교체까지) | `JWT_EXPIRE_MINUTES` (기본 60분) |
| 보관 위치 | 서버 + 발급 클라이언트만 | 클라이언트 보관 가능 |
| 검증 방식 | 평문 비교 | HS256 서명 검증 |
| 클레임 | — | `sub`(client_id), `iat`, `exp` |

JWT가 만료되면 `/auth/token`을 다시 호출해 재발급한다. 서버는 무상태이므로 발급된 JWT를 별도로 폐기하는 기능은 없다(즉시 폐기가 필요하면 `JWT_SECRET`을 교체하고 서버를 재기동하면 모든 기존 토큰이 무효화된다).

---

## 5. API 레퍼런스

### 5.1 `GET /health`

서버 헬스체크. 인증 불필요.

응답:
```json
{ "status": "ok" }
```

---

### 5.2 `POST /auth/token`

마스터 API 키를 검증하고 JWT를 발급한다. 인증 불필요.

요청:
```json
{
  "api_key": "change-me",
  "client_id": "service-a"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `api_key` | string | ✅ | `.env`의 `API_KEY`와 정확히 일치해야 함 |
| `client_id` | string | ❌ | JWT의 `sub` 클레임에 박힐 라벨. 없으면 `"default"` |

응답 200:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

응답 401:
```json
{ "detail": "Invalid API key" }
```

---

### 5.3 `POST /chat`

자연어 질의를 Claude CLI로 전달한다. **인증 필요**: `Authorization: Bearer <JWT>`.

요청:
```json
{
  "question": "오늘 추천 점심 메뉴",
  "model": "opus"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `question` | string (≥1자) | ✅ | 자연어 질의 |
| `model` | string \| null | ❌ | Claude 모델 alias 또는 ID. 미지정 시 `DEFAULT_MODEL` 사용 |

응답 200:
```json
{
  "answer": "김치찌개 추천합니다. 비 오는 날엔 따뜻한 국물이 최고예요.",
  "model": "opus"
}
```

응답 401: JWT 누락 / 만료 / 위조
```json
{ "detail": "Invalid or expired token" }
```

응답 502: Claude CLI 실패 (모델 미존재, 타임아웃, CLI 미설치 등)
```json
{
  "detail": "Claude CLI exited with code 1: There's an issue with the selected model (string)..."
}
```

서버는 Claude CLI를 `subprocess`로 실행한다:
```bash
claude -p --model <model> --output-format json <question>
```
CLI가 stdout JSON으로 돌려준 `result` 문자열이 그대로 `answer`가 된다.

### 5.4 웹 관리 대시보드 (`GET /`)

브라우저로 `http://<host>:<port>/` 에 접속하면 **id/pw 로그인** 후 사용하는 관리 화면이 뜬다.

- **로그인**: `ADMIN_USER` / `ADMIN_PASSWORD`(환경변수)로 인증. 성공 시 서명된 세션 쿠키(HttpOnly)가 발급된다.
- **총 요청 수**: 들어온 API 요청을 로컬 SQLite(`DATA_DIR/app.db`)에 기록해 집계한다 — 총 요청 수 / `/chat` 요청 수 / 최근 24시간. (헬스체크·관리 페이지·Swagger 요청은 집계 제외)
- **클라이언트별 요청 수**: 토큰 발급 시 넘긴 `client_id`(JWT 의 `sub`) 기준으로 클라이언트별 총 요청·`/chat` 요청·마지막 요청 시각을 보여준다. `client_id` 미지정 요청은 `default` 로 집계된다.
- **API 키 노출**: 현재 구조는 서버 전체 단일 마스터 키(`API_KEY`) 1개이며, 그 값을 화면에 노출한다. 클라이언트는 이 키로 `POST /auth/token` 을 호출하면서 원하는 `client_id` 를 지정해 토큰을 받는다(클라이언트별 키 발급/폐기는 없음).
- **JWT_SECRET 변경**: 폼에서 새 비밀(16자+)을 입력하면 DB `settings` 테이블에 저장되어 `.env` 의 `JWT_SECRET` 을 **즉시 덮어쓴다**(재기동 불필요). 변경 시 기존에 발급된 모든 JWT 와 관리 세션이 무효화되므로 재로그인이 필요하다.

| 경로 | 메서드 | 설명 |
|---|---|---|
| `/` | GET | 대시보드(미로그인 시 `/admin/login` 으로 이동) |
| `/admin/login` | GET/POST | 로그인 폼 / 자격 검증 |
| `/admin/logout` | POST | 로그아웃 |
| `/admin/jwt-secret` | POST | JWT_SECRET 변경 |

> 집계 DB와 변경된 JWT_SECRET 은 `ysclaude-data` 볼륨(`/app/data`)에 저장되어 재배포에도 유지된다.

---

## 6. End-to-end 예제

### 6.1 cURL

```bash
# 1) 토큰 발급
TOKEN=$(curl -s -X POST http://localhost:9091/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key":"change-me","client_id":"demo"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# 2) /chat 호출
curl -s -X POST http://localhost:9091/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"파이썬에서 dict을 JSON으로 변환하는 방법?"}'
```

### 6.2 Python (`httpx`)

```python
import httpx

BASE = "http://localhost:9091"
API_KEY = "change-me"

with httpx.Client(base_url=BASE, timeout=300) as client:
    r = client.post("/auth/token", json={"api_key": API_KEY, "client_id": "demo"})
    r.raise_for_status()
    token = r.json()["access_token"]

    r = client.post(
        "/chat",
        json={"question": "FastAPI에서 의존성 주입 예제"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    print(r.json()["answer"])
```

### 6.3 JavaScript (`fetch`)

```js
const BASE = "http://localhost:9091";

const { access_token } = await fetch(`${BASE}/auth/token`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ api_key: "change-me", client_id: "demo" }),
}).then(r => r.json());

const res = await fetch(`${BASE}/chat`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${access_token}`,
  },
  body: JSON.stringify({ question: "Node.js에서 SSE 구현 방법" }),
}).then(r => r.json());

console.log(res.answer);
```

---

## 7. Swagger UI에서 테스트하기

1. <http://localhost:9091/docs> 접속
2. `POST /auth/token` → "Try it out" → 본문 그대로 (또는 `client_id` 수정) → "Execute"
3. 응답의 `access_token` 값 복사
4. 페이지 **우측 상단 "Authorize" 버튼** (자물쇠 아이콘) 클릭
5. `Value`에 토큰만 붙여넣기 (**`Bearer ` 접두사 X — 자동 첨부**) → "Authorize" → "Close"
6. `POST /chat` → "Try it out" → 본문 작성 → "Execute"

> Swagger 본문 example의 `"model": "string"` 같은 placeholder는 그대로 보내면 안 된다. 실제 모델 alias(`opus`, `sonnet` 등)로 바꾸거나 필드를 지운다.

---

## 8. 프로젝트 구조

```
yclaude/
├── README.md
└── server/
    ├── .env                  # 로컬 환경변수 (git ignore)
    ├── .env.example          # 환경변수 템플릿
    ├── requirements.txt
    ├── config.py             # pydantic-settings 기반 Settings
    ├── auth.py               # JWT 발급/검증, HTTPBearer 의존성
    ├── claude_client.py      # Claude CLI subprocess 호출 래퍼
    ├── db.py                 # 로컬 SQLite (요청 수 집계 + JWT_SECRET 오버라이드)
    ├── admin.py              # 관리 대시보드(로그인/통계/JWT_SECRET 변경)
    └── main.py               # FastAPI app, 엔드포인트 정의
```

핵심 파일별 진입점:

- 새 엔드포인트 추가 → `server/main.py`
- Claude CLI 인자/파싱 변경 → `server/claude_client.py:ask_claude`
- 인증 정책 변경 → `server/auth.py`
- 요청 집계 / DB 스키마 → `server/db.py`
- 대시보드 화면·로직 → `server/admin.py`
- 설정 항목 추가 → `server/config.py` + `.env.example`

---

## 9. 운영 / 보안 체크리스트

- [ ] `API_KEY`, `JWT_SECRET`을 기본값(`change-me`, `replace-with-...`)에서 충분히 긴 랜덤값으로 교체
- [ ] `ADMIN_PASSWORD`를 설정(비어 있으면 대시보드 로그인 자체가 막힘). 운영에선 Jenkins Credentials(`ysclaude-admin`)로 주입 권장
- [ ] `.env`를 git에 커밋하지 않을 것 (`.gitignore` 확인)
- [ ] 대시보드는 HTTP 세션 쿠키를 쓰므로(평문 HTTP에선 secure 미설정) 외부 노출 시 HTTPS 리버스 프록시(nginx, Caddy 등) 뒤에 두기
- [ ] `CLAUDE_TIMEOUT`을 호출 패턴에 맞게 조정 (긴 답변이 잘리지 않도록)
- [ ] Claude CLI가 실행되는 사용자 컨텍스트로 사전 로그인되어 있는지 확인 (`claude` 명령 1회 수동 실행)
- [ ] 동시 요청이 많아질 경우, Claude CLI를 `subprocess`로 매번 띄우는 비용 고려 (현재 구조는 요청당 새 프로세스)

---

## 10. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `Claude CLI not found at 'claude'` | CLI 미설치 또는 PATH 미반영. `CLAUDE_CLI_PATH`에 절대경로 지정 |
| `Claude CLI exited with code 1: There's an issue with the selected model (...)` | `model` 값이 유효하지 않음. `opus` / `sonnet` 등으로 변경하거나 필드 제거 |
| `Claude CLI timed out after 300s` | `CLAUDE_TIMEOUT` 상향 또는 더 짧은 질의로 분할 |
| `Invalid or expired token` | JWT 만료(기본 60분) — `/auth/token` 재호출 |
| `Invalid API key` | `.env`의 `API_KEY`와 요청 본문 값이 다름 |
| 포트 충돌 (`Address already in use`) | 다른 프로세스가 점유 중. `lsof -iTCP:9091 -sTCP:LISTEN`로 확인 후 `PORT` 변경 |

---

## 11. 라이선스

내부 사용. 외부 배포 전 정책 확인 필요.
