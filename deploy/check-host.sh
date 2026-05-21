#!/usr/bin/env bash
# Podman 호스트 환경 진단 — linger 필요 여부 판단용
# 사용법:
#   ./check-host.sh
# (대상 사용자명을 바꾸려면 USER_NAME 환경변수)
set -u

USER_NAME="${USER_NAME:-${USER:-$(whoami)}}"
APP_NAME="${APP_NAME:-ysclaude}"

color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
ok()    { printf '  %s %s\n' "$(color '32' '✓')" "$1"; }
warn()  { printf '  %s %s\n' "$(color '33' '!')" "$1"; }
fail()  { printf '  %s %s\n' "$(color '31' '✗')" "$1"; }
info()  { printf '  %s %s\n' "·" "$1"; }
hr()    { printf '\n%s\n' "$(color '36' "=== $1 ===")"; }

NEED_LINGER=0
HAS_SYSTEMD_UNIT=0
KILL_USER_PROC_OFF=0

hr "대상 사용자: ${USER_NAME} / 앱: ${APP_NAME}"

hr "1. linger 상태"
LINGER_RAW="$(loginctl show-user "$USER_NAME" 2>/dev/null | grep '^Linger=' || true)"
if [ -z "$LINGER_RAW" ]; then
  warn "loginctl이 ${USER_NAME} 정보를 모릅니다 (현재 로그인 중 아닐 수 있음)"
  if [ -f "/var/lib/systemd/linger/${USER_NAME}" ]; then
    ok "/var/lib/systemd/linger/${USER_NAME} 파일 존재 → linger 켜진 것으로 판단"
    LINGER="yes"
  else
    fail "linger 파일도 없음 → 꺼져있을 가능성 높음"
    LINGER="no"
  fi
else
  echo "    ${LINGER_RAW}"
  LINGER="${LINGER_RAW#Linger=}"
  if [ "$LINGER" = "yes" ]; then ok "이미 켜져 있음"; else fail "꺼져 있음"; fi
fi

hr "2. KillUserProcesses 설정"
KUP_RAW="$(grep -E '^\s*KillUserProcesses' /etc/systemd/logind.conf 2>/dev/null || true)"
if [ -z "$KUP_RAW" ]; then
  # 명시적 설정 없으면 기본값 yes
  info "/etc/systemd/logind.conf에 명시 없음 → 기본값 KillUserProcesses=yes (로그아웃 시 프로세스 종료)"
  echo "    추가 확인:"
  KUP_DROPIN="$(grep -rE '^\s*KillUserProcesses' /etc/systemd/logind.conf.d/ 2>/dev/null || true)"
  if [ -n "$KUP_DROPIN" ]; then
    echo "    drop-in: ${KUP_DROPIN}"
    if echo "$KUP_DROPIN" | grep -qE '=\s*no'; then
      ok "drop-in에서 KillUserProcesses=no — 로그아웃해도 프로세스 유지됨"
      KILL_USER_PROC_OFF=1
    fi
  fi
else
  echo "    ${KUP_RAW}"
  if echo "$KUP_RAW" | grep -qE '=\s*no'; then
    ok "KillUserProcesses=no — 로그아웃해도 프로세스 유지됨"
    KILL_USER_PROC_OFF=1
  else
    info "KillUserProcesses=yes — 로그아웃 시 프로세스 종료"
  fi
fi

hr "3. Podman 모드"
if command -v podman >/dev/null 2>&1; then
  PODMAN_VER="$(podman --version 2>/dev/null | head -1)"
  info "${PODMAN_VER}"
  ROOTLESS="$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null || echo 'unknown')"
  echo "    rootless: ${ROOTLESS}"
  RUN_ROOT="$(podman info --format '{{.Store.RunRoot}}' 2>/dev/null || true)"
  echo "    runRoot: ${RUN_ROOT}"
else
  fail "podman 명령을 찾을 수 없음"
fi

hr "4. 현재 실행 중인 컨테이너 (rootless)"
ROOTLESS_CT="$(podman ps --format '{{.Names}} ({{.Status}})' 2>/dev/null || true)"
if [ -z "$ROOTLESS_CT" ]; then
  info "(없음)"
else
  echo "$ROOTLESS_CT" | sed 's/^/    /'
fi

hr "5. 현재 실행 중인 컨테이너 (rootful)"
if [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null; then
  ROOTFUL_CT="$(sudo podman ps --format '{{.Names}} ({{.Status}})' 2>/dev/null || true)"
  if [ -z "$ROOTFUL_CT" ]; then
    info "(없음)"
  else
    echo "$ROOTFUL_CT" | sed 's/^/    /'
  fi
else
  warn "sudo 비밀번호가 필요해서 스킵. 수동으로: sudo podman ps"
fi

hr "6. systemd user unit 으로 등록된 컨테이너"
USER_UNITS="$(systemctl --user list-units --type=service --all 'container-*' --no-legend 2>/dev/null | awk '{print $1, "→", $4}' || true)"
if [ -z "$USER_UNITS" ]; then
  info "(없음)"
else
  echo "$USER_UNITS" | sed 's/^/    /'
  HAS_SYSTEMD_UNIT=1
fi

hr "7. systemd system unit 으로 등록된 컨테이너"
SYS_UNITS="$(systemctl list-units --type=service --all 'container-*' --no-legend 2>/dev/null | awk '{print $1, "→", $4}' || true)"
if [ -z "$SYS_UNITS" ]; then
  info "(없음)"
else
  echo "$SYS_UNITS" | sed 's/^/    /'
  HAS_SYSTEMD_UNIT=1
fi

hr "8. Quadlet 파일 존재 여부"
for d in "${HOME}/.config/containers/systemd" "/etc/containers/systemd"; do
  if [ -d "$d" ]; then
    FILES="$(ls "$d" 2>/dev/null | grep -E '\.(container|kube|volume|network)$' || true)"
    if [ -n "$FILES" ]; then
      echo "    ${d}:"
      echo "$FILES" | sed 's/^/      /'
      HAS_SYSTEMD_UNIT=1
    fi
  fi
done
[ "$HAS_SYSTEMD_UNIT" -eq 0 ] && info "(Quadlet 파일 없음)"

hr "9. 현재 활성 세션"
loginctl list-sessions --no-legend 2>/dev/null | sed 's/^/    /' || warn "확인 불가"

hr "10. 세션 상세 — 누가 세션을 잡고 있는가"
SESSION_IDS="$(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$USER_NAME" '$3==u {print $1}' || true)"
if [ -z "$SESSION_IDS" ]; then
  info "${USER_NAME} 사용자의 활성 세션 없음"
