import os
import json
import pytest
import pandas as pd
from app.scripts.export_ml_dataset_regime import generate_regime_dataset

def test_export_ml_dataset_regime_validation(tmp_path):
    input_path = tmp_path / "ml_dataset_ohlcv_v1.csv"
    output_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    meta_path = tmp_path / "ml_dataset_ohlcv_regime_v1.meta.json"
    
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
    
    # 2 rows
    data = {c: [0.0, 0.0] for c in metadata_cols + stock_feature_cols}
    data["symbol"] = ["AAPL", "MSFT"]
    data["sample_date"] = ["2020-01-01", "2020-01-01"]
    data["outcome"] = ["WIN", "LOSS"]
    
    df = pd.DataFrame(data)
    df.to_csv(input_path, index=False)
    
    # Expected rows is 2, skip_row_check=False 
    # But wait, default expected_rows is 440411, so we must override it for test or use skip_row_check
    generate_regime_dataset(
        input_path=str(input_path),
        output_path=str(output_path),
        skip_row_check=True
    )
    
    assert output_path.exists()
    assert meta_path.exists()
    
    out_df = pd.read_csv(output_path)
    assert len(out_df.columns) == 311
    
    with open(meta_path) as f:
        meta = json.load(f)
        
    assert meta["row_count"] == 2
    assert meta["total_column_count"] == 311
    assert meta["technical_feature_count"] == 300
    assert meta["regime_feature_count"] == 8
    assert meta["dataset_version"] == "stock_opportunity_ohlcv_regime_v1"
    
    # Test missing input fails
    with pytest.raises(FileNotFoundError):
        generate_regime_dataset(input_path=str(tmp_path / "missing.csv"))
        
    # Test column count fails
    bad_df = df.drop(columns=["c59_volume_rel"])
    bad_path = tmp_path / "bad.csv"
    bad_df.to_csv(bad_path, index=False)
    with pytest.raises(ValueError, match="Expected 300 technical feature columns"):
        generate_regime_dataset(input_path=str(bad_path), skip_row_check=True)
