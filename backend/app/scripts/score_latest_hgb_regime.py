"""
score_latest_hgb_regime.py

Scores candidates on the latest dataset date using the HGB candidate model,
and outputs to /app/data/exports/latest_hgb_regime_rankings.csv.
"""
from __future__ import annotations

import json
import os
import joblib
import pandas as pd
from datetime import datetime, timezone


def run_score_latest_hgb_regime(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    model_dir: str = "/app/data/models/stock_opportunity_hgb_regime_v1",
    output_dir: str = "/app/data/exports",
    dataset_version: str = "stock_opportunity_hgb_regime_v1"
):
    model_path = os.path.join(model_dir, "model.joblib")
    schema_path = os.path.join(model_dir, "feature_schema.json")

    if not os.path.exists(model_path) or not os.path.exists(schema_path):
        raise FileNotFoundError(f"Model artifacts missing in {model_dir}")
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset CSV not found at {input_csv_path}")

    print("Loading HGB candidate model and schema...")
    clf = joblib.load(model_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        feature_cols = json.load(f)

    print(f"Loading dataset from {input_csv_path}...")
    df = pd.read_csv(input_csv_path)

    latest_date = df["sample_date"].max()
    print(f"Filtering dataset for latest sample_date: {latest_date}...")
    latest_df = df[df["sample_date"] == latest_date].copy()
    row_count = len(latest_df)
    print(f"Found {row_count} symbols to score.")

    # Verify all features are present
    missing_cols = set(feature_cols) - set(latest_df.columns)
    if missing_cols:
        raise ValueError(f"Missing required feature columns for scoring: {missing_cols}")

    print("Scoring candidates using HGB Classifier...")
    X = latest_df[feature_cols]
    
    # Class 1 is WIN (WIN -> 1, LOSS/TIMEOUT -> 0)
    win_probabilities = clf.predict_proba(X)[:, 1]
    latest_df["win_probability"] = win_probabilities

    print("Ranking candidates...")
    latest_df = latest_df.sort_values("win_probability", ascending=False).reset_index(drop=True)
    latest_df["rank"] = latest_df.index + 1

    # Define exact output columns (excluding internal target/outcome)
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
    output_cols = ["rank", "symbol", "sample_date", "win_probability"] + regime_cols
    out_df = latest_df[output_cols]

    # Hard correction 4: Write only to latest_hgb_regime_rankings files
    os.makedirs(output_dir, exist_ok=True)
    csv_out_path = os.path.join(output_dir, "latest_hgb_regime_rankings.csv")
    meta_out_path = os.path.join(output_dir, "latest_hgb_regime_rankings.meta.json")

    print(f"Saving HGB rankings to {csv_out_path}...")
    out_df.to_csv(csv_out_path, index=False)

    # Hard correction 6: Include candidate warning
    print(f"Saving HGB metadata to {meta_out_path}...")
    metadata = {
        "model_version": dataset_version,
        "source_csv": os.path.basename(input_csv_path),
        "scored_sample_date": latest_date,
        "row_count": row_count,
        "ranking_count": len(out_df),
        "feature_schema_match": True,
        "is_live_today": False,
        "purpose": "offline candidate scoring verification",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "warning": "candidate only, not deployed for live trading"
    }
    with open(meta_out_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("Candidate HGB latest-date scoring completed successfully.")


if __name__ == "__main__":
    run_score_latest_hgb_regime()
