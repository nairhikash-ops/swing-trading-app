import argparse
import sys
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.index_universe import IndexUniverseService, IndexUniverseStore
from app.ml_foundation import ML_LABEL_NAME, ML_MODEL_NAME
from app.ml_samples import MLSampleService, MLSampleStore
from app.store import TokenStore


def run_batch(
    ml_service: MLSampleService,
    universe_service: IndexUniverseService,
    ml_store: MLSampleStore,
    dry_run: bool,
    limit: int | None,
    symbols_str: str | None,
) -> dict[str, Any]:
    # 1. Determine candidate symbols
    candidate_symbols = []
    if symbols_str:
        raw_symbols = symbols_str.split(",")
        candidate_symbols = [s.strip().upper() for s in raw_symbols if s.strip()]
    else:
        constituents = universe_service.nifty_500_constituents()
        candidate_symbols = [c["symbol"].upper() for c in constituents]

    # 2. Get already generated symbols
    already_generated = set()
    with ml_store._connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT symbol
            FROM ml_samples
            WHERE model_name = ? AND label_name = ?
            """,
            (ML_MODEL_NAME, ML_LABEL_NAME)
        ).fetchall()
        already_generated = {row["symbol"].upper() for row in rows}

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "execute": not dry_run,
        "requested_symbol_count": len(candidate_symbols),
        "candidate_symbol_count": len(candidate_symbols),
        "already_generated_count": 0,
        "attempted_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "total_created": 0,
        "total_updated": 0,
        "total_would_create": 0,
        "total_would_update": 0,
        "errors": []
    }

    for symbol in candidate_symbols:
        if symbol in already_generated:
            summary["already_generated_count"] += 1
            summary["skipped_count"] += 1
            continue

        if limit is not None and summary["attempted_count"] >= limit:
            break

        summary["attempted_count"] += 1
        try:
            result = ml_service.generate_one(symbol=symbol, dry_run=dry_run)
            summary["succeeded_count"] += 1
            if dry_run:
                summary["total_would_create"] += result["samples_created"]
                summary["total_would_update"] += result["samples_updated"]
            else:
                summary["total_created"] += result["samples_created"]
                summary["total_updated"] += result["samples_updated"]
        except Exception as e:
            summary["failed_count"] += 1
            summary["errors"].append({"symbol": symbol, "message": str(e)})

    # Print summary
    print("=== BATCH GENERATION SUMMARY ===")
    for key, value in summary.items():
        if key != "errors":
            print(f"{key}: {value}")

    if summary["errors"]:
        print("\n=== ERRORS ===")
        for err in summary["errors"]:
            print(f"{err['symbol']}: {err['message']}")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ML samples in batch.")
    parser.add_argument("--execute", action="store_true", help="Execute real database writes.")
    parser.add_argument("--limit", type=int, help="Limit number of symbols to process (required with --execute).")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols to process.")

    args = parser.parse_args()

    execute = args.execute
    limit = args.limit
    symbols_str = args.symbols

    if execute and limit is None:
        print("ERROR: --limit is required when --execute is used.")
        sys.exit(1)

    dry_run = not execute

    settings = get_settings()
    token_store = TokenStore(settings.database_path)
    ml_store = MLSampleStore(token_store)
    ml_service = MLSampleService(settings=settings, store=ml_store)
    universe_store = IndexUniverseStore(token_store)
    universe_service = IndexUniverseService(settings=settings, store=universe_store)

    run_batch(
        ml_service=ml_service,
        universe_service=universe_service,
        ml_store=ml_store,
        dry_run=dry_run,
        limit=limit,
        symbols_str=symbols_str,
    )


if __name__ == "__main__":
    main()
