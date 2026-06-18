import sys
import argparse
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.store import TokenStore
from app.shadow_tracking import (
    DEFAULT_DB_PATH,
    init_db,
    get_observing_records,
    get_observing_records_by_model,
    get_model_version_counts,
    update_shadow_outcome,
)
from app.ml_samples import classify_outcome
from app.ml_foundation import (
    ML_FUTURE_WINDOW_SESSIONS,
    ML_TARGET_PERCENT,
    ML_STOP_PERCENT,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_instrument(conn, symbol: str) -> Optional[int]:
    """Resolve symbol to instrument_id. Returns None if not found."""
    row = conn.execute(
        '''
        SELECT id FROM instruments
        WHERE active = 1 AND exchange_id = 'NSE' AND segment = 'E'
          AND UPPER(underlying_symbol) = ?
        ORDER BY
          CASE WHEN instrument = 'EQUITY' THEN 0 ELSE 1 END,
          CASE WHEN series = 'EQ' THEN 0 ELSE 1 END,
          id
        LIMIT 1
        ''',
        (symbol.upper(),),
    ).fetchone()
    return int(row["id"]) if row else None


def _fetch_entry_close(conn, instrument_id: int, scored_sample_date: str) -> Optional[float]:
    """Fetch the closing price on the scored sample date. Returns None if not found."""
    row = conn.execute(
        "SELECT close FROM daily_candles WHERE instrument_id = ? AND trading_date = ?",
        (instrument_id, scored_sample_date),
    ).fetchone()
    return float(row["close"]) if row else None


def _fetch_future_window(conn, instrument_id: int, scored_sample_date: str) -> List[Dict]:
    """Fetch up to ML_FUTURE_WINDOW_SESSIONS candles after the scored date."""
    rows = conn.execute(
        '''
        SELECT trading_date, high, low FROM daily_candles
        WHERE instrument_id = ? AND trading_date > ?
        ORDER BY trading_date ASC
        LIMIT ?
        ''',
        (instrument_id, scored_sample_date, ML_FUTURE_WINDOW_SESSIONS),
    ).fetchall()
    return [dict(row) for row in rows]


def _classify_record(conn, record: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt to classify one shadow record. Returns a result dict with keys:
    status: 'ready' | 'skip_no_instrument' | 'skip_no_entry' | 'skip_insufficient'
    outcome_data: dict (only when status == 'ready')
    reason: str (only when status != 'ready')
    """
    symbol = record["symbol"]
    scored_sample_date = record["scored_sample_date"]

    instrument_id = _resolve_instrument(conn, symbol)
    if instrument_id is None:
        return {"status": "skip_no_instrument", "reason": f"no instrument for {symbol}"}

    entry_close = _fetch_entry_close(conn, instrument_id, scored_sample_date)
    if entry_close is None:
        return {"status": "skip_no_entry", "reason": f"no entry candle for {symbol} on {scored_sample_date}"}

    future_window = _fetch_future_window(conn, instrument_id, scored_sample_date)
    if len(future_window) < ML_FUTURE_WINDOW_SESSIONS:
        return {
            "status": "skip_insufficient",
            "reason": f"{symbol}: only {len(future_window)}/{ML_FUTURE_WINDOW_SESSIONS} future sessions",
        }

    target_price = entry_close * (1 + ML_TARGET_PERCENT / 100.0)
    stop_price = entry_close * (1 - ML_STOP_PERCENT / 100.0)
    outcome_data = classify_outcome(
        future_window=future_window,
        future_window_sessions=ML_FUTURE_WINDOW_SESSIONS,
        target_price=target_price,
        stop_price=stop_price,
    )

    if outcome_data["outcome"] == "INSUFFICIENT_FUTURE_DATA":
        return {
            "status": "skip_insufficient",
            "reason": f"{symbol}: classify_outcome returned INSUFFICIENT_FUTURE_DATA",
        }

    return {"status": "ready", "outcome_data": outcome_data}


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_resolver(
    shadow_db_path: str = DEFAULT_DB_PATH,
    model_version: Optional[str] = None,
    scored_sample_date: Optional[str] = None,
    execute: bool = False,
) -> None:
    """Resolve shadow outcomes for the specified model_version.

    Args:
        shadow_db_path:      Path to the shadow tracking SQLite database.
        model_version:       If provided, only OBSERVING rows for this model_version
                             are considered. If None, all OBSERVING rows are
                             considered (backward-compatible behaviour).
        scored_sample_date:  If provided, further filter to only OBSERVING rows
                             whose scored_sample_date matches this value (YYYY-MM-DD).
                             If None, all OBSERVING rows for the model_version are
                             processed (backward-compatible behaviour).
        execute:             If False (default), dry-run only — no DB writes.
                             If True, outcomes are written to the DB.

    V1.24 safety rules
    ------------------
    - Dry-run is the default.  Pass execute=True only after dry-run is verified.
    - model_version should always be supplied for V1.24+ runs so that HGB and
      LogisticRegression rows are never mixed.

    V1.25 safety rules
    ------------------
    - scored_sample_date is optional but recommended when multiple shadow dates
      exist for the same model_version.  It prevents accidentally resolving rows
      from a different date in the same run.
    """
    settings = get_settings()
    token_store = TokenStore(settings.database_path)

    init_db(shadow_db_path)

    # --- Print run header ---------------------------------------------------
    print("=" * 70)
    if execute:
        print("=== EXECUTE MODE: WRITING TO DB ===")
    else:
        print("=== RESOLVER DRY-RUN ===")
    print(f"Model version filter      : {model_version if model_version else '(none — all models)'}")
    if scored_sample_date:
        print(f"Scored sample date filter : {scored_sample_date}")
    else:
        print(f"Scored sample date filter : (none — all dates for model_version)")
    print("=" * 70)

    # --- Fetch OBSERVING records --------------------------------------------
    if model_version:
        records = get_observing_records_by_model(shadow_db_path, model_version)
    else:
        records = get_observing_records(shadow_db_path)

    # V1.25: optional scored_sample_date filter applied after fetch.
    if scored_sample_date:
        records = [r for r in records if r.get("scored_sample_date") == scored_sample_date]

    print(f"Total OBSERVING rows : {len(records)}")

    if not records:
        print("No OBSERVING records found — nothing to resolve.")
        if not execute:
            _print_dryrun_footer(shadow_db_path)
        return

    # --- Classify all records (read-only pass) ------------------------------
    import sqlite3 as _sqlite3

    results: List[Dict[str, Any]] = []
    with token_store._connect() as conn:
        conn.row_factory = _sqlite3.Row
        for record in records:
            result = _classify_record(conn, record)
            result["record"] = record
            results.append(result)

    # --- Tally outcomes -------------------------------------------------------
    ready = [r for r in results if r["status"] == "ready"]
    skip_no_instrument = [r for r in results if r["status"] == "skip_no_instrument"]
    skip_no_entry = [r for r in results if r["status"] == "skip_no_entry"]
    skip_insufficient = [r for r in results if r["status"] == "skip_insufficient"]

    expected_wins      = sum(1 for r in ready if r["outcome_data"]["outcome"] == "WIN")
    expected_losses    = sum(1 for r in ready if r["outcome_data"]["outcome"] == "LOSS")
    expected_timeouts  = sum(1 for r in ready if r["outcome_data"]["outcome"] == "TIMEOUT")
    expected_ambiguous = sum(1 for r in ready if r["outcome_data"]["outcome"] == "AMBIGUOUS")

    # --- DB counts BEFORE any write ----------------------------------------
    counts_before = get_model_version_counts(shadow_db_path)

    # --- Print dry-run summary ----------------------------------------------
    print(f"Rows with enough future candles    : {len(ready)}")
    print(f"Rows with insufficient future data : {len(skip_insufficient)}")
    print(f"Rows with no instrument            : {len(skip_no_instrument)}")
    print(f"Rows with no entry candle          : {len(skip_no_entry)}")
    print()
    print(f"Expected WIN count                 : {expected_wins}")
    print(f"Expected LOSS count                : {expected_losses}")
    print(f"Expected TIMEOUT count             : {expected_timeouts}")
    print(f"Expected AMBIGUOUS count           : {expected_ambiguous}")
    print(f"Expected rows that WOULD be updated: {len(ready)}")
    print()

    if len(skip_insufficient) > 0:
        print("--- Symbols with insufficient future data ---")
        for r in skip_insufficient:
            print(f"  {r['reason']}")
        print()

    # --- DB counts BEFORE ---------------------------------------------------
    print("--- DB COUNTS BEFORE ---")
    for mv, cnt in counts_before:
        print(f"  {mv} : {cnt} rows")
    print()

    # --- Write phase (only if execute=True) ---------------------------------
    if execute:
        print("--- WRITING OUTCOMES TO DB ---")
        resolved_count = 0
        skipped_count = 0
        with token_store._connect() as conn:
            conn.row_factory = _sqlite3.Row
            for r in results:
                if r["status"] != "ready":
                    sym = r["record"]["symbol"]
                    sdate = r["record"]["scored_sample_date"]
                    print(f"  Skipping {sym} on {sdate}: {r['reason']}")
                    skipped_count += 1
                    continue
                sym = r["record"]["symbol"]
                sdate = r["record"]["scored_sample_date"]
                outcome = r["outcome_data"]["outcome"]
                print(f"  Resolving {sym} on {sdate} -> {outcome}")
                update_shadow_outcome(shadow_db_path, r["record"]["id"], r["outcome_data"])
                resolved_count += 1

        counts_after = get_model_version_counts(shadow_db_path)
        print()
        print("--- DB COUNTS AFTER EXECUTION ---")
        for mv, cnt in counts_after:
            print(f"  {mv} : {cnt} rows")
        print()
        print("=== RESOLVER SUMMARY ===")
        print(f"Total OBSERVING scanned    : {len(records)}")
        print(f"Resolved                   : {resolved_count}")
        print(f"Skipped (still observing)  : {skipped_count}")
    else:
        # Dry-run: re-read counts to prove they are unchanged
        counts_after = get_model_version_counts(shadow_db_path)
        print("--- DB COUNTS AFTER DRY-RUN (must be identical to BEFORE) ---")
        for mv, cnt in counts_after:
            print(f"  {mv} : {cnt} rows")
        print()
        _print_dryrun_footer(shadow_db_path)


def _print_dryrun_footer(shadow_db_path: str) -> None:
    print("=" * 70)
    print("DRY RUN ONLY - NO DB WRITE")
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve outcomes for shadow tracking journal.\n\n"
            "Default behaviour is DRY-RUN — no DB writes are performed.\n"
            "Pass --execute to write resolved outcomes to the database.\n\n"
            "V1.24 safety rule: always supply --model-version to avoid mixing\n"
            "HGB and LogisticRegression rows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to shadow tracking DB",
    )
    parser.add_argument(
        "--model-version",
        type=str,
        default=None,
        help=(
            "Only resolve OBSERVING rows for this model_version. "
            "Recommended: always supply this flag to prevent cross-model mutation. "
            "Example: --model-version stock_opportunity_hgb_regime_v1"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help=(
            "Write resolved outcomes to the DB. "
            "Without this flag the script runs in DRY-RUN mode and makes no DB changes."
        ),
    )
    parser.add_argument(
        "--scored-sample-date",
        type=str,
        default=None,
        help=(
            "V1.25: Further filter OBSERVING rows to this scored_sample_date (YYYY-MM-DD). "
            "When supplied, only rows whose scored_sample_date matches are processed. "
            "Without this flag all OBSERVING rows for --model-version are processed. "
            "Example: --scored-sample-date 2026-05-21"
        ),
    )
    args = parser.parse_args()

    run_resolver(
        shadow_db_path=args.db_path,
        model_version=args.model_version,
        scored_sample_date=args.scored_sample_date,
        execute=args.execute,
    )


if __name__ == "__main__":
    main()
