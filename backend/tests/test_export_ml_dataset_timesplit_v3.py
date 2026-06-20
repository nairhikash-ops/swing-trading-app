import os
import json
import tempfile
from pathlib import Path
import pandas as pd
import pytest

from app.scripts.export_ml_dataset_timesplit_v3 import (
    export_timesplit_v3,
    DEFAULT_SOURCE_CSV,
    DEFAULT_OUTPUT_DIR
)

@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)

def build_synthetic_regime_v3_df(num_samples=10):
    # Ensure dates before and after 2025-07-09
    dates = ["2025-07-01", "2025-07-08", "2025-07-09", "2025-07-10", "2025-07-15"]
    outcomes = ["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN"]
    
    rows = []
    for i in range(num_samples):
        row = {
            "symbol": f"SYM{i}",
            "sample_date": dates[i % len(dates)],
            "outcome": outcomes[i % len(outcomes)]
        }
        
        # Exact anatomy feature names to satisfy test constraints
        anatomy_cols = [
            "c00_open_rel",
            "c00_body_to_range",
            "c00_close_position_in_range",
            "c59_signed_body_to_range",
        ]
        
        for col in anatomy_cols:
            row[col] = float(i)
            
        # 600 tech features total. Subtract anatomy cols we already added.
        remaining_tech = 600 - len(anatomy_cols)
        for c in range(remaining_tech):
            row[f"f_{c:03d}"] = float(c)
            
        regime_cols = [
            "market_median_20d_return",
            "stock_breakout_while_market_weak"
        ]
        
        for col in regime_cols:
            row[col] = float(i)
            
        remaining_regime = 8 - len(regime_cols)
        for r in range(remaining_regime):
            row[f"regime_{r:02d}"] = float(r)
            
        rows.append(row)
        
    return pd.DataFrame(rows)

def test_timesplit_v3_files_and_split_logic(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df(10)
    df_in.to_csv(in_path, index=False)
    
    meta = export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir)
    
    assert (out_dir / "train.csv").exists()
    assert (out_dir / "test.csv").exists()
    assert (out_dir / "split_meta.json").exists()
    
    df_train = pd.read_csv(out_dir / "train.csv")
    df_test = pd.read_csv(out_dir / "test.csv")
    
    cutoff = "2025-07-09"
    assert (df_train["sample_date"] < cutoff).all()
    assert (df_test["sample_date"] >= cutoff).all()
    
    train_dates = set(df_train["sample_date"])
    test_dates = set(df_test["sample_date"])
    assert len(train_dates.intersection(test_dates)) == 0

def test_timesplit_v3_shapes_and_columns(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df(10)
    df_in.to_csv(in_path, index=False)
    
    meta = export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir)
    
    df_train = pd.read_csv(out_dir / "train.csv")
    df_test = pd.read_csv(out_dir / "test.csv")
    
    assert len(df_train.columns) == 611
    assert len(df_test.columns) == 611
    assert meta["feature_count"] == 608
    assert list(df_train.columns) == list(df_in.columns)
    assert list(df_test.columns) == list(df_in.columns)
    
    # Validation constraint 4: exact v3 columns exist
    exact_cols = [
        "c00_open_rel",
        "c00_body_to_range",
        "c00_close_position_in_range",
        "c59_signed_body_to_range",
        "market_median_20d_return",
        "stock_breakout_while_market_weak"
    ]
    for col in exact_cols:
        assert col in df_train.columns
        assert col in df_test.columns

def test_timesplit_v3_metadata_and_outcomes(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df(10) # 10 samples, 2 AMBIGUOUS
    df_in.to_csv(in_path, index=False)
    
    meta = export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir)
    
    with open(out_dir / "split_meta.json", "r") as f:
        meta_json = json.load(f)
        
    assert "AMBIGUOUS" in meta_json["excluded_outcomes_observed"]
    assert meta_json["dataset_version"] == "timesplit_regime_v3"
    assert meta_json["total_eligible_row_count"] == 8

def test_timesplit_v3_rejects_unsafe_source_names(temp_workspace):
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df()
    
    for bad_name in ["ml_dataset_ohlcv_v3.csv", "ml_dataset_ohlcv_regime_v1.csv"]:
        bad_path = temp_workspace / bad_name
        df_in.to_csv(bad_path, index=False)
        with pytest.raises(ValueError, match="Unsafe old source name rejected"):
            export_timesplit_v3(source_csv_path=bad_path, output_dir=out_dir)

def test_timesplit_v3_rejects_unsafe_output_dirs(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    df_in = build_synthetic_regime_v3_df()
    df_in.to_csv(in_path, index=False)
    
    for bad_dir in ["timesplit_v2", "timesplit_regime_v2"]:
        bad_out = temp_workspace / bad_dir
        with pytest.raises(ValueError, match="Unsafe old output directory name rejected"):
            export_timesplit_v3(source_csv_path=in_path, output_dir=bad_out)

def test_timesplit_v3_wrong_feature_count_raises(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df()
    df_in.drop(columns=["f_000"], inplace=True) # drop one feature
    df_in.to_csv(in_path, index=False)
    
    # Needs to bypass total_cols check first if we dropped a column. Actually, the code checks total_cols == 611 first.
    # So if we drop a column, total_cols == 610. Let's just catch ValueError.
    with pytest.raises(ValueError, match="Total source column count must be exactly 611"):
        export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir)

def test_timesplit_v3_expected_rows_enforced(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df(10)
    df_in.to_csv(in_path, index=False)
    
    # 10 rows total, 8 eligible.
    # "expected_total_rows" means total eligible rows.
    # We pass 8 -> passes.
    export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir, expected_total_rows=8)
    
    # We pass 10 -> fails because expected is eligible count, not raw count.
    with pytest.raises(ValueError, match="Expected 10 total rows, found 8"):
        export_timesplit_v3(source_csv_path=in_path, output_dir=out_dir, expected_total_rows=10)

def test_timesplit_v3_expected_rows_optional(temp_workspace):
    in_path = temp_workspace / "ml_dataset_ohlcv_regime_v3.csv"
    out_dir = temp_workspace / "timesplit_regime_v3"
    
    df_in = build_synthetic_regime_v3_df(10)
    df_in.to_csv(in_path, index=False)
    
    # Should not raise
    export_timesplit_v3(
        source_csv_path=in_path, 
        output_dir=out_dir, 
        expected_total_rows=None, 
        expected_train_rows=None, 
        expected_test_rows=None
    )
