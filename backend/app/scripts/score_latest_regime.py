import os
import json
import joblib
import pandas as pd
from datetime import datetime, timezone

def run_score_latest_regime(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    model_dir: str = "/app/data/models/stock_opportunity_ohlcv_regime_v1",
    output_dir: str = "/app/data/exports",
    dataset_version: str = "stock_opportunity_ohlcv_regime_v1"
):
    model_path = os.path.join(model_dir, "model.joblib")
    schema_path = os.path.join(model_dir, "feature_schema.json")
    
    if not os.path.exists(model_path) or not os.path.exists(schema_path):
        raise FileNotFoundError(f"Model artifacts missing in {model_dir}")
        
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset not found at {input_csv_path}")

    print("Loading model and schema...")
    lr = joblib.load(model_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        feature_cols = json.load(f)
        
    print(f"Loading regime dataset from {input_csv_path}...")
    df = pd.read_csv(input_csv_path)

    latest_date = df["sample_date"].max()
    print(f"Filtering dataset for latest sample_date: {latest_date}...")
    
    latest_df = df[df["sample_date"] == latest_date].copy()
    row_count = len(latest_df)
    print(f"Found {row_count} symbols to score.")
    
    # Ensure all required features are present
    missing_cols = set(feature_cols) - set(latest_df.columns)
    if missing_cols:
        raise ValueError(f"Missing required feature columns for scoring: {missing_cols}")

    print("Scoring candidates...")
    X = latest_df[feature_cols]
    
    # We assume binary classifier where index 1 is WIN (based on encode_label returning 1 for WIN)
    win_probabilities = lr.predict_proba(X)[:, 1]
    
    latest_df["win_probability"] = win_probabilities
    
    print("Ranking candidates...")
    latest_df = latest_df.sort_values("win_probability", ascending=False).reset_index(drop=True)
    latest_df["rank"] = latest_df.index + 1
    
    # Define exact output columns
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
    
    os.makedirs(output_dir, exist_ok=True)
    csv_out_path = os.path.join(output_dir, "latest_regime_rankings.csv")
    meta_out_path = os.path.join(output_dir, "latest_regime_rankings.meta.json")
    
    print(f"Saving rankings to {csv_out_path}...")
    out_df.to_csv(csv_out_path, index=False)
    
    print(f"Saving metadata to {meta_out_path}...")
    metadata = {
        "model_version": dataset_version,
        "source_csv": os.path.basename(input_csv_path),
        "scored_sample_date": latest_date,
        "row_count": row_count,
        "ranking_count": len(out_df),
        "feature_schema_match": True,
        "is_live_today": False,
        "purpose": "offline scoring pipeline verification",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    with open(meta_out_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    print("Offline latest-dataset-date scoring completed successfully.")

if __name__ == "__main__":
    run_score_latest_regime()
