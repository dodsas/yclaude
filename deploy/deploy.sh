#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-ysclaude}"
APP_DIR="${APP_DIR:-/home/dodsas/work/${APP_NAME}}"
HOST_PORT="${HOST_PORT:-9091}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yml}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_RETAIN="${IMAGE_RETAIN:-3}"
IMAGE_NAME="localhost/${APP_NAME}"

log() { printf '[deploy] %s\n' "$*"; }

if [ ! -d "$APP_DIR" ]; then
  log "APP_DIR이 존재하지 않습니다: $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

# 로그 디렉터리 (compose.yml 의 ./logs 바인드 마운트 대상)
mkdir -p "$APP_DIR/logs"
chmod 777 "$APP_DIR/logs"  # 컨테이너 안 app 사용자가 쓸 수 있도록

# Claude CLI 인증 정보 마운트 경로 결정
# 우선순위: CLAUDE_HOST_DIR (env) → ~/.claude (호스트 사용자 홈) → ./secrets/claude (placeholder)
if [ -n "${CLAUDE_HOST_DIR:-}" ]; then
  log "Claude 인증 디렉터리: ${CLAUDE_HOST_DIR} (CLAUDE_HOST_DIR 지정)"
elif [ -d "$HOME/.claude" ] && [ -n "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
  export CLAUDE_HOST_DIR="$HOME/.claude"
  log "Claude 인증 디렉터리: ${CLAUDE_HOST_DIR} (호스트 홈 자동 감지)"
else
  mkdir -p "$APP_DIR/secrets/claude"
  chmod 700 "$APP_DIR/secrets/claude"
  export CLAUDE_HOST_DIR="$APP_DIR/secrets/claude"
  log "Claude 인증 디렉터리: ${CLAUDE_HOST_DIR} (placeholder, 비어 있음)"
  log "  → /chat 호출 시 인증 오류 가능. 호스트에서 'claude' 1회 인증 후 다음 중 하나:"
  log "  (a) ~/.claude 가 자동 감지되도록 두기"
  log "  (b) CLAUDE_HOST_DIR 환경변수로 다른 경로 지정"
  log "  (c) rsync -a ~/.claude/ ${APP_DIR}/secrets/claude/"
fi

# 비밀값 파일 (.env) 은 호스트 디스크에서 관리. git archive 가 .env 를 포함하지 않으므로
# tar 전개시에도 보존됨 → 서버에서 한 번 작성해 두면 이후 배포는 손대지 않는다.
# 최초 배포 시에만 server/.env.example 을 부트스트랩 템플릿으로 복사한다.
if [ ! -f "$APP_DIR/.env" ]; then
  if [ -f "$APP_DIR/server/.env.example" ]; then
    install -m 600 "$APP_DIR/server/.env.example" "$APP_DIR/.env"
    log ".env 부트스트랩: server/.env.example 복사 — 실 운영값으로 ${APP_DIR}/.env 직접 편집 필요"
  else
    log ".env 도, server/.env.example 도 없음. ${APP_DIR}/.env 를 작성하세요."
    exit 1
  fi
else
  log ".env 가 호스트에 존재 — 보존 (수정은 ${APP_DIR}/.env 직접 편집)"
fi
chmod 600 "$APP_DIR/.env" 2>/dev/null || true

# 관리자 대시보드 자격증명(.env upsert).
# Jenkins 가 ADMIN_USER / ADMIN_PASSWORD 를 환경변수로 넘기면 매 배포 시 .env 에 반영한다.
# (Jenkins 를 단일 진실원천으로 두기 위함. 값이 없으면 기존 .env 값을 그대로 둔다.)
upsert_env() {
  local key="$1" value="$2" file="$APP_DIR/.env"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    # 구분자로 | 사용(값에 / 등이 포함돼도 안전), 값은 sed 특수문자 이스케이프
    local esc
    esc=$(printf '%s' "$value" | sed -e 's/[&|\\]/\\&/g')
    sed -i "s|^${key}=.*|${key}=${esc}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

if [ -n "${ADMIN_USER:-}" ]; then
  upsert_env "ADMIN_USER" "$ADMIN_USER"
  log "ADMIN_USER 를 .env 에 반영"
fi
if [ -n "${ADMIN_PASSWORD:-}" ]; then
  upsert_env "ADMIN_PASSWORD" "$ADMIN_PASSWORD"
  log "ADMIN_PASSWORD 를 .env 에 반영 (값은 로그에 출력하지 않음)"
fi

if ! command -v podman-compose >/dev/null 2>&1; then
  log "podman-compose 명령을 찾을 수 없습니다."
  log "설치: sudo dnf install -y podman-compose  (또는 pip install --user podman-compose)"
  exit 1
fi

export HOST_PORT IMAGE_TAG CLAUDE_HOST_DIR

log "이미지 태그: ${IMAGE_NAME}:${IMAGE_TAG}"

log "podman-compose: 빌드"
podman-compose -f "$COMPOSE_FILE" build

# latest 태그도 함께 부여 (compose default 호환)
if [ "$IMAGE_TAG" != "latest" ]; then
  podman tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_NAME}:latest"
fi

log "podman-compose: 기존 컨테이너 중지/제거"
podman-compose -f "$COMPOSE_FILE" down --remove-orphans || true

log "podman-compose: 기동"
podman-compose -f "$COMPOSE_FILE" up -d

log "헬스체크 (최대 30초 대기)"
HEALTH_OK=0
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${HOST_PORT}/health" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [ "$HEALTH_OK" -ne 1 ]; then
  log "✗ 헬스체크 실패. 로그:"
  podman-compose -f "$COMPOSE_FILE" logs --tail 50 || true
  exit 1
fi

log "✓ 헬스체크 통과 — http://$(hostname):${HOST_PORT}"

# ysclaude 이미지만 정리 — 다른 서비스(ysadmin, dokuwiki 등)에 영향 주지 않음
log "이미지 정리 (최근 ${IMAGE_RETAIN}개 유지)"
# 1) dangling (untagged) 중 ysclaude만
podman images --filter "dangling=true" --filter "reference=${IMAGE_NAME}" --format "{{.ID}}" \
  | xargs -r podman rmi 2>/dev/null || true

# 2) 태그된 ysclaude 이미지 중 오래된 것 제거 (latest 제외)
podman images "${IMAGE_NAME}" --format "{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}" \
  | grep -v -E "^latest\b" \
  | sort -k3 -r \
  | awk -v keep="$IMAGE_RETAIN" 'NR > keep {print $2}' \
  | xargs -r podman rmi 2>/dev/null || true

log "완료."
