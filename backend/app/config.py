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
    dhan_instruments_detailed_url: str = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    dhan_instrument_exchange: str = "NSE"
    dhan_instrument_segment: str = "E"
    nifty_500_constituents_url: str = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    historical_lookback_calendar_days: int = Field(default=45, ge=1, le=365)
    extended_history_lookback_calendar_days: int = Field(default=365, ge=1, le=365)
    extended_history_upward_move_threshold_percent: float = Field(default=50.0, ge=0.1, le=100.0)
    dhan_historical_exchange_segment: str = "NSE_EQ"
    dhan_historical_instrument: str = "EQUITY"
    dhan_historical_rps: float = Field(default=2.0, ge=0.2, le=10.0)
    dhan_historical_max_retries: int = Field(default=3, ge=0, le=8)
    historical_finalized_after_hour_ist: int = Field(default=18, ge=0, le=23)
    data_quality_session_coverage_ratio: float = Field(default=0.5, ge=0.1, le=1.0)
    data_quality_block_missing_sessions: int = Field(default=3, ge=1, le=20)
    data_quality_extreme_move_percent: float = Field(default=20.0, ge=5.0, le=80.0)
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
