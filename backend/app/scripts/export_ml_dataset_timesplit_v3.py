import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_SOURCE_CSV = Path("/app/data/exports/ml_dataset_ohlcv_regime_v3.csv")
DEFAULT_OUTPUT_DIR = Path("/app/data/exports/timesplit_regime_v3")

ELIGIBLE_OUTCOMES = ["WIN", "LOSS", "TIMEOUT"]
EXCLUDED_OUTCOMES = ["AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA", "null", "unknown"]

def export_timesplit_v3(
    source_csv_path=DEFAULT_SOURCE_CSV,
    output_dir=DEFAULT_OUTPUT_DIR,
    cutoff_date="2025-07-09",
    expected_total_rows: int | None = None,
    expected_train_rows: int | None = None,
    expected_test_rows: int | None = None,
    expected_feature_count: int = 608
):
    source_csv_path = Path(source_csv_path)
    output_dir = Path(output_dir)
    
    if not source_csv_path.exists():
        raise FileNotFoundError(f"Source file missing: {source_csv_path}")
        
    source_name = source_csv_path.name
    if source_name != "ml_dataset_ohlcv_regime_v3.csv":
        if source_name in ["ml_dataset_ohlcv_v3.csv", "ml_dataset_ohlcv_regime_v1.csv", "ml_dataset_ohlcv_regime_v2.csv"]:
            raise ValueError(f"Unsafe old source name rejected: {source_name}")
        raise ValueError(f"Source file name must be exactly ml_dataset_ohlcv_regime_v3.csv, got {source_name}")

    output_dir_name = output_dir.name
    if output_dir_name != "timesplit_regime_v3":
        if output_dir_name in ["timesplit_v2", "timesplit_regime_v2"]:
            raise ValueError(f"Unsafe old output directory name rejected: {output_dir_name}")
        raise ValueError(f"Output directory basename must be exactly timesplit_regime_v3, got {output_dir_name}")

    df = pd.read_csv(source_csv_path)
    
    metadata_cols = ["symbol", "sample_date", "outcome"]
    if list(df.columns[:3]) != metadata_cols:
        raise ValueError(f"First three columns must be {metadata_cols}")
        
    total_cols = len(df.columns)
    if total_cols != 611:
        raise ValueError(f"Total source column count must be exactly 611, got {total_cols}")
        
    feature_cols = list(df.columns[3:])
    if len(feature_cols) != expected_feature_count:
        raise ValueError(f"Feature count must be exactly {expected_feature_count}, got {len(feature_cols)}")
        
    eligible_mask = df["outcome"].isin(ELIGIBLE_OUTCOMES)
    excluded_outcomes_observed = sorted(str(value) for value in df.loc[~eligible_mask, "outcome"].dropna().unique())
    
    df_eligible = df[eligible_mask].copy()
    
    # Sort by sample_date
    df_eligible.sort_values(by="sample_date", inplace=True)
    
    # Split
    train_mask = df_eligible["sample_date"] < cutoff_date
    test_mask = df_eligible["sample_date"] >= cutoff_date
    
    df_train = df_eligible[train_mask].copy()
    df_test = df_eligible[test_mask].copy()
    
    # Validations
    if expected_total_rows is not None and len(df_eligible) != expected_total_rows:
        raise ValueError(f"Expected {expected_total_rows} total rows, found {len(df_eligible)}")
    if expected_train_rows is not None and len(df_train) != expected_train_rows:
        raise ValueError(f"Expected {expected_train_rows} train rows, found {len(df_train)}")
    if expected_test_rows is not None and len(df_test) != expected_test_rows:
        raise ValueError(f"Expected {expected_test_rows} test rows, found {len(df_test)}")
        
    if list(df_train.columns) != list(df_test.columns):
        raise ValueError("Train and test columns do not match exactly.")
        
    train_dates = set(df_train["sample_date"].unique())
    test_dates = set(df_test["sample_date"].unique())
    overlap = train_dates.intersection(test_dates)
    if len(overlap) > 0:
        raise ValueError(f"Sample date overlap found between train and test: {len(overlap)} dates")
        
    max_train_date = df_train["sample_date"].max() if len(df_train) > 0 else None
    min_test_date = df_test["sample_date"].min() if len(df_test) > 0 else None
    
    if max_train_date is not None and max_train_date >= cutoff_date:
        raise ValueError(f"Max train date {max_train_date} >= cutoff {cutoff_date}")
    if min_test_date is not None and min_test_date < cutoff_date:
        raise ValueError(f"Min test date {min_test_date} < cutoff {cutoff_date}")
        
    os.makedirs(output_dir, exist_ok=True)
    
    train_path = output_dir / "train.csv"
    test_path = output_dir / "test.csv"
    meta_path = output_dir / "split_meta.json"
    
    train_tmp = train_path.with_suffix(".csv.tmp")
    test_tmp = test_path.with_suffix(".csv.tmp")
    meta_tmp = meta_path.with_suffix(".json.tmp")
    
    try:
        df_train.to_csv(train_tmp, index=False)
        df_test.to_csv(test_tmp, index=False)
        os.replace(train_tmp, train_path)
        os.replace(test_tmp, test_path)
    except Exception as e:
        for t in [train_tmp, test_tmp]:
            if t.exists():
                t.unlink()
        raise e
        
    feature_schema_match = True
    leakage_safe = (
        len(overlap) == 0
        and (max_train_date is None or max_train_date < cutoff_date)
        and (min_test_date is None or min_test_date >= cutoff_date)
        and list(df_train.columns) == list(df_test.columns)
        and feature_schema_match
    )
        
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_csv_path),
        "output_dir": str(output_dir),
        "cutoff_date": cutoff_date,
        "train_rule": f"sample_date < {cutoff_date}",
        "test_rule": f"sample_date >= {cutoff_date}",
        "eligible_outcomes": ELIGIBLE_OUTCOMES,
        "excluded_outcomes": EXCLUDED_OUTCOMES,
        "excluded_outcomes_observed": excluded_outcomes_observed,
        "train_row_count": len(df_train),
        "test_row_count": len(df_test),
        "total_eligible_row_count": len(df_eligible),
        "train_unique_sample_dates": len(train_dates),
        "test_unique_sample_dates": len(test_dates),
        "min_train_sample_date": max_train_date if len(df_train) == 0 else df_train["sample_date"].min(),
        "max_train_sample_date": max_train_date,
        "min_test_sample_date": min_test_date,
        "max_test_sample_date": min_test_date if len(df_test) == 0 else df_test["sample_date"].max(),
        "cutoff_date_row_count": len(df[df["sample_date"] == cutoff_date]),
        "train_outcome_counts": df_train["outcome"].value_counts().to_dict(),
        "test_outcome_counts": df_test["outcome"].value_counts().to_dict(),
        "sample_date_overlap_count": len(overlap),
        "source_column_count": total_cols,
        "output_column_count": total_cols,
        "feature_count": len(feature_cols),
        "expected_feature_count": expected_feature_count,
        "feature_schema_match": feature_schema_match,
        "missing_features": [],
        "extra_features": [],
        "leakage_safe": leakage_safe,
        "dataset_version": "timesplit_regime_v3",
        "source_dataset_version": "stock_opportunity_ohlcv_regime_v3",
        "notes": ""
    }
    
    try:
        with open(meta_tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(meta_tmp, meta_path)
    except Exception as e:
        if meta_tmp.exists():
            meta_tmp.unlink()
        raise e
        
    return meta

if __name__ == "__main__":
    export_timesplit_v3()
