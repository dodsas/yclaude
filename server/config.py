from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str = "change-me"
    jwt_secret: str = "replace-with-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    default_model: str = "opus"
    claude_cli_path: str = "claude"
    claude_timeout: int = 300

    # 관리자 대시보드 로그인 (Jenkins 환경변수로 주입)
    admin_user: str = "admin"
    admin_password: str = ""
    admin_session_minutes: int = 480

    # 로컬 SQLite DB 가 저장될 디렉터리 (컨테이너에서는 /app/data 볼륨)
    data_dir: str = "data"

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
