from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_SCHEMA = "matsya"


@dataclass(frozen=True)
class MatsyaSettings:
    database_url: str
    schema_name: str = DEFAULT_SCHEMA
    instrument_master_url: str = "https://images.dhan.co/api-data/api-scrip-master.csv"
    nifty_500_url: str = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

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
            instrument_master_url=os.getenv(
                "MATSYA_INSTRUMENT_MASTER_URL",
                "https://images.dhan.co/api-data/api-scrip-master.csv",
            ),
            nifty_500_url=os.getenv(
                "MATSYA_NIFTY_500_URL",
                "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
            ),
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
