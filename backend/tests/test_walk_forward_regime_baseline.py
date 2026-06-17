import os
import pandas as pd
import pytest

from app.scripts.walk_forward_regime_baseline import run_regime_walk_forward_experiment

@pytest.fixture
def mock_regime_dataset(tmp_path):
    csv_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    
    dates = [
        # Training instances 2020
        "2020-01-01", "2020-06-01", "2020-12-01", "2021-05-01",
        # Embargo for Period 1 starts 2021-11-27
        "2021-11-01", # inside train window
        "2021-12-01", # inside embargo! (should not be in train_df)
        "2021-12-15", # inside embargo! (should not be in train_df)
        
        # Validation Period 1: 2022-01-01 to 2022-04-01
        "2022-01-05", "2022-02-05", "2022-03-05", "2022-03-10",
        
        # Embargo for Period 2 starts 2022-02-25
        "2022-03-01", # inside embargo for Period 2 (also in Val 1)
        
        # Validation Period 2: 2022-04-01 to 2022-07-01
        "2022-04-05", "2022-05-05", "2022-06-05", "2022-06-15",
        
        # Partial Period 3 (ends prematurely)
        "2022-08-01"
    ]
    
    # Ensure all classes are present in training
    outcomes = [
        "WIN", "LOSS", "TIMEOUT", "WIN",
        "LOSS",
        "WIN",
        "TIMEOUT",
        
        "WIN", "LOSS", "LOSS", "WIN",
        
        "LOSS",
        
        "WIN", "LOSS", "LOSS", "TIMEOUT",
        
        "WIN"
    ]
    
    # 300 tech + 8 regime cols
    tech_cols = {}
    for i in range(60):
        prefix = f"c{i:02d}_"
        tech_cols[f"{prefix}open_rel"] = [0.01] * len(dates)
        tech_cols[f"{prefix}high_rel"] = [0.02] * len(dates)
        tech_cols[f"{prefix}low_rel"] = [-0.01] * len(dates)
        tech_cols[f"{prefix}close_rel"] = [0.0] * len(dates)
        tech_cols[f"{prefix}volume_rel"] = [1.0] * len(dates)
        
    regime_cols = {
        "market_median_20d_return": [0.05] * len(dates),
        "market_breakout_rate": [0.1] * len(dates),
        "market_breakdown_rate": [0.05] * len(dates),
        "market_breadth_delta": [0.05] * len(dates),
        "market_cross_sectional_volatility": [0.02] * len(dates),
        "stock_20d_return_minus_market_median": [0.01] * len(dates),
        "stock_is_stronger_than_market": [1.0] * len(dates),
        "stock_breakout_while_market_weak": [0.0] * len(dates)
    }
    
    data = {
        "symbol": ["AAPL"] * len(dates),
        "sample_date": dates,
        "outcome": outcomes,
    }
    data.update(tech_cols)
    data.update(regime_cols)
    
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    return str(csv_path)

def test_walk_forward_regime_baseline(mock_regime_dataset, tmp_path):
    report_path = tmp_path / "report.txt"
    run_regime_walk_forward_experiment(input_csv_path=mock_regime_dataset, report_path=str(report_path))
    
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    
    # Check partial period logic
    assert "Skipping final partial period starting 2022-07-01" in content
    
    # Check period counts
    assert "Total completed periods:       2" in content
    
    # Verify training ends logic and embargoes.
    assert "Training end (post-embargo): 2021-11-27" in content
    assert "Training end (post-embargo): 2022-02-25" in content

    # Check metrics format
    assert "Top 01% | Rows:" in content
    assert "Average Top 1% expectancy:" in content
    assert "Average Top 5% expectancy:" in content
    assert "Worst Top 1% period damage:" in content
