import json

import pandas as pd
import pytest

from app.scripts.export_ml_dataset_timesplit_v2 import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_CSV,
    ELIGIBLE_OUTCOMES,
    _validate_date_split,
    export_timesplit,
)


def _features(count: int = 308) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_schema(path, features: list[str]) -> None:
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_dataset(path, features: list[str], outcomes: list[str | None] | None = None) -> None:
    outcomes = outcomes or ["WIN", "LOSS", "TIMEOUT", "WIN"]
    sample_dates = [
        "2025-07-08",
        "2025-07-08",
        "2025-07-09",
        "2025-07-10",
        "2025-07-07",
        "2025-07-11",
    ]
    rows = []
    for row_idx, outcome in enumerate(outcomes):
        row = {
            "symbol": f"SYM{row_idx}",
            "sample_date": sample_dates[row_idx],
            "outcome": outcome,
        }
        row.update({feature: float(row_idx) for feature in features})
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)


def _run_export(tmp_path, features: list[str] | None = None, outcomes=None, schema=None):
    features = features or _features()
    schema = schema or features
    source_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    schema_path = tmp_path / "feature_schema.json"
    output_dir = tmp_path / "timesplit_regime_v2"
    _write_dataset(source_path, features, outcomes=outcomes)
    _write_schema(schema_path, schema)

    meta = export_timesplit(
        source_csv_path=source_path,
        schema_path=schema_path,
        output_dir=output_dir,
        expected_total_rows=4,
        expected_train_rows=2,
        expected_test_rows=2,
    )
    return meta, output_dir


def test_default_paths_use_regime_dataset_and_new_output_dir():
    assert DEFAULT_SOURCE_CSV.as_posix() == "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv"
    assert DEFAULT_OUTPUT_DIR.as_posix() == "/app/data/exports/timesplit_regime_v2"


def test_base_non_regime_source_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="base OHLCV CSV is not valid"):
        export_timesplit(
            source_csv_path=tmp_path / "ml_dataset_ohlcv_v1.csv",
            schema_path=tmp_path / "feature_schema.json",
            output_dir=tmp_path / "timesplit_regime_v2",
            expected_total_rows=4,
            expected_train_rows=2,
            expected_test_rows=2,
        )


def test_export_timesplit_success_writes_regime_split_and_meta(tmp_path):
    meta, output_dir = _run_export(tmp_path)

    train = pd.read_csv(output_dir / "train.csv")
    test = pd.read_csv(output_dir / "test.csv")

    assert (output_dir / "train.csv").exists()
    assert (output_dir / "test.csv").exists()
    assert (output_dir / "split_meta.json").exists()
    assert meta["source_path"].endswith("ml_dataset_ohlcv_regime_v1.csv")
    assert meta["obsolete_previous_export_path"] == "/app/data/exports/timesplit_v2/"
    assert meta["train_row_count"] == 2
    assert meta["test_row_count"] == 2
    assert meta["feature_count"] == 308
    assert meta["expected_feature_count"] == 308
    assert meta["feature_schema_match"] is True
    assert meta["sample_date_overlap_count"] == 0
    assert meta["leakage_safe"] is True
    assert len(train.columns) == 311
    assert list(train.columns) == list(test.columns)
    assert set(train["outcome"]).issubset(set(ELIGIBLE_OUTCOMES))
    assert set(test["outcome"]).issubset(set(ELIGIBLE_OUTCOMES))


def test_feature_count_must_be_308(tmp_path):
    features = _features(307)
    source_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    schema_path = tmp_path / "feature_schema.json"
    _write_dataset(source_path, features)
    _write_schema(schema_path, features)

    with pytest.raises(ValueError, match="Feature count 307 does not match expected 308"):
        export_timesplit(
            source_csv_path=source_path,
            schema_path=schema_path,
            output_dir=tmp_path / "timesplit_regime_v2",
            expected_total_rows=4,
            expected_train_rows=2,
            expected_test_rows=2,
        )


def test_feature_schema_must_match_varaha_schema_order(tmp_path):
    features = _features()
    schema = features.copy()
    schema[0], schema[1] = schema[1], schema[0]

    with pytest.raises(ValueError, match="Feature schema does not match"):
        _run_export(tmp_path, features=features, schema=schema)


def test_train_test_date_overlap_is_rejected():
    train = pd.DataFrame({"sample_date": ["2025-07-08", "2025-07-09"]})
    test = pd.DataFrame({"sample_date": ["2025-07-09", "2025-07-10"]})

    with pytest.raises(ValueError, match="overlap is not zero"):
        _validate_date_split(train, test)


def test_excluded_outcomes_are_filtered_from_outputs(tmp_path):
    outcomes = ["WIN", "LOSS", "TIMEOUT", "WIN", "AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA"]
    meta, output_dir = _run_export(tmp_path, outcomes=outcomes)

    train = pd.read_csv(output_dir / "train.csv")
    test = pd.read_csv(output_dir / "test.csv")
    output_outcomes = set(pd.concat([train["outcome"], test["outcome"]]))

    assert output_outcomes == {"WIN", "LOSS", "TIMEOUT"}
    assert meta["total_eligible_row_count"] == 4
    assert "AMBIGUOUS" in meta["excluded_outcomes"]
    assert "INSUFFICIENT_FUTURE_DATA" in meta["excluded_outcomes"]


def test_unsafe_output_path_is_rejected(tmp_path):
    features = _features()
    source_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    schema_path = tmp_path / "feature_schema.json"
    _write_dataset(source_path, features)
    _write_schema(schema_path, features)

    with pytest.raises(ValueError, match="Unsafe output path detected"):
        export_timesplit(
            source_csv_path=source_path,
            schema_path=schema_path,
            output_dir=tmp_path / "timesplit_v2",
            expected_total_rows=4,
            expected_train_rows=2,
            expected_test_rows=2,
        )
