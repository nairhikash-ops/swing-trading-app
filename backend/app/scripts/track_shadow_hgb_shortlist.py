"""
track_shadow_hgb_shortlist.py

Tracks HGB candidate picks in the shadow tracking database under
the candidate model version stock_opportunity_hgb_regime_v1.

V1.25 additions
---------------
- --ranked-csv PATH  : explicit path to ranked CSV (must be paired with --meta-json).
- --meta-json PATH   : explicit path to meta JSON  (must be paired with --ranked-csv).
  When both are supplied the script reads those files instead of the latest defaults.
  Supplying only one raises ValueError immediately.
"""
from __future__ import annotations
import argparse
import math
import sqlite3

import json
import os
import pandas as pd
from datetime import datetime, timezone
from app.shadow_tracking import init_db, insert_shadow_records, DEFAULT_DB_PATH


def run_track_shadow_hgb_shortlist(
    exports_dir: str = "/app/data/exports",
    db_path: str = DEFAULT_DB_PATH,
    allow_live_today: bool = False,
    execute: bool = False,
    ranked_csv: str | None = None,
    meta_json: str | None = None,
):
    # V1.25: explicit path support — both must be supplied together or both omitted.
    _ranked_csv_supplied = ranked_csv is not None
    _meta_json_supplied  = meta_json is not None
    if _ranked_csv_supplied != _meta_json_supplied:
        raise ValueError(
            "--ranked-csv and --meta-json must be supplied together. "
            "Supplying only one is not allowed. "
            f"(ranked_csv={ranked_csv!r}, meta_json={meta_json!r})"
        )

    if ranked_csv is not None and meta_json is not None:
        # Explicit paths supplied — use them directly.
        csv_path  = ranked_csv
        meta_path = meta_json
    else:
        # Default behaviour: read latest files.
        csv_path  = os.path.join(exports_dir, "latest_hgb_regime_rankings.csv")
        meta_path = os.path.join(exports_dir, "latest_hgb_regime_rankings.meta.json")

    if not os.path.exists(csv_path) or not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"HGB rankings or HGB rankings metadata not found. "
            f"(csv={csv_path!r}, meta={meta_path!r})"
        )

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    if meta.get("is_live_today", True) and not allow_live_today:
        raise ValueError("is_live_today is true, but allow_live_today is False. Failing closed.")

    df = pd.read_csv(csv_path)
    total_rows = len(df)

    # Calculate cutoff counts using ceil as per specification
    top_1_count = max(1, math.ceil(0.01 * total_rows))
    top_5_count = max(1, math.ceil(0.05 * total_rows))

    # Ensure dataframe is sorted by rank ascending (1-indexed)
    df = df.sort_values(by="rank", ascending=True).reset_index(drop=True)
    # Take top 5% rows based on position
    df_tracked = df.head(top_5_count).copy()

    # Hard correction 5: Set model_version to stock_opportunity_hgb_regime_v1
    model_version = meta.get("model_version", "stock_opportunity_hgb_regime_v1")
    model_commit = os.environ.get("APP_GIT_COMMIT", "unknown")
    date_scored = datetime.now(timezone.utc).isoformat()
    scored_sample_date = meta.get("scored_sample_date", "unknown")

    regime_cols = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]

    records = []
    for idx, row in df_tracked.iterrows():
        # idx is zero‑based; position = idx + 1
        position = idx + 1
        rank = row["rank"]
        bucket = "PRIMARY_TOP_1" if position <= top_1_count else "WATCH_TOP_5"

        regime_dict = {col: row[col] for col in regime_cols if col in row}
        regime_json = json.dumps(regime_dict)

        records.append({
            "date_scored": date_scored,
            "scored_sample_date": scored_sample_date,
            "model_version": model_version,
            "model_commit": model_commit,
            "rank": rank,
            "bucket": bucket,
            "symbol": row["symbol"],
            "win_probability": row["win_probability"],
            "regime_context_json": regime_json,
            "tracking_status": "OBSERVING"
        })

    if execute:
        # Initialize shadow DB if not exists
        init_db(db_path)
        # Count existing rows for this model_version before insertion
        conn = sqlite3.connect(db_path)
        before = conn.execute("SELECT COUNT(1) FROM shadow_tracking WHERE model_version = ?", (model_version,)).fetchone()[0]
        conn.close()

        # Insert HGB records safely (database unique constraint prevents duplicate key conflicts)
        inserted_count = insert_shadow_records(db_path, records)
        skipped_count = len(records) - inserted_count

        # Count after insertion
        conn = sqlite3.connect(db_path)
        after = conn.execute("SELECT COUNT(1) FROM shadow_tracking WHERE model_version = ?", (model_version,)).fetchone()[0]
        conn.close()
    else:
        inserted_count = 0
        skipped_count = len(records)
        before = "N/A"
        after = "N/A"

    print(f"HGB Scored sample date: {scored_sample_date}")
    print(f"HGB Ranking rows: {total_rows}")
    print(f"HGB Top 5% tracked: {top_5_count}")
    print(f"HGB Primary Top 1%: {top_1_count}")
    # Also report WATCH_TOP_5 count for clarity
    watch_top_5_count = top_5_count - top_1_count
    print(f"HGB WATCH_TOP_5 rows: {watch_top_5_count}")
    if execute:
        print(f"Existing records before insertion for model_version {model_version}: {before}")
        print(f"HGB records inserted: {inserted_count}")
        print(f"HGB duplicate records skipped: {skipped_count}")
        print(f"Existing records after insertion: {after}")
    else:
        print(f"[DRY-RUN] HGB records that would be inserted: {len(records)}")
        print(f"[DRY-RUN] Duplicate records that would be skipped: {skipped_count}")
    print("Status: OBSERVING")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Track HGB shadow shortlist.\n\n"
            "V1.25: Supply --ranked-csv and --meta-json together to use date-specific\n"
            "archive files instead of the latest defaults. Supplying only one fails loudly."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform actual DB insertion (default is dry-run)",
    )
    parser.add_argument(
        "--ranked-csv",
        type=str,
        default=None,
        help=(
            "Path to a specific ranked CSV file (e.g. hgb_regime_rankings_2026-05-21.csv). "
            "Must be paired with --meta-json. Overrides the latest-file default."
        ),
    )
    parser.add_argument(
        "--meta-json",
        type=str,
        default=None,
        help=(
            "Path to a specific meta JSON file (e.g. hgb_regime_rankings_2026-05-21.meta.json). "
            "Must be paired with --ranked-csv. Overrides the latest-file default."
        ),
    )
    args = parser.parse_args()
    run_track_shadow_hgb_shortlist(
        execute=args.execute,
        ranked_csv=args.ranked_csv,
        meta_json=args.meta_json,
    )
