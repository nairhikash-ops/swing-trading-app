"""
train_hgb_regime_candidate.py

Trains a candidate HistGradientBoostingClassifier model on raw features
and outputs to /app/data/models/stock_opportunity_hgb_regime_v1/.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.ensemble import HistGradientBoostingClassifier


def encode_label(outcome: str) -> int:
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


def run_train_hgb_candidate(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    old_schema_path: str = "/app/data/models/stock_opportunity_ohlcv_regime_v1/feature_schema.json",
    output_dir: str = "/app/data/models/stock_opportunity_hgb_regime_v1",
    dataset_version: str = "stock_opportunity_hgb_regime_v1"
):
    if not os.path.exists(old_schema_path):
        raise FileNotFoundError(f"Production feature schema not found at {old_schema_path}")
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset CSV not found at {input_csv_path}")

    print(f"Loading feature schema from {old_schema_path}...")
    with open(old_schema_path, "r", encoding="utf-8") as f:
        feature_schema = json.load(f)
        
    if len(feature_schema) != 308:
        raise ValueError(f"Expected 308 features in schema, got {len(feature_schema)}")

    print(f"Loading dataset from {input_csv_path} memory-safely...")
    # Load only required columns and use float32 to reduce memory usage by 50%
    req_cols = ["symbol", "sample_date", "outcome"] + feature_schema
    dtype_dict = {col: np.float32 for col in feature_schema}
    dtype_dict.update({"symbol": "category"})
    
    df = pd.read_csv(input_csv_path, usecols=req_cols, dtype=dtype_dict)
    df["sample_date"] = pd.to_datetime(df["sample_date"])

    # Hard correction 1: Explicitly filter outcomes to WIN, LOSS, TIMEOUT only
    allowed_outcomes = {"WIN", "LOSS", "TIMEOUT"}
    df = df[df["outcome"].isin(allowed_outcomes)].copy()
    
    # Map label: WIN -> 1, LOSS/TIMEOUT -> 0
    df["target"] = df["outcome"].apply(encode_label)

    # Sort chronologically
    df = df.sort_values("sample_date").reset_index(drop=True)

    # Extract raw features and target
    X = df[feature_schema]
    y = df["target"]

    # Hard correction 2: HGB must use raw features only (no StandardScaler, no Pipeline)
    print(f"Training candidate model on {len(df)} rows (100% of dataset)...")
    clf = HistGradientBoostingClassifier(random_state=42)
    
    t0 = time.perf_counter()
    clf.fit(X, y)
    elapsed = time.perf_counter() - t0
    print(f"Training completed in {elapsed:.2f} seconds.")

    # Hard correction 3: Write only to the HGB directory
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "model.joblib")
    schema_path = os.path.join(output_dir, "feature_schema.json")
    metadata_path = os.path.join(output_dir, "model_metadata.json")

    print(f"Saving model to {model_path}...")
    joblib.dump(clf, model_path)

    print(f"Saving feature schema to {schema_path}...")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(feature_schema, f, indent=2)

    # Hard correction 6: Include candidate warning
    print(f"Saving metadata to {metadata_path}...")
    metadata = {
        "dataset_version": dataset_version,
        "source_csv": os.path.basename(input_csv_path),
        "row_count": len(df),
        "feature_count": len(feature_schema),
        "target_definition": "WIN=1, LOSS/TIMEOUT=0 (AMBIGUOUS/INSUFFICIENT excluded)",
        "model_type": "HistGradientBoostingClassifier (Raw Features)",
        "trained_on_full_dataset": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "warning": "candidate only, not deployed for live trading",
        "training_time_seconds": round(elapsed, 4)
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("Candidate HGB model training completed successfully.")


if __name__ == "__main__":
    run_train_hgb_candidate()
