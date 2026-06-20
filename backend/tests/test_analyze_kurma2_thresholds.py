import json

import pandas as pd
import pytest

from app.scripts.analyze_kurma2_thresholds import (
    MODEL_VERSION,
    analyze_kurma2_thresholds,
)


def _rows():
    return [
        ("AAA", "2025-07-09", "WIN", 1, 0.91, 1),
        ("BBB", "2025-07-09", "LOSS", 0, 0.82, 1),
        ("CCC", "2025-07-10", "TIMEOUT", 0, 0.71, 1),
        ("DDD", "2025-07-11", "WIN", 1, 0.63, 1),
        ("EEE", "2025-07-12", "LOSS", 0, 0.54, 1),
        ("FFF", "2025-07-13", "TIMEOUT", 0, 0.46, 0),
        ("GGG", "2025-07-14", "WIN", 1, 0.37, 0),
        ("HHH", "2025-07-15", "LOSS", 0, 0.28, 0),
        ("III", "2025-07-16", "TIMEOUT", 0, 0.19, 0),
        ("JJJ", "2025-07-17", "LOSS", 0, 0.08, 0),
    ]


def _write_predictions(path, rows=None, drop_columns=None) -> None:
    rows = rows or _rows()
    df = pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "sample_date",
            "outcome",
            "target",
            "win_probability",
            "predicted_label",
        ],
    )
    if drop_columns:
        df = df.drop(columns=drop_columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _paths(tmp_path):
    predictions_csv = tmp_path / "evaluations" / MODEL_VERSION / "test_predictions.csv"
    output_dir = tmp_path / "evaluations" / MODEL_VERSION
    return predictions_csv, output_dir


def _run_success(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    _write_predictions(predictions_csv)
    summary = analyze_kurma2_thresholds(
        predictions_csv=predictions_csv,
        output_dir=output_dir,
        expected_row_count=10,
    )
    return summary, output_dir


def test_missing_predictions_csv_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)

    with pytest.raises(FileNotFoundError, match="Predictions CSV not found"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_missing_required_columns_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    _write_predictions(predictions_csv, drop_columns=["win_probability"])

    with pytest.raises(ValueError, match="missing required columns"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_unsafe_sample_date_before_cutoff_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    rows = _rows()
    rows[0] = ("AAA", "2025-07-08", "WIN", 1, 0.91, 1)
    _write_predictions(predictions_csv, rows=rows)

    with pytest.raises(ValueError, match="sample_date < 2025-07-09"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_unsupported_outcome_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    rows = _rows()
    rows[1] = ("BBB", "2025-07-09", "AMBIGUOUS", 0, 0.82, 1)
    _write_predictions(predictions_csv, rows=rows)

    with pytest.raises(ValueError, match="unsupported outcomes"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_invalid_target_encoding_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    rows = _rows()
    rows[0] = ("AAA", "2025-07-09", "WIN", 0, 0.91, 1)
    _write_predictions(predictions_csv, rows=rows)

    with pytest.raises(ValueError, match="Target column does not match"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_invalid_probability_rejected(tmp_path):
    predictions_csv, output_dir = _paths(tmp_path)
    rows = _rows()
    rows[0] = ("AAA", "2025-07-09", "WIN", 1, 1.2, 1)
    _write_predictions(predictions_csv, rows=rows)

    with pytest.raises(ValueError, match="between 0 and 1"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )

    rows = _rows()
    rows[0] = ("AAA", "2025-07-09", "WIN", 1, "not-a-number", 1)
    _write_predictions(predictions_csv, rows=rows)

    with pytest.raises(ValueError, match="numeric and finite"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=output_dir,
            expected_row_count=10,
        )


def test_threshold_outputs_written_successfully(tmp_path):
    _, output_dir = _run_success(tmp_path)

    threshold_csv = output_dir / "threshold_analysis.csv"
    threshold_json = output_dir / "threshold_analysis.json"
    assert threshold_csv.exists()
    assert threshold_json.exists()

    df = pd.read_csv(threshold_csv)
    data = json.loads(threshold_json.read_text())
    assert len(df) == 9
    assert len(data) == 9
    assert set(df["threshold"]) == {0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50}
    assert "expectancy_win7_loss3_timeout0" in df.columns


def test_top_bucket_outputs_written_successfully(tmp_path):
    _, output_dir = _run_success(tmp_path)

    bucket_csv = output_dir / "top_bucket_analysis.csv"
    bucket_json = output_dir / "top_bucket_analysis.json"
    assert bucket_csv.exists()
    assert bucket_json.exists()

    df = pd.read_csv(bucket_csv)
    data = json.loads(bucket_json.read_text())
    assert len(df) == 8
    assert len(data) == 8
    assert set(df["label"]) == {
        "top_50",
        "top_100",
        "top_250",
        "top_500",
        "top_1000",
        "top_1_percent",
        "top_5_percent",
        "top_10_percent",
    }
    assert (df["candidate_count"] <= 10).all()


def test_metadata_records_no_db_mutation_or_deployment(tmp_path):
    summary, output_dir = _run_success(tmp_path)
    written_summary = json.loads((output_dir / "champion_summary.json").read_text())

    assert summary["db_mutation"] is False
    assert summary["deployed"] is False
    assert written_summary["db_mutation"] is False
    assert written_summary["deployed"] is False
    assert written_summary["analysis_type"] == "threshold_and_bucket_analysis"


def test_output_dir_is_only_kurma2_evaluation_dir(tmp_path):
    summary, output_dir = _run_success(tmp_path)

    assert output_dir.parent.name == "evaluations"
    assert output_dir.name == MODEL_VERSION
    assert summary["output_dir"] == str(output_dir)

    predictions_csv, _ = _paths(tmp_path / "unsafe")
    _write_predictions(predictions_csv)
    with pytest.raises(ValueError, match="evaluations directory"):
        analyze_kurma2_thresholds(
            predictions_csv=predictions_csv,
            output_dir=tmp_path / "models" / MODEL_VERSION,
            expected_row_count=10,
        )
