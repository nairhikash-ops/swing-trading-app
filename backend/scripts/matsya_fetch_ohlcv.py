from __future__ import annotations

import argparse
import asyncio
import os

from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.ingest import candles_from_dhan_payload, sha256_payload
from app.matsya.repository import (
    finish_import_run,
    insert_raw_dhan_response,
    record_import_error,
    start_import_run,
    upsert_ohlcv_daily,
)
from app.matsya.settings import MatsyaSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch daily Dhan OHLCV into Matsya PostgreSQL.")
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--exchange-segment", default="NSE_EQ")
    parser.add_argument("--instrument", default="EQUITY")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--access-token-env", default="MATSYA_MANUAL_DHAN_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only; do not write to PostgreSQL.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    access_token = os.getenv(args.access_token_env)
    if not access_token:
        raise RuntimeError(f"{args.access_token_env} is not set")

    payload = await DhanClient().historical_daily(
        access_token=access_token,
        security_id=args.security_id,
        exchange_segment=args.exchange_segment,
        instrument=args.instrument,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    candles = candles_from_dhan_payload(
        payload,
        security_id=args.security_id,
        exchange_segment=args.exchange_segment,
        instrument=args.instrument,
    )
    if args.dry_run:
        print(f"dry_run=true security_id={args.security_id} candles={len(candles)}")
        return

    settings = MatsyaSettings.from_env()
    with connect(settings) as conn:
        run_schema(conn)
        run_id = start_import_run(
            conn,
            provider_code="dhan",
            import_type="ohlcv_daily",
            source_name=args.security_id,
            metadata={
                "security_id": args.security_id,
                "exchange_segment": args.exchange_segment,
                "instrument": args.instrument,
                "from_date": args.from_date,
                "to_date": args.to_date,
            },
        )
        try:
            insert_raw_dhan_response(
                conn,
                endpoint_name="historical_daily",
                request_hash=sha256_payload(
                    {
                        "security_id": args.security_id,
                        "exchange_segment": args.exchange_segment,
                        "instrument": args.instrument,
                        "from_date": args.from_date,
                        "to_date": args.to_date,
                    }
                ),
                request_payload={
                    "security_id": args.security_id,
                    "exchange_segment": args.exchange_segment,
                    "instrument": args.instrument,
                    "from_date": args.from_date,
                    "to_date": args.to_date,
                },
                response_hash=sha256_payload(payload),
                response_json=payload,
                run_id=run_id,
            )
            for candle in candles:
                upsert_ohlcv_daily(conn, candle, run_id=run_id)
            finish_import_run(conn, run_id, status="completed", counts={"total_rows_seen": len(candles), "inserted_rows": len(candles)})
        except Exception as exc:
            record_import_error(conn, provider_code="dhan", error_type=type(exc).__name__, error_message=str(exc), run_id=run_id)
            finish_import_run(conn, run_id, status="failed")
            raise
        finally:
            conn.commit()
    print(f"ohlcv fetch completed run_id={run_id} candles={len(candles)}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
