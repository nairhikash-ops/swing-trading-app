import os
import json
import pytest
import numpy as np
import pandas as pd

from app.scripts.train_regime_offline import run_train_regime_offline
from app.scripts.score_latest_regime import run_score_latest_regime

def create_dummy_regime_csv(path: str, num_rows: int = 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    metadata_cols = ["symbol", "sample_date", "outcome"]
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
    
    all_cols = metadata_cols + technical_cols + regime_cols
    df = pd.DataFrame(columns=all_cols)
    
    symbols = [f"SYM{i}" for i in range(10)]
    dates = ["2023-01-01", "2023-01-02", "2023-01-03"]
    outcomes = ["WIN", "LOSS", "TIMEOUT"]
    
    data = []
    for i in range(num_rows):
        row = {
            "symbol": symbols[i % len(symbols)],
            "sample_date": dates[i % len(dates)],
            "outcome": outcomes[i % len(outcomes)]
        }
        for c in technical_cols:
            row[c] = np.random.normal(0, 0.05)
        for c in regime_cols:
            row[c] = np.random.normal(0, 0.01)
        data.append(row)
        
    df = pd.DataFrame(data)
    df.to_csv(path, index=False)
    return df

@pytest.fixture
def dummy_pipeline_env(tmp_path):
    data_dir = tmp_path / "data"
    exports_dir = data_dir / "exports"
    models_dir = data_dir / "models"
    
    csv_path = str(exports_dir / "ml_dataset_ohlcv_regime_v1.csv")
    create_dummy_regime_csv(csv_path, num_rows=50)
    
    return {
        "csv_path": csv_path,
        "models_dir": str(models_dir),
        "exports_dir": str(exports_dir)
    }

def test_offline_regime_pipeline_end_to_end(dummy_pipeline_env):
    csv_path = dummy_pipeline_env["csv_path"]
    models_dir = dummy_pipeline_env["models_dir"]
    exports_dir = dummy_pipeline_env["exports_dir"]
    
    model_dir = os.path.join(models_dir, "stock_opportunity_ohlcv_regime_v1")
    
    # 1. Run training
    run_train_regime_offline(
        input_csv_path=csv_path,
        output_dir=model_dir
    )
    
    # Verify artifacts
    assert os.path.exists(os.path.join(model_dir, "model.joblib"))
    assert os.path.exists(os.path.join(model_dir, "feature_schema.json"))
    assert os.path.exists(os.path.join(model_dir, "model_metadata.json"))
    
    with open(os.path.join(model_dir, "model_metadata.json"), "r") as f:
        meta = json.load(f)
        assert meta["feature_count"] == 308
        assert meta["trained_on_full_dataset"] is True
        
    with open(os.path.join(model_dir, "feature_schema.json"), "r") as f:
        schema = json.load(f)
        assert len(schema) == 308
        
    # 2. Run scoring
    run_score_latest_regime(
        input_csv_path=csv_path,
        model_dir=model_dir,
        output_dir=exports_dir
    )
    
    # Verify scoring outputs
    rankings_csv = os.path.join(exports_dir, "latest_regime_rankings.csv")
    rankings_meta = os.path.join(exports_dir, "latest_regime_rankings.meta.json")
    
    assert os.path.exists(rankings_csv)
    assert os.path.exists(rankings_meta)
    
    with open(rankings_meta, "r") as f:
        rmeta = json.load(f)
        assert rmeta["is_live_today"] is False
        assert rmeta["feature_schema_match"] is True
        
    df_out = pd.read_csv(rankings_csv)
    
    # Verify exact columns requested
    expected_cols = [
        "rank", "symbol", "sample_date", "win_probability",
        "market_median_20d_return", "market_breakout_rate",
        "market_breakdown_rate", "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    assert list(df_out.columns) == expected_cols
    
    # Verify all output rows are from the latest date (2023-01-03)
    assert (df_out["sample_date"] == "2023-01-03").all()
    
    # Verify sorted by rank
    assert list(df_out["rank"]) == list(range(1, len(df_out) + 1))
    
    # Verify sorted by probability descending
    probs = df_out["win_probability"].tolist()
    assert probs == sorted(probs, reverse=True)
