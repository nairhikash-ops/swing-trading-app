from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = ""
    data_dir: Path = Path("./data")
    backend_cors_origins: str = "http://localhost:5173"

    dhan_api_base_url: str = "https://api.dhan.co"
    dhan_renew_before_minutes: int = Field(default=180, ge=5, le=23 * 60)
    dhan_status_stale_minutes: int = Field(default=15, ge=1, le=24 * 60)
    dhan_renew_check_interval_seconds: int = Field(default=900, ge=60, le=24 * 3600)

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.backend_cors_origins.split(",") if item.strip()]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "dhan_auth.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
