from __future__ import annotations

from app.matsya.db import connect, health_check
from app.matsya.settings import MatsyaSettings


TABLES = [
    "raw_import_runs",
    "raw_import_errors",
    "raw_dhan_responses",
    "dhan_profile_snapshots",
    "dhan_token_renewal_runs",
    "instruments",
    "market_universe_members",
    "ohlcv_daily",
]


def main() -> None:
    settings = MatsyaSettings.from_env()
    with connect(settings) as conn:
        status = health_check(conn)
        print(f"database={status['database']} user={status['user']} url={settings.safe_database_url()}")
        for table in TABLES:
            row = conn.execute(f"SELECT COUNT(*) FROM matsya.{table}").fetchone()
            print(f"matsya.{table}: {row[0]}")


if __name__ == "__main__":
    main()

