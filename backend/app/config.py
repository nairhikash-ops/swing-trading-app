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
    historical_lookback_calendar_days: int = Field(default=365, ge=1, le=365)
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
    data_maintenance_enabled: bool = True
    data_maintenance_check_interval_seconds: int = Field(default=3600, ge=300, le=24 * 3600)
    auto_purge_market_data: bool = False
    data_retention_calendar_days: int = Field(default=365, ge=1, le=3650)
    reversal_opportunity_automation_enabled: bool = False
    reversal_opportunity_min_score: float = Field(default=0.0, ge=0.0, le=100.0)
    reversal_opportunity_min_entry_quality_score: float = Field(default=55.0, ge=0.0, le=100.0)
    reversal_opportunity_include_watch_only: bool = False
    reversal_opportunity_limit: int = Field(default=500, ge=1, le=500)
    reversal_opportunity_outcome_refresh_limit: int = Field(default=1000, ge=1, le=5000)
    demo_initial_cash: float = Field(default=1_000_000.0, gt=0)
    demo_default_quantity: float = Field(default=1.0, gt=0)
    demo_default_risk_reward: float = Field(default=2.0, ge=1.0, le=10.0)
    demo_max_holding_sessions: int = Field(default=15, ge=1, le=120)
    demo_automation_enabled: bool = False
    demo_automation_max_algo_analyses_per_run: int = Field(default=5, ge=1, le=50)
    demo_automation_signal_review_window_sessions: int = Field(default=3, ge=1, le=10)
    demo_automation_retry_failed_algo_analyses: bool = False
    watchlist_entry_expiry_sessions: int = Field(default=8, ge=1, le=30)
    watchlist_breakout_min_close_strength: float = Field(default=0.60, ge=0.0, le=1.0)
    watchlist_max_entry_extension_percent: float = Field(default=5.0, ge=0.0, le=100.0)
    watchlist_max_risk_percent_at_entry: float = Field(default=8.0, ge=0.0, le=100.0)

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.backend_cors_origins.split(",") if item.strip()]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "dhan_auth.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
