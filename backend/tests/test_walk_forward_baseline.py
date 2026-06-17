import os
import pandas as pd
import pytest

from app.scripts.walk_forward_baseline import run_walk_forward_experiment


@pytest.fixture
def mock_dataset(tmp_path):
    csv_path = tmp_path / "ml_dataset_ohlcv_v1.csv"
    
    # We need:
    # Earliest date: 2020-01-01
    # First validation start: 2022-01-01 (2 years later)
    # Validation period 1: 2022-01-01 to 2022-04-01
    # Validation period 2: 2022-04-01 to 2022-07-01
    # Partial period 3 (skipped): 2022-07-01 to 2022-08-01

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
    
    # Ensure all classes are present in training so logistic regression doesn't crash
    # Outcomes: length = 17
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
    
    df = pd.DataFrame({
        "symbol": ["AAPL"] * len(dates),
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

def test_walk_forward_baseline(mock_dataset, tmp_path):
    report_path = tmp_path / "report.txt"
    run_walk_forward_experiment(input_csv_path=mock_dataset, report_path=str(report_path))
    
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    
    # Check partial period logic
    assert "Skipping final partial period starting 2022-07-01" in content
    
    # Check period counts
    assert "Total completed periods:       2" in content
    
    # Verify training ends logic and embargoes.
    # Period 1: Val start 2022-01-01. Embargo = 35 days = 2021-11-27.
    assert "Training end (post-embargo): 2021-11-27" in content
    
    # Period 2: Val start 2022-04-01. Embargo = 2022-02-25.
    assert "Training end (post-embargo): 2022-02-25" in content

    # Check top metrics format
    assert "Top 01% | Rows:" in content
    assert "Top 05% | Rows:" in content
    assert "Exp: " in content
