import os

from unittest.mock import patch

import pandas as pd
import pytest
from app.scripts.train_baseline import encode_label, run_training_experiment


@pytest.fixture
def tiny_dataset(tmp_path) -> str:
    cols = ["symbol", "sample_date", "outcome"]
    feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
    cols.extend(feature_cols)

    data = []
    for i in range(10):
        row = ["A", f"2021-01-{i+1:02d}", "WIN" if i % 3 == 0 else "LOSS"]
        row.extend([float(i)] * 300)
        data.append(row)

    df = pd.DataFrame(data, columns=cols)
    csv_path = tmp_path / "tiny.csv"
    df.to_csv(csv_path, index=False)
    return str(csv_path)


def test_train_baseline_success(tmp_path, tiny_dataset):
    report_path = str(tmp_path / "report.txt")
    model_path = str(tmp_path / "model.joblib")

    run_training_experiment(
        input_csv_path=tiny_dataset,
        report_path=report_path,
        model_path=model_path,
    )

    assert os.path.exists(report_path)
    assert os.path.exists(model_path)

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Input row count:      10" in content
        assert "Feature column count: 300" in content
        assert "Total column count:   303" in content
        assert "Train row count:      8" in content
        assert "Test row count:       2" in content


def test_train_baseline_missing_features(tmp_path):
    df = pd.DataFrame({"symbol": ["A"], "sample_date": ["2020-01-01"], "outcome": ["WIN"]})
    csv_path = tmp_path / "bad.csv"
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Expected exactly 300 feature columns"):
        run_training_experiment(
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
    cols = ["symbol", "sample_date", "outcome"]
    feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        feature_cols.extend([
            f"{prefix}open_rel", f"{prefix}high_rel", f"{prefix}low_rel", f"{prefix}close_rel", f"{prefix}volume_rel",
        ])
    cols.extend(feature_cols)

    data = []
    # Create 5 rows with dates completely out of order
    # The split should be 80% train (4 rows) and 20% test (1 row).
    # Since 2021-01-05 is the newest, it MUST end up in the test set.
    rows_info = [
        ("2021-01-05", "WIN"),     # newest -> should be test
        ("2021-01-04", "LOSS"),
        ("2021-01-02", "TIMEOUT"),
        ("2021-01-03", "WIN"),
        ("2021-01-01", "LOSS"),    # oldest -> should be train
    ]
    for date, outcome in rows_info:
        row = ["A", date, outcome]
        row.extend([0.0] * 300)
        data.append(row)

    df = pd.DataFrame(data, columns=cols)
    csv_path = tmp_path / "split.csv"
    df.to_csv(csv_path, index=False)

    report_path = str(tmp_path / "report.txt")
    model_path = str(tmp_path / "model.joblib")

    with patch("app.scripts.train_baseline.accuracy_score") as mock_acc:
        mock_acc.return_value = 0.5
        run_training_experiment(str(csv_path), report_path, model_path)

        # Check what was passed as y_test to accuracy_score
        y_test_passed = mock_acc.call_args_list[0][0][0]

        # Length should be exactly 1 (20% of 5)
        assert len(y_test_passed) == 1

        # The single test row should be the newest date (2021-01-05), which is a WIN (encoded as 1)
        assert y_test_passed.iloc[0] == 1
