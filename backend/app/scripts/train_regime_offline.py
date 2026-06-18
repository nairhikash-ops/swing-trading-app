import os
import json
import joblib
import subprocess
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

def encode_label(outcome: str) -> int:
    """Encode outcome to binary classification target."""
    if outcome == "WIN":
        return 1
    elif outcome in ("LOSS", "TIMEOUT"):
        return 0
    raise ValueError(f"Unknown outcome: {outcome}")

def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"

def run_train_regime_offline(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    output_dir: str = "/app/data/models/stock_opportunity_ohlcv_regime_v1",
    dataset_version: str = "stock_opportunity_ohlcv_regime_v1"
):
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset not found at {input_csv_path}")

    print(f"Loading full regime dataset from {input_csv_path}...")
    df = pd.read_csv(input_csv_path)

    # 1. Verify 3 metadata columns
    metadata_cols = ["symbol", "sample_date", "outcome"]
    
    # 2. Verify 300 technical features
    technical_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        technical_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
        
    # 3. Verify 8 regime features
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
    
    expected_cols = metadata_cols + technical_cols + regime_cols

    # 4. Verify 311 columns
    if len(df.columns) != 311:
        raise ValueError(f"Expected exactly 311 columns, got {len(df.columns)}")
        
    actual_cols = list(df.columns)
    if set(actual_cols) != set(expected_cols):
        missing = set(expected_cols) - set(actual_cols)
        extra = set(actual_cols) - set(expected_cols)
        raise ValueError(f"Column mismatch. Missing: {missing}, Extra: {extra}")

    # 5. Verify zero null/inf in feature columns
    feature_cols = technical_cols + regime_cols
    if df[feature_cols].isna().any().any():
        raise ValueError("NaN values found in feature columns.")
    if np.isinf(df[feature_cols].select_dtypes(include=np.number)).any().any():
        raise ValueError("Infinite values found in feature columns.")

    # Sort by sample_date to ensure deterministic order if needed, but not doing a split
    df = df.sort_values("sample_date").reset_index(drop=True)

    # 6. Binary target
    df["target"] = df["outcome"].apply(encode_label)

    # 7. Train on 100% of data
    X = df[feature_cols]
    y = df["target"]

    print(f"Training final offline model on {len(df)} rows (100% of dataset)...")
    lr = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(max_iter=1000, random_state=42))
    ])
    lr.fit(X, y)

    # 8. Save artifacts
    os.makedirs(output_dir, exist_ok=True)
    
    model_path = os.path.join(output_dir, "model.joblib")
    schema_path = os.path.join(output_dir, "feature_schema.json")
    metadata_path = os.path.join(output_dir, "model_metadata.json")
    
    print(f"Saving model to {model_path}...")
    joblib.dump(lr, model_path)
    
    print(f"Saving feature schema to {schema_path}...")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, indent=2)
        
    print(f"Saving metadata to {metadata_path}...")
    metadata = {
        "dataset_version": dataset_version,
        "source_csv": os.path.basename(input_csv_path),
        "row_count": len(df),
        "feature_count": 308,
        "technical_feature_count": 300,
        "regime_feature_count": 8,
        "target_definition": "WIN=1, LOSS/TIMEOUT=0",
        "model_type": "StandardScaler + LogisticRegression",
        "trained_on_full_dataset": True,
        "not_an_evaluation_split": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "validation_reference_reports": [
            "regime_baseline_report_v1.txt",
            "regime_walk_forward_report_v1.txt"
        ]
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    print("Offline regime model training completed successfully.")

if __name__ == "__main__":
    run_train_regime_offline()
