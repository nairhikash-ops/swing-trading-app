"""
track_shadow_hgb_shortlist.py

Tracks HGB candidate picks in the shadow tracking database under
the candidate model version stock_opportunity_hgb_regime_v1.
"""
from __future__ import annotations

import json
import os
import pandas as pd
from datetime import datetime, timezone
from app.shadow_tracking import init_db, insert_shadow_records, DEFAULT_DB_PATH


def run_track_shadow_hgb_shortlist(
    exports_dir: str = "/app/data/exports",
    db_path: str = DEFAULT_DB_PATH,
    allow_live_today: bool = False
):
    csv_path = os.path.join(exports_dir, "latest_hgb_regime_rankings.csv")
    meta_path = os.path.join(exports_dir, "latest_hgb_regime_rankings.meta.json")

    if not os.path.exists(csv_path) or not os.path.exists(meta_path):
        raise FileNotFoundError("HGB rankings or HGB rankings metadata not found.")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    if meta.get("is_live_today", True) and not allow_live_today:
        raise ValueError("is_live_today is true, but allow_live_today is False. Failing closed.")

    df = pd.read_csv(csv_path)
    total_rows = len(df)

    # Calculate cutoff counts
    top_1_count = max(1, int(round(0.01 * total_rows)))
    top_5_count = max(1, int(round(0.05 * total_rows)))

    # Filter to Top 5% HGB shortlist
    df_tracked = df[df["rank"] <= top_5_count].copy()

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
    for _, row in df_tracked.iterrows():
        rank = row["rank"]
        bucket = "PRIMARY_TOP_1" if rank <= top_1_count else "WATCH_TOP_5"

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

    # Initialize shadow DB if not exists
    init_db(db_path)

    # Insert HGB records safely (database unique constraint prevents duplicate key conflicts)
    inserted_count = insert_shadow_records(db_path, records)
    skipped_count = len(records) - inserted_count

    print(f"HGB Scored sample date: {scored_sample_date}")
    print(f"HGB Ranking rows: {total_rows}")
    print(f"HGB Top 5% tracked: {top_5_count}")
    print(f"HGB Primary Top 1%: {top_1_count}")
    print(f"HGB records inserted: {inserted_count}")
    print(f"HGB duplicate records skipped: {skipped_count}")
    print("Status: OBSERVING")


if __name__ == "__main__":
    run_track_shadow_hgb_shortlist()
