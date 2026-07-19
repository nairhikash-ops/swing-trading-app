from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_SCHEMA = "matsya"


@dataclass(frozen=True)
class MatsyaSettings:
    database_url: str
    schema_name: str = DEFAULT_SCHEMA
    app_secret_key: str = ""
    cors_origins_raw: str = "http://localhost:5190,http://127.0.0.1:5190"
    dhan_api_base_url: str = "https://api.dhan.co"
    instrument_master_url: str = "https://images.dhan.co/api-data/api-scrip-master.csv"
    nifty_500_url: str = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    renew_before_minutes: int = 180
    ohlcv_worker_enabled: bool = True
    ohlcv_loop: bool = False
    ohlcv_check_interval_seconds: int = 3600
    ohlcv_incremental_overlap_sessions: int = 2
    ohlcv_validation_trading_days: int = 60
    ohlcv_primary_run_hour_ist: int = 5
    ohlcv_primary_run_minute_ist: int = 30
    ohlcv_repair_run_hour_ist: int = 6
    ohlcv_repair_run_minute_ist: int = 30
    ohlcv_final_check_hour_ist: int = 7
    ohlcv_final_check_minute_ist: int = 30
    ohlcv_ready_deadline_hour_ist: int = 8
    ohlcv_ready_deadline_minute_ist: int = 0
    historical_lookback_calendar_days: int = 1825
    dhan_historical_daily_supported_years: int = 5
    dhan_historical_rps: float = 2.0
    dhan_historical_max_retries: int = 3
    dhan_latest_candle_retry_hours: int = 3
    dhan_historical_exchange_segment: str = "NSE_EQ"
    dhan_historical_instrument: str = "EQUITY"
    ohlcv_universe_name: str = "NIFTY_500"
    historical_finalized_after_hour_ist: int = 18
    market_code: str = "NSE"
    intraday_paper_enabled: bool = False
    dhan_live_feed_url: str = "wss://api-feed.dhan.co"
    intraday_feed_stale_seconds: int = 45
    intraday_subscription_refresh_seconds: int = 5
    intraday_reconnect_max_seconds: int = 60
    intraday_reconciliation_hour_ist: int = 15
    intraday_reconciliation_minute_ist: int = 35

    @classmethod
    def from_env(cls) -> "MatsyaSettings":
        database_url = os.getenv("MATSYA_DATABASE_URL")
        if not database_url:
            host = os.getenv("MATSYA_POSTGRES_HOST", "127.0.0.1")
            port = os.getenv("MATSYA_POSTGRES_PORT", "5432")
            database = os.getenv("POSTGRES_DB", os.getenv("MATSYA_POSTGRES_DB", "matsya"))
            user = os.getenv("POSTGRES_USER", os.getenv("MATSYA_POSTGRES_USER", "matsya_user"))
            password = os.getenv("POSTGRES_PASSWORD", os.getenv("MATSYA_POSTGRES_PASSWORD", ""))
            if not password:
                raise RuntimeError("Matsya PostgreSQL password is missing from the environment")
            database_url = (
                f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}"
            )
        return cls(
            database_url=database_url,
            schema_name=os.getenv("MATSYA_SCHEMA", DEFAULT_SCHEMA),
            app_secret_key=os.getenv("MATSYA_APP_SECRET_KEY", os.getenv("APP_SECRET_KEY", "")),
            cors_origins_raw=os.getenv(
                "MATSYA_CORS_ORIGINS",
                "http://localhost:5190,http://127.0.0.1:5190",
            ),
            dhan_api_base_url=os.getenv("MATSYA_DHAN_API_BASE_URL", "https://api.dhan.co"),
            instrument_master_url=os.getenv(
                "MATSYA_INSTRUMENT_MASTER_URL",
                "https://images.dhan.co/api-data/api-scrip-master.csv",
            ),
            nifty_500_url=os.getenv(
                "MATSYA_NIFTY_500_URL",
                "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
            ),
            renew_before_minutes=int(os.getenv("MATSYA_RENEW_BEFORE_MINUTES", "180")),
            ohlcv_worker_enabled=os.getenv("MATSYA_OHLCV_WORKER_ENABLED", "true").lower() == "true",
            ohlcv_loop=os.getenv("MATSYA_OHLCV_LOOP", "false").lower() == "true",
            ohlcv_check_interval_seconds=int(os.getenv("MATSYA_OHLCV_CHECK_INTERVAL_SECONDS", "3600")),
            ohlcv_incremental_overlap_sessions=int(os.getenv("MATSYA_OHLCV_INCREMENTAL_OVERLAP_SESSIONS", "2")),
            ohlcv_validation_trading_days=int(os.getenv("MATSYA_OHLCV_VALIDATION_TRADING_DAYS", "60")),
            ohlcv_primary_run_hour_ist=int(os.getenv("MATSYA_OHLCV_PRIMARY_RUN_HOUR_IST", "5")),
            ohlcv_primary_run_minute_ist=int(os.getenv("MATSYA_OHLCV_PRIMARY_RUN_MINUTE_IST", "30")),
            ohlcv_repair_run_hour_ist=int(os.getenv("MATSYA_OHLCV_REPAIR_RUN_HOUR_IST", "6")),
            ohlcv_repair_run_minute_ist=int(os.getenv("MATSYA_OHLCV_REPAIR_RUN_MINUTE_IST", "30")),
            ohlcv_final_check_hour_ist=int(os.getenv("MATSYA_OHLCV_FINAL_CHECK_HOUR_IST", "7")),
            ohlcv_final_check_minute_ist=int(os.getenv("MATSYA_OHLCV_FINAL_CHECK_MINUTE_IST", "30")),
            ohlcv_ready_deadline_hour_ist=int(os.getenv("MATSYA_OHLCV_READY_DEADLINE_HOUR_IST", "8")),
            ohlcv_ready_deadline_minute_ist=int(os.getenv("MATSYA_OHLCV_READY_DEADLINE_MINUTE_IST", "0")),
            historical_lookback_calendar_days=int(os.getenv("MATSYA_HISTORICAL_LOOKBACK_CALENDAR_DAYS", "1825")),
            dhan_historical_daily_supported_years=int(os.getenv("MATSYA_DHAN_HISTORICAL_DAILY_SUPPORTED_YEARS", "5")),
            dhan_historical_rps=float(os.getenv("MATSYA_DHAN_HISTORICAL_RPS", "2")),
            dhan_historical_max_retries=int(os.getenv("MATSYA_DHAN_HISTORICAL_MAX_RETRIES", "3")),
            dhan_latest_candle_retry_hours=int(os.getenv("MATSYA_DHAN_LATEST_CANDLE_RETRY_HOURS", "3")),
            dhan_historical_exchange_segment=os.getenv("MATSYA_DHAN_HISTORICAL_EXCHANGE_SEGMENT", "NSE_EQ"),
            dhan_historical_instrument=os.getenv("MATSYA_DHAN_HISTORICAL_INSTRUMENT", "EQUITY"),
            ohlcv_universe_name=os.getenv("MATSYA_OHLCV_UNIVERSE_NAME", "NIFTY_500"),
            historical_finalized_after_hour_ist=int(os.getenv("MATSYA_HISTORICAL_FINALIZED_AFTER_HOUR_IST", "18")),
            market_code=os.getenv("MATSYA_MARKET_CODE", "NSE"),
            intraday_paper_enabled=os.getenv("MATSYA_INTRADAY_PAPER_ENABLED", "false").lower() == "true",
            dhan_live_feed_url=os.getenv("MATSYA_DHAN_LIVE_FEED_URL", "wss://api-feed.dhan.co"),
            intraday_feed_stale_seconds=int(os.getenv("MATSYA_INTRADAY_FEED_STALE_SECONDS", "45")),
            intraday_subscription_refresh_seconds=int(
                os.getenv("MATSYA_INTRADAY_SUBSCRIPTION_REFRESH_SECONDS", "5")
            ),
            intraday_reconnect_max_seconds=int(os.getenv("MATSYA_INTRADAY_RECONNECT_MAX_SECONDS", "60")),
            intraday_reconciliation_hour_ist=int(os.getenv("MATSYA_INTRADAY_RECONCILIATION_HOUR_IST", "15")),
            intraday_reconciliation_minute_ist=int(os.getenv("MATSYA_INTRADAY_RECONCILIATION_MINUTE_IST", "35")),
        )

    def safe_database_url(self) -> str:
        parsed = urlsplit(self.database_url)
        if not parsed.password:
            return self.database_url
        username = parsed.username or ""
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{username}:***@{hostname}{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]
