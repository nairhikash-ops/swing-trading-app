import os
import json
import pytest
import numpy as np
import pandas as pd
from app.scripts.export_ml_dataset_regime import generate_regime_dataset

def create_mock_df(rows=2, dupes=False, nan_regime=False):
    metadata_cols = ["symbol", "sample_date", "outcome"]
    stock_feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        stock_feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
    
    data = {c: [0.0] * rows for c in metadata_cols + stock_feature_cols}
    symbols = [f"SYM{i}" for i in range(rows)]
    if dupes and rows >= 2:
        symbols[1] = symbols[0]
        
    data["symbol"] = symbols
    data["sample_date"] = ["2020-01-01"] * rows
    data["outcome"] = ["WIN"] * rows
    
    df = pd.DataFrame(data)
    
    if nan_regime:
        df.loc[0, "c59_close_rel"] = np.nan
        
    return df

def test_export_ml_dataset_regime_validation(tmp_path):
    input_path = tmp_path / "ml_dataset_ohlcv_v1.csv"
    output_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    meta_path = tmp_path / "ml_dataset_ohlcv_regime_v1.meta.json"
    
    # 1. row_count == minimum passes
    df_2 = create_mock_df(rows=2)
    df_2.to_csv(input_path, index=False)
    
    generate_regime_dataset(
        input_path=str(input_path),
        output_path=str(output_path),
        minimum_expected_rows=2,
        skip_row_check=False
    )
    assert output_path.exists()
    
    out_df = pd.read_csv(output_path)
    assert len(out_df.columns) == 311
    
    with open(meta_path) as f:
        meta = json.load(f)
        
    assert meta["row_count"] == 2
    assert meta["total_column_count"] == 311
    assert meta["technical_feature_count"] == 300
    assert meta["regime_feature_count"] == 8
    assert meta["dataset_version"] == "stock_opportunity_ohlcv_regime_v1"
    
    # 2. row_count > minimum passes
    df_3 = create_mock_df(rows=3)
    df_3.to_csv(input_path, index=False)
    generate_regime_dataset(
        input_path=str(input_path),
        output_path=str(output_path),
        minimum_expected_rows=2,
        skip_row_check=False
    )
    
    # 3. row_count < minimum fails
    with pytest.raises(ValueError, match="less than minimum expected"):
        generate_regime_dataset(
            input_path=str(input_path),
            output_path=str(output_path),
            minimum_expected_rows=4,
            skip_row_check=False
        )

    # 4. Duplicate symbol + sample_date fails even when skip_row_check=True
    df_dupes = create_mock_df(rows=2, dupes=True)
    df_dupes.to_csv(input_path, index=False)
    with pytest.raises(ValueError, match="duplicate samples in dataset"):
        generate_regime_dataset(
            input_path=str(input_path),
            output_path=str(output_path),
            minimum_expected_rows=2,
            skip_row_check=True
        )

    # 5. NaN regime feature fails
    df_nan = create_mock_df(rows=2, nan_regime=True)
    df_nan.to_csv(input_path, index=False)
    with pytest.raises(ValueError, match="NaN values found in regime columns"):
        generate_regime_dataset(
            input_path=str(input_path),
            output_path=str(output_path),
            minimum_expected_rows=2,
            skip_row_check=True
        )

    # 6. Test missing input fails
    with pytest.raises(FileNotFoundError):
        generate_regime_dataset(input_path=str(tmp_path / "missing.csv"))
        
    # 7. Test column count fails
    bad_df = df_2.drop(columns=["c59_volume_rel"])
    bad_path = tmp_path / "bad.csv"
    bad_df.to_csv(bad_path, index=False)
    with pytest.raises(ValueError, match="Expected 300 technical feature columns"):
        generate_regime_dataset(input_path=str(bad_path), skip_row_check=True)
