import os
import pandas as pd
import pytest

from app.scripts.walk_forward_failure_analysis import run_failure_analysis_experiment

@pytest.fixture
def mock_dataset_failure(tmp_path):
    csv_path = tmp_path / "ml_dataset_ohlcv_v1.csv"
    
    dates = [
        # Training instances 2020
        "2020-01-01", "2020-06-01", "2020-12-01", "2021-05-01",
        # Validation Period 1: 2022-01-01 to 2022-04-01
        "2022-01-05", "2022-02-05", "2022-03-05", "2022-03-10", "2022-03-15",
        "2022-04-10" # Force end_date past the 3-month window
    ]
    
    outcomes = [
        "WIN", "LOSS", "TIMEOUT", "WIN",
        "LOSS", "LOSS", "LOSS", "WIN", "LOSS",
        "WIN"
    ]
    
    symbols = [
        "AAPL", "MSFT", "AAPL", "TSLA",
        # Concentrated losses in validation to trigger a negative period
        "TSLA", "TSLA", "AAPL", "AAPL", "TSLA",
        "AAPL"
    ]
    
    df = pd.DataFrame({
        "symbol": symbols,
        "sample_date": dates,
        "outcome": outcomes,
        "c00_open_rel": [0.01] * len(dates),
        "c00_high_rel": [0.02] * len(dates),
        "c00_low_rel": [-0.01] * len(dates),
        "c00_close_rel": [0.0] * len(dates),
        "c00_volume_rel": [1.0] * len(dates),
    })
    
    df.to_csv(csv_path, index=False)
    return str(csv_path)

def test_walk_forward_failure_analysis(mock_dataset_failure, tmp_path):
    report_path = tmp_path / "report.txt"
    run_failure_analysis_experiment(input_csv_path=mock_dataset_failure, report_path=str(report_path))
    
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    
    # Check sector unavailable note exists
    assert "Sector Concentration: unavailable in current exported dataset." in content
    
    # Check negative period flag
    assert "** NEGATIVE PERIOD DETECTED **" in content
    
    # Check symbol concentration fields
    assert "Top 1% Unique Symbols:" in content
    assert "Top 1% Max Symbol Share:" in content
    assert "Top 1% Best Symbols (WINs):" in content
    assert "Top 1% Worst Symbols (LOSSes):" in content