else
  for sid in $SESSION_IDS; do
    echo "    --- 세션 #${sid} ---"
    loginctl show-session "$sid" 2>/dev/null \
      | grep -E '^(Id|Name|User|Type|Class|Service|State|Active|Remote|RemoteHost|Display|TTY|Scope|Leader|IdleHint|IdleSinceHint)=' \
      | sed 's/^/      /'
    LEADER_PID="$(loginctl show-session "$sid" -p Leader --value 2>/dev/null)"
    if [ -n "$LEADER_PID" ] && [ "$LEADER_PID" != "0" ]; then
      LEADER_CMD="$(ps -p "$LEADER_PID" -o user=,cmd= 2>/dev/null || true)"
      [ -n "$LEADER_CMD" ] && echo "      LeaderProcess=${LEADER_CMD}"
      LEADER_PARENT="$(ps -p "$LEADER_PID" -o ppid= 2>/dev/null | tr -d ' ')"
      if [ -n "$LEADER_PARENT" ] && [ "$LEADER_PARENT" != "0" ]; then
        PARENT_CMD="$(ps -p "$LEADER_PARENT" -o user=,cmd= 2>/dev/null || true)"
        [ -n "$PARENT_CMD" ] && echo "      ParentOfLeader=${PARENT_CMD}"
      fi
    fi
  done
fi

hr "11. user@<uid>.service 상태 (사용자 systemd 인스턴스)"
USER_UID="$(id -u "$USER_NAME" 2>/dev/null || true)"
if [ -n "$USER_UID" ]; then
  USER_MGR_STATE="$(systemctl is-active "user@${USER_UID}.service" 2>/dev/null || true)"
  USER_MGR_ENABLED="$(systemctl is-enabled "user@${USER_UID}.service" 2>/dev/null || true)"
  echo "    user@${USER_UID}.service: state=${USER_MGR_STATE}, enabled=${USER_MGR_ENABLED}"
  if [ "$USER_MGR_STATE" = "active" ]; then
    SINCE="$(systemctl show "user@${USER_UID}.service" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
    [ -n "$SINCE" ] && info "활성화된 시점: ${SINCE}"
    info "이 service가 살아있는 한 rootless 컨테이너도 유지됨"
  fi
fi

hr "12. 세션을 만드는 가능한 출처"
echo "    (해당 서비스가 떠있으면 자동으로 ${USER_NAME} 세션을 만들 수 있음)"
for svc in cockpit.socket cockpit.service sshd.service gdm.service; do
  if systemctl is-active "$svc" >/dev/null 2>&1; then
    ok "$svc 활성 중"
  fi
done
echo "    'web console' 타입 세션이 보이면 Cockpit이 가장 유력한 원인"

hr "결론"
if [ "$LINGER" = "yes" ]; then
  ok "linger 이미 켜져 있음 → 추가 작업 불필요"
elif [ "$KILL_USER_PROC_OFF" -eq 1 ]; then
  ok "KillUserProcesses=no 로 운영 중 → 로그아웃해도 프로세스 유지됨 → linger 불필요"
elif [ "$HAS_SYSTEMD_UNIT" -eq 1 ]; then
  warn "systemd unit으로 컨테이너 운영 중 → 그 unit 메커니즘으로 유지되는 것"
  warn "${APP_NAME}도 동일하게 systemd unit (Quadlet) 방식으로 운영하면 linger 필요"
  warn "단순 'podman run -d' 방식이면 linger 권장"
  NEED_LINGER=1
else
  fail "linger 꺼져있고, 다른 보호 메커니즘도 안 보임"
  if [ -n "$SESSION_IDS" ]; then
    warn "→ 다만 ${USER_NAME} 세션이 떠있어서 user systemd가 살아있는 상태"
    warn "→ 그래서 컨테이너가 지금까지 유지되고 있는 것"
    warn "→ 그 세션이 끊기면 (Cockpit 로그아웃/타임아웃, 호스트 재부팅 등) 모든 컨테이너 죽음"
    warn "→ 안정성을 위해 권장: sudo loginctl enable-linger ${USER_NAME}"
  else
    fail "→ 권장: sudo loginctl enable-linger ${USER_NAME} 1회 실행"
  fi
  NEED_LINGER=1
fi

echo
if [ "$NEED_LINGER" -eq 1 ]; then
  echo "권장 명령: $(color '33' "sudo loginctl enable-linger ${USER_NAME}")"
fi
