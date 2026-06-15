"""로컬 SQLite 저장소.

- request_log: 들어온 요청을 기록(총 요청 수 집계용)
- settings: 런타임에 바꿀 수 있는 설정값(JWT_SECRET 등) 저장

DB 파일은 settings.data_dir 아래(app.db)에 생성된다. 컨테이너에서는
/app/data 볼륨에 영구 저장되므로 재배포에도 값이 유지된다.
"""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import settings

_db_path: Path | None = None
_lock = threading.Lock()


def _path() -> Path:
    global _db_path
    if _db_path is None:
        data_dir = Path(settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        _db_path = data_dir / "app.db"
    return _db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                path      TEXT    NOT NULL,
                method    TEXT    NOT NULL,
                status    INTEGER NOT NULL,
                client    TEXT
            )
            """
        )
        # 기존(구버전) DB 호환: client 컬럼이 없으면 추가
        cols = {row[1] for row in conn.execute("PRAGMA table_info(request_log)")}
        if "client" not in cols:
            conn.execute("ALTER TABLE request_log ADD COLUMN client TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log(ts)"
        )


def log_request(
    path: str, method: str, status: int, client: str | None = None
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO request_log (ts, path, method, status, client) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, path, method, status, client),
        )


def get_stats() -> dict[str, int]:
    """대시보드에 표시할 집계값."""
    day_ago = datetime.now(timezone.utc).timestamp() - 86400
    day_ago_iso = datetime.fromtimestamp(day_ago, timezone.utc).isoformat()
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM request_log").fetchone()[0]
        chat = conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE path = '/chat'"
        ).fetchone()[0]
        last_24h = conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE ts >= ?", (day_ago_iso,)
        ).fetchone()[0]
    return {"total": total, "chat": chat, "last_24h": last_24h}


def get_client_stats() -> list[dict]:
    """클라이언트(토큰 sub = client_id)별 요청 집계."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(client, '(미인증/토큰없음)') AS c,
                   COUNT(*)                                AS total,
                   SUM(CASE WHEN path = '/chat' THEN 1 ELSE 0 END) AS chat,
                   MAX(ts)                                 AS last_seen
            FROM request_log
            GROUP BY c
            ORDER BY total DESC
            """
        ).fetchall()
    return [
        {"client": r[0], "total": r[1], "chat": r[2] or 0, "last_seen": r[3]}
        for r in rows
    ]


def get_setting(key: str) -> str | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def set_setting(key: str, value: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_jwt_secret() -> str:
    """런타임에 유효한 JWT 서명 비밀.

    UI 에서 변경하면 settings 테이블 값이 .env 의 JWT_SECRET 을 덮어쓴다.
    """
    return get_setting("jwt_secret") or settings.jwt_secret
