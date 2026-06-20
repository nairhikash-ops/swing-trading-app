import os
import json
import tempfile
import pandas as pd
import numpy as np
import pytest

from app.scripts.export_ml_dataset_regime_v3 import (
    generate_regime_dataset_v3,
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_PATH,
)

@pytest.fixture
def temp_csv_paths():
    fd_in, in_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd_in)
    fd_out, out_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd_out)
    meta_path = out_path.replace(".csv", ".meta.json")
    
    yield in_path, out_path, meta_path
    
    if os.path.exists(in_path):
        os.remove(in_path)
    if os.path.exists(out_path):
        os.remove(out_path)
    if os.path.exists(meta_path):
        os.remove(meta_path)

def build_synthetic_v3_df(num_samples=4):
    # Minimum 2 dates, multiple symbols
    dates = ["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-02"]
    symbols = ["AAPL", "MSFT", "AAPL", "MSFT"]
    
    rows = []
    for i in range(num_samples):
        row = {
            "symbol": symbols[i % len(symbols)],
            "sample_date": dates[i % len(dates)],
            "outcome": "WIN"
        }
        
        # 60 candles x 10 features = 600 technical features
        for c in range(60):
            prefix = f"c{c:02d}_"
            row[f"{prefix}open_rel"] = 1.0
            row[f"{prefix}high_rel"] = 1.1
            row[f"{prefix}low_rel"] = 0.9
            row[f"{prefix}close_rel"] = 1.05
            row[f"{prefix}volume_rel"] = 1.0
            row[f"{prefix}body_to_range"] = 0.25
            row[f"{prefix}upper_wick_to_range"] = 0.25
            row[f"{prefix}lower_wick_to_range"] = 0.50
            row[f"{prefix}close_position_in_range"] = 0.75
            row[f"{prefix}signed_body_to_range"] = 0.25
        rows.append(row)
        
    return pd.DataFrame(rows)

def test_regime_v3_output_shape(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    meta = generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    
    df_out = pd.read_csv(out_path)
    
    assert len(df_out.columns) == 611
    assert meta["total_feature_count"] == 608
    assert meta["technical_feature_count"] == 600
    assert meta["regime_feature_count"] == 8

def test_metadata_columns_stay_first(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    df_out = pd.read_csv(out_path)
    
    assert list(df_out.columns[:3]) == ["symbol", "sample_date", "outcome"]

def test_regime_columns_last_and_names(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    df_out = pd.read_csv(out_path)
    
    expected_regime = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    
    assert list(df_out.columns[-8:]) == expected_regime

def test_candle_anatomy_preserved(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    df_out = pd.read_csv(out_path)
    
    assert "c00_body_to_range" in df_out.columns
    assert "c00_close_position_in_range" in df_out.columns
    assert "c59_signed_body_to_range" in df_out.columns

def test_regime_calculations_finite(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    df_out = pd.read_csv(out_path)
    
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
    
    assert not df_out[regime_cols].isna().any().any()
    assert not np.isinf(df_out[regime_cols]).any().any()

def test_duplicate_symbol_sample_date_raises(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    # Duplicate the first row
    df_in = pd.concat([df_in, df_in.iloc[[0]]], ignore_index=True)
    df_in.to_csv(in_path, index=False)
    
    with pytest.raises(ValueError, match="Found 1 duplicate samples"):
        generate_regime_dataset_v3(input_path=in_path, output_path=out_path)

def test_missing_input_raises(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    os.remove(in_path) # Delete it so it's missing
    
    with pytest.raises(FileNotFoundError, match="Input V3 CSV missing"):
        generate_regime_dataset_v3(input_path=in_path, output_path=out_path)

def test_wrong_technical_feature_count_raises(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    # Drop one feature
    df_in.drop(columns=["c00_body_to_range"], inplace=True)
    df_in.to_csv(in_path, index=False)
    
    with pytest.raises(ValueError, match="Expected 603 input columns"):
        generate_regime_dataset_v3(input_path=in_path, output_path=out_path)

def test_metadata_json_written_to_temp_path(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in.to_csv(in_path, index=False)
    
    generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
    
    assert os.path.exists(meta_path)
    with open(meta_path, "r") as f:
        meta = json.load(f)
        
    assert meta["technical_feature_count"] == 600
    assert meta["regime_feature_count"] == 8
    assert meta["total_feature_count"] == 608
    assert meta["total_column_count"] == 611
    assert meta["dataset_version"] == "stock_opportunity_ohlcv_regime_v3"
    assert meta["parent_dataset_version"] == "stock_opportunity_ohlcv_v3"

def test_default_output_path_constant():
    assert DEFAULT_OUTPUT_PATH == "/app/data/exports/ml_dataset_ohlcv_regime_v3.csv"
    assert DEFAULT_INPUT_PATH == "/app/data/exports/ml_dataset_ohlcv_v3.csv"

def test_existing_regime_columns_raises(temp_csv_paths):
    in_path, out_path, meta_path = temp_csv_paths
    df_in = build_synthetic_v3_df()
    df_in["market_median_20d_return"] = 0.05
    df_in.to_csv(in_path, index=False)
    
    with pytest.raises(ValueError, match="Input CSV already contains regime columns"):
        generate_regime_dataset_v3(input_path=in_path, output_path=out_path)
