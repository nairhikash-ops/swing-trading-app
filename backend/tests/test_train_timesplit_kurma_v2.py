import json

import pandas as pd
import pytest

from app.scripts.train_timesplit_kurma_v2 import (
    FORBIDDEN_TEST_CSV,
    KURMA_1_MODEL_VERSION,
    MODEL_VERSION,
    VARAHA_1_MODEL_VERSION,
    train_timesplit_kurma_v2,
)


def _features(count: int = 308) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_schema(path, features: list[str]) -> None:
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_train_csv(
    path,
    features: list[str],
    *,
    outcomes: list[str] | None = None,
    sample_dates: list[str] | None = None,
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
        rows.append(row)

    pd.DataFrame(rows, columns=["symbol", "sample_date", "outcome"] + features).to_csv(
        path, index=False
    )


def _paths(tmp_path):
    train_path = tmp_path / "exports" / "timesplit_regime_v2" / "train.csv"
    schema_path = tmp_path / "models" / "stock_opportunity_hgb_regime_v1" / "feature_schema.json"
    output_dir = tmp_path / "models" / MODEL_VERSION
    train_path.parent.mkdir(parents=True)
    schema_path.parent.mkdir(parents=True)
    return train_path, schema_path, output_dir


def _run_success(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)

    metadata = train_timesplit_kurma_v2(
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
        train_timesplit_kurma_v2(
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
        train_timesplit_kurma_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_excluded_outcomes_are_rejected(tmp_path):
    features = _features()
    train_path, schema_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(
        train_path,
        features,
        outcomes=["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN", "LOSS"],
    )

    with pytest.raises(ValueError, match="unsupported outcomes"):
        train_timesplit_kurma_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_mixed_or_unsafe_test_dates_are_rejected(tmp_path):
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
        train_timesplit_kurma_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=output_dir,
            expected_train_rows=6,
        )


def test_metadata_records_test_data_unused(tmp_path):
    metadata, output_dir = _run_success(tmp_path)
    written_metadata = json.loads((output_dir / "model_metadata.json").read_text())

    assert metadata["test_data_used"] is False
    assert written_metadata["test_data_used"] is False
    assert written_metadata["train_only"] is True
    assert written_metadata["forbidden_test_csv"] == str(FORBIDDEN_TEST_CSV)


def test_output_directory_is_kurma_2_only(tmp_path):
    metadata, output_dir = _run_success(tmp_path)

    assert output_dir.name == MODEL_VERSION
    assert metadata["model_version"] == MODEL_VERSION
    assert (output_dir / "model.joblib").exists()
    assert (output_dir / "feature_schema.json").exists()
    assert (output_dir / "model_metadata.json").exists()
    assert not (tmp_path / "models" / KURMA_1_MODEL_VERSION / "model_metadata.json").exists()
    assert not (tmp_path / "models" / VARAHA_1_MODEL_VERSION / "model_metadata.json").exists()


@pytest.mark.parametrize("protected_dir", [KURMA_1_MODEL_VERSION, VARAHA_1_MODEL_VERSION])
def test_protected_v1_output_directories_are_rejected(tmp_path, protected_dir):
    features = _features()
    train_path, schema_path, _ = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_train_csv(train_path, features)

    with pytest.raises(ValueError, match="protected model dir"):
        train_timesplit_kurma_v2(
            train_csv_path=train_path,
            schema_path=schema_path,
            output_dir=tmp_path / "models" / protected_dir,
            expected_train_rows=6,
        )
