"""관리자 웹 대시보드.

- GET  /                  → 대시보드(미로그인 시 /admin/login 으로 이동)
- GET  /admin/login       → 로그인 폼
- POST /admin/login       → id/pw 검증 후 세션 쿠키 발급
- POST /admin/logout      → 로그아웃
- POST /admin/jwt-secret  → JWT_SECRET 변경(DB 저장, 즉시 반영)

로그인 자격(admin_user / admin_password)은 환경변수(Jenkins 주입)로 설정한다.
세션은 JWT 로 서명한 HttpOnly 쿠키로 유지한다.
"""
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt

import db
from config import settings

router = APIRouter()

SESSION_COOKIE = "ys_admin_session"


def _create_session() -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.admin_session_minutes
    )
    payload = {"sub": settings.admin_user, "role": "admin", "exp": expire}
    return jwt.encode(payload, db.get_jwt_secret(), algorithm=settings.jwt_algorithm)


def _is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        payload = jwt.decode(
            token, db.get_jwt_secret(), algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return False
    return payload.get("role") == "admin"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
          margin: 0; background: #0f172a; color: #e2e8f0; }}
  .wrap {{ max-width: 720px; margin: 0 auto; padding: 48px 20px; }}
  h1 {{ font-size: 22px; margin: 0 0 24px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px;
           padding: 24px; margin-bottom: 20px; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  .stat {{ background: #0f172a; border-radius: 10px; padding: 18px; text-align: center; }}
  .stat .num {{ font-size: 32px; font-weight: 700; color: #38bdf8; }}
  .stat .label {{ font-size: 13px; color: #94a3b8; margin-top: 6px; }}
  label {{ display: block; font-size: 13px; color: #94a3b8; margin: 12px 0 6px; }}
  input[type=text], input[type=password] {{
    width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px;
    border: 1px solid #334155; background: #0f172a; color: #e2e8f0; font-size: 14px; }}
  button {{ margin-top: 16px; padding: 10px 18px; border: 0; border-radius: 8px;
            background: #2563eb; color: #fff; font-size: 14px; cursor: pointer; }}
  button.secondary {{ background: #475569; }}
  .row {{ display: flex; justify-content: space-between; align-items: center; }}
  .msg {{ padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }}
  .msg.ok {{ background: #064e3b; color: #6ee7b7; }}
  .msg.err {{ background: #7f1d1d; color: #fca5a5; }}
  code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px;
          word-break: break-all; }}
  .hint {{ font-size: 12px; color: #64748b; margin-top: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-weight: 600; font-size: 12px; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .kv {{ font-size: 13px; color: #94a3b8; margin: 6px 0 2px; }}
</style>
</head>
<body><div class="wrap">{body}</div></body>
</html>"""


def _msg(request: Request) -> str:
    ok = request.query_params.get("ok")
    err = request.query_params.get("err")
    if ok:
        return f'<div class="msg ok">{escape(ok)}</div>'
    if err:
        return f'<div class="msg err">{escape(err)}</div>'
    return ""


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    stats = db.get_stats()
    clients = db.get_client_stats()
    has_override = db.get_setting("jwt_secret") is not None
    source = "UI 변경값(DB)" if has_override else ".env 기본값"

    if clients:
        client_rows = "".join(
            f"<tr><td>{escape(c['client'])}</td>"
            f"<td class='num'>{c['total']}</td>"
            f"<td class='num'>{c['chat']}</td>"
            f"<td>{escape((c['last_seen'] or '')[:19].replace('T', ' '))}</td></tr>"
            for c in clients
        )
    else:
        client_rows = (
            "<tr><td colspan='4' style='color:#64748b'>아직 요청이 없습니다.</td></tr>"
        )

    body = f"""
    <div class="row">
      <h1>yclaude 관리 대시보드</h1>
      <form method="post" action="/admin/logout">
        <button class="secondary" type="submit">로그아웃</button>
      </form>
    </div>
    {_msg(request)}
    <div class="card">
      <div class="stats">
        <div class="stat"><div class="num">{stats['total']}</div><div class="label">총 요청 수</div></div>
        <div class="stat"><div class="num">{stats['chat']}</div><div class="label">/chat 요청</div></div>
        <div class="stat"><div class="num">{stats['last_24h']}</div><div class="label">최근 24시간</div></div>
      </div>
    </div>
    <div class="card">
      <h1 style="font-size:18px">클라이언트별 요청 수</h1>
      <p class="hint">클라이언트 = 토큰 발급 시 넘긴 <code>client_id</code>(JWT 의 <code>sub</code>).
      <code>client_id</code> 미지정 시 <code>default</code> 로 집계됩니다.</p>
      <table>
        <thead><tr><th>클라이언트(client_id)</th><th class="num">총 요청</th>
        <th class="num">/chat</th><th>마지막 요청(UTC)</th></tr></thead>
        <tbody>{client_rows}</tbody>
      </table>
    </div>
    <div class="card">
      <h1 style="font-size:18px">API 키 (모든 클라이언트 공용)</h1>
      <p class="hint">현재 구조는 서버 전체에 단일 마스터 키 1개입니다. 클라이언트는 이 키로
      <code>POST /auth/token</code> 을 호출해 토큰을 발급받습니다(원하는 <code>client_id</code> 지정).</p>
      <div class="kv">API_KEY</div>
      <code>{escape(settings.api_key)}</code>
    </div>
    <div class="card">
      <h1 style="font-size:18px">JWT_SECRET 변경</h1>
      <p class="hint">현재 적용 소스: <code>{escape(source)}</code> ·
      변경 시 기존에 발급된 액세스 토큰은 모두 무효화되고, 관리자 세션도 재로그인이 필요합니다.</p>
      <form method="post" action="/admin/jwt-secret">
        <label for="new_secret">새 JWT_SECRET (최소 16자)</label>
        <input type="text" id="new_secret" name="new_secret" autocomplete="off"
               placeholder="길고 무작위한 문자열">
        <button type="submit">변경 적용</button>
      </form>
    </div>
    """
    return HTMLResponse(_page("yclaude 관리 대시보드", body))


@router.get("/admin/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if _is_logged_in(request):
        return RedirectResponse(url="/", status_code=302)
    body = f"""
    <h1>yclaude 관리자 로그인</h1>
    {_msg(request)}
    <div class="card">
      <form method="post" action="/admin/login">
        <label for="username">아이디</label>
        <input type="text" id="username" name="username" autocomplete="username">
        <label for="password">비밀번호</label>
        <input type="password" id="password" name="password" autocomplete="current-password">
        <button type="submit">로그인</button>
      </form>
    </div>
    """
    return HTMLResponse(_page("로그인", body))


@router.post("/admin/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if not settings.admin_password:
        return RedirectResponse(
            url="/admin/login?err=" + "ADMIN_PASSWORD 가 서버에 설정되지 않았습니다",
            status_code=302,
        )
    ok_user = secrets.compare_digest(username, settings.admin_user)
    ok_pw = secrets.compare_digest(password, settings.admin_password)
    if not (ok_user and ok_pw):
        return RedirectResponse(
            url="/admin/login?err=아이디 또는 비밀번호가 올바르지 않습니다",
            status_code=302,
        )
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        _create_session(),
        max_age=settings.admin_session_minutes * 60,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/admin/logout")
async def logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.post("/admin/jwt-secret")
async def change_jwt_secret(request: Request, new_secret: str = Form(...)):
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    new_secret = new_secret.strip()
    if len(new_secret) < 16:
        return RedirectResponse(
            url="/?err=JWT_SECRET 은 최소 16자 이상이어야 합니다", status_code=302
        )
    db.set_setting("jwt_secret", new_secret)
    # 비밀이 바뀌면 기존 세션 쿠키는 새 비밀로 검증되지 않으므로 재로그인 필요.
    resp = RedirectResponse(
        url="/admin/login?ok=JWT_SECRET 이 변경되었습니다. 다시 로그인하세요",
        status_code=302,
    )
    resp.delete_cookie(SESSION_COOKIE)
    return resp
