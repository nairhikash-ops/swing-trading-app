from __future__ import annotations

import argparse
import asyncio

from app.dhan_client import DhanClient
from app.instrument_master import parse_instrument_csv
from app.matsya.db import connect, run_schema
from app.matsya.ingest import instrument_record, sha256_text
from app.matsya.repository import finish_import_run, insert_raw_dhan_response, start_import_run, upsert_instrument
from app.matsya.settings import MatsyaSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Dhan instrument master into Matsya PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse only; do not write to PostgreSQL.")
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for smoke runs.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    settings = MatsyaSettings.from_env()
    client = DhanClient()
    csv_text = await client.fetch_instrument_master_csv(settings.instrument_master_url)
    _source_columns, total_rows, rows = parse_instrument_csv(csv_text, "NSE", "E")
    selected = rows[: args.limit] if args.limit else rows
    if args.dry_run:
        print(f"dry_run=true source_rows={total_rows} selected_rows={len(selected)}")
        return

    with connect(settings) as conn:
        run_schema(conn)
        run_id = start_import_run(
            conn,
            provider_code="dhan",
            import_type="instrument_master",
            source_name="dhan_instrument_master",
            source_url=settings.instrument_master_url,
            metadata={"source_rows": total_rows, "selected_rows": len(selected)},
        )
        insert_raw_dhan_response(
            conn,
            endpoint_name="instrument_master_csv",
            request_hash=sha256_text(settings.instrument_master_url),
            request_payload={"url": settings.instrument_master_url},
            response_hash=sha256_text(csv_text),
            response_text_ref="instrument_master_csv",
            run_id=run_id,
        )
        for raw_row in selected:
            upsert_instrument(conn, instrument_record(raw_row), run_id=run_id)
        finish_import_run(conn, run_id, status="completed", counts={"total_rows_seen": total_rows, "inserted_rows": len(selected)})
        conn.commit()
    print(f"instrument import completed run_id={run_id} rows={len(selected)}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
