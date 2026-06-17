import pandas as pd
import pytest

from app.scripts.walk_forward_regime_diagnostics import (
    derive_regime_metrics,
    run_regime_diagnostics_experiment,
)

def test_derive_regime_metrics_bull_market():
    # Bull market:
    # 20d ago (c39), price was 100. Current (c59), price is 120. Return = +20%
    # c39_rel = 100/120 - 1.0 = -0.1666...
    # Since prices went up, all previous prices are < current close.
    # Max of prev prices < 0 -> Breakout
    
    data = {"c39_close_rel": [-0.166666666]}
    for i in range(40, 59):
        # gradually increasing prices, but all below 120
        # e.g., 101/120 - 1.0 = -0.1583
        data[f"c{i}_close_rel"] = [-0.15]
        
    df = pd.DataFrame(data)
    
    metrics = derive_regime_metrics(df)
    
    # 1.0 / (-0.166666666 + 1.0) - 1.0 -> 1.0 / 0.833333334 - 1.0 -> 1.20 - 1.0 = 0.20
    assert pytest.approx(metrics["median_20d_return"], 0.01) == 0.20
    assert pytest.approx(metrics["mean_20d_return"], 0.01) == 0.20
    
    # Max is < 0, so it's a breakout
    assert metrics["breakout_rate"] == 1.0
    assert metrics["breakdown_rate"] == 0.0
    assert metrics["hostile_regime_flag"] is False


def test_derive_regime_metrics_bear_market():
    # Bear market:
    # 20d ago (c39), price was 120. Current (c59), price is 100. Return = -16.66%
    # c39_rel = 120/100 - 1.0 = 0.20
    # Since prices went down, all previous prices are > current close.
    # Min of prev prices > 0 -> Breakdown
    
    data = {"c39_close_rel": [0.20]}
    for i in range(40, 59):
        data[f"c{i}_close_rel"] = [0.10]
        
    df = pd.DataFrame(data)
    
    metrics = derive_regime_metrics(df)
    
    # 1.0 / (0.20 + 1.0) - 1.0 -> 1.0 / 1.20 - 1.0 -> 0.8333 - 1.0 = -0.1666
    assert pytest.approx(metrics["median_20d_return"], 0.01) == -0.1666
    
    # Min is > 0, so it's a breakdown
    assert metrics["breakout_rate"] == 0.0
    assert metrics["breakdown_rate"] == 1.0
    assert metrics["hostile_regime_flag"] is True

def test_walk_forward_regime_diagnostics_integration(tmp_path):
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
        "TSLA", "TSLA", "AAPL", "AAPL", "TSLA",
        "AAPL"
    ]
    
    data = {
        "symbol": symbols,
        "sample_date": dates,
        "outcome": outcomes,
    }
    
    # Add dummy c00 to c59 features
    for i in range(60):
        prefix = f"c{i:02d}_"
        data[f"{prefix}open_rel"] = [0.0] * len(dates)
        data[f"{prefix}high_rel"] = [0.0] * len(dates)
        data[f"{prefix}low_rel"] = [0.0] * len(dates)
        data[f"{prefix}close_rel"] = [0.0] * len(dates)
        data[f"{prefix}volume_rel"] = [0.0] * len(dates)
        
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    
    report_path = tmp_path / "report.txt"
    run_regime_diagnostics_experiment(input_csv_path=str(csv_path), report_path=str(report_path))
    
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    
    # Check that missing index ticker didn't fail the script
    assert "Sector/Index Info:    unavailable in current exported dataset." in content
    
    # Check that standard fields are present
    assert "median_20d_return:" in content
    assert "breakout_minus_breakdown:" in content
    assert "hostile_regime_flag:" in content
