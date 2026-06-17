import os
import pytest
import pandas as pd
from unittest.mock import patch
from app.scripts.train_regime_baseline import encode_label, run_regime_training_experiment

@pytest.fixture
def tiny_regime_dataset(tmp_path) -> str:
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
    
    cols = metadata_cols + technical_cols + regime_cols

    data = []
    for i in range(10):
        row = ["A", f"2021-01-{i+1:02d}", "WIN" if i % 3 == 0 else "LOSS"]
        row.extend([float(i)] * 300)  # technical features
        row.extend([0.01 * i] * 8)    # regime features
        data.append(row)

    df = pd.DataFrame(data, columns=cols)
    csv_path = tmp_path / "tiny_regime.csv"
    df.to_csv(csv_path, index=False)
    return str(csv_path)


def test_train_regime_baseline_success(tmp_path, tiny_regime_dataset):
    report_path = str(tmp_path / "report.txt")
    model_path = str(tmp_path / "model.joblib")

    run_regime_training_experiment(
        input_csv_path=tiny_regime_dataset,
        report_path=report_path,
        model_path=model_path,
    )

    assert os.path.exists(report_path)
    assert os.path.exists(model_path)

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "=== REGIME BASELINE TRAINING EXPERIMENT ===" in content
        assert "Input row count:      10" in content
        assert "Feature column count: 308 (300 technical + 8 regime)" in content
        assert "Total column count:   311" in content
        assert "Train row count:      8" in content
        assert "Test row count:       2" in content
        assert "=== RANKING DIAGNOSTICS vs STOCK-ONLY BASELINE ===" in content
        assert "Top 10% | Rows:" in content
        assert "Delta:" in content
        assert "--- DECILE ANALYSIS ---" in content
        assert "D01 | Rows:" in content


def test_train_regime_baseline_missing_features(tmp_path):
    # Only 3 metadata columns + 1 random col -> missing expected columns
    df = pd.DataFrame({
        "symbol": ["A"], 
        "sample_date": ["2020-01-01"], 
        "outcome": ["WIN"],
        "extra_col": [1.0]
    })
    csv_path = tmp_path / "bad.csv"
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Expected exactly 311 columns"):
        run_regime_training_experiment(
            input_csv_path=str(csv_path),
            report_path=str(tmp_path / "report.txt"),
            model_path=str(tmp_path / "model.joblib"),
        )


def test_train_regime_baseline_nan_values(tmp_path, tiny_regime_dataset):
    # Load and inject NaN
    df = pd.read_csv(tiny_regime_dataset)
    df.loc[0, "market_median_20d_return"] = None
    csv_path = tmp_path / "nan_regime.csv"
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="NaN values found in feature columns."):
        run_regime_training_experiment(
            input_csv_path=str(csv_path),
            report_path=str(tmp_path / "report.txt"),
            model_path=str(tmp_path / "model.joblib"),
        )


def test_encode_label():
    assert encode_label("WIN") == 1
    assert encode_label("LOSS") == 0
    assert encode_label("TIMEOUT") == 0
    with pytest.raises(ValueError, match="Unknown outcome: OTHER"):
        encode_label("OTHER")


def test_chronological_split(tmp_path):
    metadata_cols = ["symbol", "sample_date", "outcome"]
    
    technical_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        technical_cols.extend([
            f"{prefix}open_rel", f"{prefix}high_rel", f"{prefix}low_rel", f"{prefix}close_rel", f"{prefix}volume_rel",
        ])
        
    regime_cols = [
        "market_median_20d_return", "market_breakout_rate", "market_breakdown_rate",
        "market_breadth_delta", "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median", "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    
    cols = metadata_cols + technical_cols + regime_cols

    data = []
    rows_info = [
        ("2021-01-05", "WIN"),     # newest -> should be test
        ("2021-01-04", "LOSS"),
        ("2021-01-02", "TIMEOUT"),
        ("2021-01-03", "WIN"),
        ("2021-01-01", "LOSS"),    # oldest -> should be train
    ]
    for date, outcome in rows_info:
        row = ["A", date, outcome]
        row.extend([0.0] * 300) # technical
        row.extend([0.0] * 8)   # regime
        data.append(row)

    df = pd.DataFrame(data, columns=cols)
    csv_path = tmp_path / "split_regime.csv"
    df.to_csv(csv_path, index=False)

    report_path = str(tmp_path / "report.txt")
    model_path = str(tmp_path / "model.joblib")

    with patch("app.scripts.train_regime_baseline.accuracy_score") as mock_acc:
        mock_acc.return_value = 0.5
        run_regime_training_experiment(str(csv_path), report_path, model_path)

        y_test_passed = mock_acc.call_args_list[0][0][0]
        assert len(y_test_passed) == 1
        assert y_test_passed.iloc[0] == 1  # newest date outcome WIN -> 1
