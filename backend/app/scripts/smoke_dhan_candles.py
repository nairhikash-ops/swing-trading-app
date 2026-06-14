import argparse
import asyncio
import json
from datetime import date, timedelta
from typing import Any

from app.config import Settings
from app.crypto import TokenCrypto
from app.dhan_client import DhanClient
from app.historical_data import (
    HistoricalDataStore,
    HistoricalWindow,
    clamp_window_to_dhan_floor,
    parse_historical_payload,
)
from app.store import TokenStore
from app.token_service import TokenService


async def main() -> None:
    args = parse_args()
    settings = Settings()
    token_store = TokenStore(settings.database_path)
    token_service = TokenService(settings, token_store)
    historical_store = HistoricalDataStore(token_store)

    token_status = token_service.status()
    requested_window = HistoricalWindow(
        from_date=date.fromisoformat(args.from_date),
        to_date_exclusive=date.fromisoformat(args.to_date) + timedelta(days=1),
    )
    clamped_window = clamp_window_to_dhan_floor(settings, requested_window)
    report: dict[str, Any] = {
        "token_state": token_status.state,
        "data_plan": token_status.data_plan,
        "data_api_active": token_status.data_api_active,
        "historical_fetch_allowed": token_status.historical_fetch_allowed,
        "historical_block_reason": token_status.historical_block_reason,
        "symbol": args.symbol.upper(),
        "requested_from_date": requested_window.from_date.isoformat(),
        "requested_to_date": args.to_date,
        "clamped_from_date": clamped_window.from_date.isoformat(),
        "clamped_to_date": (clamped_window.to_date_exclusive - timedelta(days=1)).isoformat(),
    }

    instrument = find_instrument(token_store, args.symbol)
    if instrument is None:
        report.update({"status": "blocked", "error": "No active Dhan NSE equity instrument found for symbol."})
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    report.update(
        {
            "instrument_id": instrument["id"],
            "security_id": instrument["security_id"],
            "isin": instrument["isin"],
        }
    )
    if not token_status.historical_fetch_allowed:
        report.update({"status": "blocked"})
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    token = token_store.get()
    if token is None:
        report.update({"status": "blocked", "error": "No Dhan token stored."})
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    access_token = TokenCrypto(settings.app_secret_key).decrypt(token.encrypted_access_token)
    before_dates = stored_dates(token_store, int(instrument["id"]), clamped_window)
    payload = await DhanClient(settings.dhan_api_base_url).historical_daily(
        access_token=access_token,
        security_id=str(instrument["security_id"]),
        exchange_segment="NSE_EQ",
        instrument="EQUITY",
        from_date=clamped_window.from_date.isoformat(),
        to_date=(clamped_window.to_date_exclusive - timedelta(days=1)).isoformat(),
    )
    candles = parse_historical_payload(payload)
    item = {
        "instrument_id": instrument["id"],
        "security_id": instrument["security_id"],
        "symbol": instrument["symbol"],
        "archive_status": "initial_capture" if not before_dates else "incremental_update",
    }
    if candles:
        historical_store.upsert_candles(item, candles, "NSE_EQ", "EQUITY")
    source_floor_reason = historical_store.record_fetch_outcome(
        item,
        candles,
        clamped_window.from_date,
        clamped_window.to_date_exclusive - timedelta(days=1),
    )
    after_dates = stored_dates(token_store, int(instrument["id"]), clamped_window)
    archive = historical_store.archive_metadata(int(instrument["id"])) or {}
    stored_range = historical_store.stored_candle_range(int(instrument["id"]))
    returned_dates = {str(candle["trading_date"]) for candle in candles}

    report.update(
        {
            "status": "ok",
            "candles_returned": len(candles),
            "candles_inserted": len(returned_dates - before_dates),
            "candles_updated": len(returned_dates & before_dates),
            "stored_rows_in_range_before": len(before_dates),
            "stored_rows_in_range_after": len(after_dates),
            "first_stored_candle_date": stored_range["first_stored_candle_date"],
            "latest_stored_candle_date": stored_range["latest_stored_candle_date"],
            "duplicate_count": duplicate_count(token_store, int(instrument["id"])),
            "invalid_ohlcv_count": invalid_ohlcv_count(token_store, int(instrument["id"])),
            "source_floor_reason": source_floor_reason,
            "source_floor_reached": bool(archive.get("source_floor_reached")),
            "complete_available_history": bool(archive.get("complete_available_history")),
        }
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny Dhan candle smoke test. Does not run scheduler or pruning.")
    parser.add_argument("--symbol", default="RELIANCE", help="NSE equity symbol to smoke-test.")
    parser.add_argument("--from", dest="from_date", required=True, help="Requested start date, YYYY-MM-DD.")
    parser.add_argument("--to", dest="to_date", required=True, help="Requested end date, YYYY-MM-DD inclusive.")
    return parser.parse_args()


def find_instrument(token_store: TokenStore, symbol: str) -> dict[str, Any] | None:
    with token_store._connect() as conn:
        row = conn.execute(
            """
            SELECT id, security_id, isin, underlying_symbol AS symbol
            FROM instruments
            WHERE active = 1
              AND exchange_id = 'NSE'
              AND segment = 'E'
              AND instrument = 'EQUITY'
              AND UPPER(underlying_symbol) = UPPER(?)
            ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    return dict(row) if row else None


def stored_dates(token_store: TokenStore, instrument_id: int, window: HistoricalWindow) -> set[str]:
    with token_store._connect() as conn:
        rows = conn.execute(
            """
            SELECT trading_date
            FROM daily_candles
            WHERE instrument_id = ? AND trading_date >= ? AND trading_date < ?
            """,
            (instrument_id, window.from_date.isoformat(), window.to_date_exclusive.isoformat()),
        ).fetchall()
    return {row["trading_date"] for row in rows}


def duplicate_count(token_store: TokenStore, instrument_id: int) -> int:
    with token_store._connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS duplicate_count
            FROM (
                SELECT instrument_id, trading_date, COUNT(*) AS row_count
                FROM daily_candles
                WHERE instrument_id = ?
                GROUP BY instrument_id, trading_date
                HAVING row_count > 1
            )
            """,
            (instrument_id,),
        ).fetchone()
    return int(row["duplicate_count"] or 0)


def invalid_ohlcv_count(token_store: TokenStore, instrument_id: int) -> int:
    with token_store._connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS invalid_count
            FROM daily_candles
            WHERE instrument_id = ?
              AND (
                open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                OR high < open OR high < close OR high < low
                OR low > open OR low > close OR low > high
                OR volume < 0
              )
            """,
            (instrument_id,),
        ).fetchone()
    return int(row["invalid_count"] or 0)


if __name__ == "__main__":
    asyncio.run(main())
