from __future__ import annotations

from app.matsya.db import connect, health_check
from app.matsya.ohlcv_service import MatsyaOHLCVStore
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
    validation = MatsyaOHLCVStore(settings).validation_report(
        settings.ohlcv_universe_name,
        settings.ohlcv_validation_trading_days,
        settings.historical_finalized_after_hour_ist,
        settings.market_code,
    )
    print(
        "matsya.ohlcv_validation: "
        f"universe={validation['universe_name']} "
        f"days={validation['validation_trading_days']} "
        f"expected_latest={validation['expected_latest_candle_date']} "
        f"total_rows={validation['total_rows']} "
        f"symbols={validation['symbols_with_candles']} "
        f"duplicates={validation['duplicate_count']} "
        f"zero_candle_symbols={validation['zero_candle_symbols']} "
        f"stale_symbols={validation['stale_symbols']} "
        f"missing_recent_symbol_dates={validation['missing_recent_symbol_dates']} "
        f"null_ohlcv={validation['null_ohlcv_count']} "
        f"bad_ohlc={validation['bad_ohlc_count']} "
        f"negative_volume={validation['negative_volume_count']}"
    )


if __name__ == "__main__":
    main()
