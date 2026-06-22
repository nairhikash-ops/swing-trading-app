from __future__ import annotations

import argparse
import asyncio

from app.index_universe import NIFTY_500_INDEX_NAME, fetch_csv, parse_nifty_500_csv
from app.matsya.db import connect, run_schema
from app.matsya.ingest import sha256_text, universe_record
from app.matsya.repository import finish_import_run, start_import_run, upsert_universe_member
from app.matsya.settings import MatsyaSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import NSE universe membership into Matsya PostgreSQL.")
    parser.add_argument("--index-name", default=NIFTY_500_INDEX_NAME)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse only; do not write to PostgreSQL.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    settings = MatsyaSettings.from_env()
    csv_text = await fetch_csv(settings.nifty_500_url)
    _source_columns, total_rows, rows = parse_nifty_500_csv(csv_text)
    if args.dry_run:
        print(f"dry_run=true index={args.index_name} source_rows={total_rows} rows={len(rows)} csv_hash={sha256_text(csv_text)}")
        return

    with connect(settings) as conn:
        run_schema(conn)
        run_id = start_import_run(
            conn,
            provider_code="nse",
            import_type="universe_membership",
            source_name=args.index_name,
            source_url=settings.nifty_500_url,
            metadata={"csv_hash": sha256_text(csv_text)},
        )
        for raw_row in rows:
            upsert_universe_member(conn, universe_record(args.index_name, raw_row), run_id=run_id)
        finish_import_run(conn, run_id, status="completed", counts={"total_rows_seen": total_rows, "inserted_rows": len(rows)})
        conn.commit()
    print(f"universe import completed run_id={run_id} rows={len(rows)}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
