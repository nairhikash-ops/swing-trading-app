import json

import numpy as np
import pandas as pd
import pytest

from app.scripts.train_timesplit_varaha_v2 import (
    FORBIDDEN_TEST_CSV,
    KURMA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    MODEL_VERSION,
    VARAHA_1_MODEL_VERSION,
    train_timesplit_varaha_v2,
)


def _features(count: int = 308) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_schema(path, features: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_train_csv(
    path,
    features: list[str],
    *,
    outcomes: list[str] | None = None,
    sample_dates: list[str] | None = None,
    feature_value=None,
) -> None:
    outcomes = outcomes or ["WIN", "LOSS", "TIMEOUT", "WIN", "LOSS", "TIMEOUT"]
    sample_dates = sample_dates or [
        "2025-07-04",
        "2025-07-05",
        "2025-07-06",
        "2025-07-07",
        "2025-07-08",
        "2025-07-08",
    ]

    rows = []
    for row_idx, outcome in enumerate(outcomes):
        row = {
            "symbol": f"SYM{row_idx:03d}",
            "sample_date": sample_dates[row_idx],
            "outcome": outcome,
        }
        row.update({feature: float((row_idx % 3) + 1) for feature in features})
        if feature_value is not None:
            row[features[0]] = feature_value
        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["symbol", "sample_date", "outcome"] + features).to_csv(
        path, index=False
    )


def _paths(tmp_path):
    train_path = tmp_path / "exports" / "timesplit_regime_v2" / "train.csv"
    schema_path = tmp_path / "models" / "stock_opportunity_hgb_regime_v1" / "feature_schema.json"
    output_dir = tmp_path / "models" / MODEL_VERSION
    return train_path, schema_path, output_dir


def _run_success(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)

    metadata = train_timesplit_varaha_v2(
        train_csv_path=train_path,
        schema_path=schema_path,
        output_dir=output_dir,
        expected_train_rows=6,
        expected_max_train_sample_date="2025-07-08",
    )
    return metadata, output_dir


def test_missing_train_csv_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)

    with pytest.raises(FileNotFoundError, match="Train CSV not found"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_missing_schema_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, features)

    with pytest.raises(FileNotFoundError, match="Feature schema not found"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_wrong_feature_count_is_rejected(tmp_path):
    schema_features = _features()
    train_features = schema_features[:-1]
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, schema_features)
    _write_train_csv(train_path, train_features)

    with pytest.raises(ValueError, match="Expected 308 feature columns"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_feature_schema_mismatch_is_rejected(tmp_path):
    schema_features = _features()
    train_features = schema_features.copy()
    train_features[7] = "unexpected_feature_007"
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, schema_features)
    _write_train_csv(train_path, train_features)

    with pytest.raises(ValueError, match="Feature schema does not match"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_unsupported_outcome_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(
        train_path,
        features,
        outcomes=["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN", "LOSS"],
    )

    with pytest.raises(ValueError, match="unsupported outcomes"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_missing_required_outcome_class_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features, outcomes=["WIN", "LOSS", "WIN", "LOSS", "WIN", "LOSS"])

    with pytest.raises(ValueError, match="missing required outcome classes"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_unsafe_train_test_date_contamination_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(
        train_path,
        features,
        sample_dates=[
            "2025-07-04",
            "2025-07-05",
            "2025-07-06",
            "2025-07-08",
            "2025-07-09",
            "2025-07-10",
        ],
    )

    with pytest.raises(ValueError, match="sample_date >= 2025-07-09"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


@pytest.mark.parametrize("feature_value, message", [(np.nan, "NaN"), (np.inf, "Infinite")])
def test_nan_or_infinite_feature_is_rejected(tmp_path, feature_value, message):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features, feature_value=feature_value)

    with pytest.raises(ValueError, match=message):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


@pytest.mark.parametrize("protected_dir", [KURMA_1_MODEL_VERSION, VARAHA_1_MODEL_VERSION])
def test_protected_old_model_dirs_are_rejected(tmp_path, protected_dir):
    features = _features()
    train_path, schema_path, _ = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)

    with pytest.raises(ValueError, match="protected model dir"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=tmp_path / "models" / protected_dir,
            expected_train_rows=6,
        )


def test_protected_kurma_2_model_dir_is_rejected(tmp_path):
    features = _features()
    train_path, schema_path, _ = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)

    with pytest.raises(ValueError, match="protected model dir"):
        train_timesplit_varaha_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=tmp_path / "models" / KURMA_2_MODEL_VERSION,
            expected_train_rows=6,
        )


def test_output_directory_is_varaha_2_only(tmp_path):
    metadata, output_dir = _run_success(tmp_path)

    assert output_dir.name == MODEL_VERSION
    assert metadata["model_version"] == MODEL_VERSION
    assert metadata["model_alias"] == "Varaha 2"
    assert metadata["model_family"] == "HistGradientBoostingClassifier"
    assert (output_dir / "model.joblib").exists()
    assert (output_dir / "feature_schema.json").exists()
    assert (output_dir / "model_metadata.json").exists()
    assert not (tmp_path / "models" / KURMA_1_MODEL_VERSION / "model_metadata.json").exists()
    assert not (tmp_path / "models" / VARAHA_1_MODEL_VERSION / "model_metadata.json").exists()
    assert not (tmp_path / "models" / KURMA_2_MODEL_VERSION / "model_metadata.json").exists()


def test_metadata_records_test_data_unused(tmp_path):
    metadata, output_dir = _run_success(tmp_path)
    written_metadata = json.loads((output_dir / "model_metadata.json").read_text())

    assert metadata["test_data_used"] is False
    assert written_metadata["test_data_used"] is False
    assert written_metadata["train_only"] is True
    assert written_metadata["forbidden_test_csv"] == str(FORBIDDEN_TEST_CSV)
    assert written_metadata["train_row_count"] == 6
    assert written_metadata["feature_count"] == 308


def test_test_csv_is_never_read(tmp_path, monkeypatch):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    test_path = tmp_path / "exports" / "timesplit_regime_v2" / "test.csv"
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)
    _write_train_csv(test_path, features)

    original_read_csv = pd.read_csv
    read_paths = []

    def tracking_read_csv(path, *args, **kwargs):
        read_paths.append(str(path))
        if PathLike(path).name == "test.csv":
            raise AssertionError("test.csv must not be read")
        return original_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", tracking_read_csv)

    train_timesplit_varaha_v2(
        train_csv_path=train_path,
        schema_path=schema_path,
        output_dir=output_dir,
        expected_train_rows=6,
        expected_max_train_sample_date="2025-07-08",
    )

    assert str(test_path) not in read_paths
    assert read_paths == [str(train_path), str(train_path)]


class PathLike:
    def __init__(self, path):
        self._path = path

    @property
    def name(self):
        return getattr(self._path, "name", "")
