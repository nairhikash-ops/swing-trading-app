from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit


DEFAULT_TRUSTED_START_DATE = date(2026, 7, 6)


def _database_identity(url: str) -> tuple[str, int | None, str]:
    parsed = urlsplit(url)
    port = parsed.port or (5432 if parsed.scheme in {"postgresql", "postgres"} else None)
    return ((parsed.hostname or "").lower(), port, parsed.path.rstrip("/").lower())


@dataclass(frozen=True)
class IntradaySettings:
    database_url: str
    daily_database_url: str
    trusted_start_date: date | None = None
    symbol_universe: tuple[str, ...] = ()
    dhan_api_base_url: str = "https://api.dhan.co"
    market_open: str = "09:15"
    market_close: str = "15:30"

    def __post_init__(self) -> None:
        if _database_identity(self.database_url) == _database_identity(self.daily_database_url):
            raise ValueError("intraday and daily database URLs must identify different PostgreSQL databases")

    @classmethod
    def from_env(cls) -> "IntradaySettings":
        intraday_url = os.getenv("MATSYA_INTRADAY_DATABASE_URL", "").strip()
        daily_url = os.getenv("MATSYA_DAILY_DATABASE_URL", os.getenv("MATSYA_DATABASE_URL", "")).strip()
        if not intraday_url:
            raise RuntimeError("MATSYA_INTRADAY_DATABASE_URL is required")
        if not daily_url:
            raise RuntimeError("MATSYA_DAILY_DATABASE_URL is required")
        trusted = os.getenv("MATSYA_INTRADAY_TRUSTED_START_DATE", DEFAULT_TRUSTED_START_DATE.isoformat()).strip()
        symbols = tuple(
            sorted({item.strip().upper() for item in os.getenv("MATSYA_INTRADAY_SYMBOL_UNIVERSE", "").split(",") if item.strip()})
        )
        return cls(
            database_url=intraday_url,
            daily_database_url=daily_url,
            trusted_start_date=date.fromisoformat(trusted) if trusted else None,
            symbol_universe=symbols,
            dhan_api_base_url=os.getenv("MATSYA_DHAN_API_BASE_URL", "https://api.dhan.co"),
        )
