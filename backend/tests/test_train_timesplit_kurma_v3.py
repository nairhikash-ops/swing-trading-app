import json
from pathlib import Path

import pandas as pd
import pytest

from app.scripts import train_timesplit_kurma_v3 as trainer
from app.scripts.train_timesplit_kurma_v3 import (
    DATASET_VERSION,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SPLIT_META_JSON,
    DEFAULT_TRAIN_CSV,
    FORBIDDEN_TEST_CSV,
    KURMA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    MODEL_ALIAS,
    MODEL_FAMILY,
    MODEL_VERSION,
    SPLIT_VERSION,
    VARAHA_1_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
    derive_feature_schema_from_train_header,
    train_timesplit_kurma_v3,
)


def _features(count: int = 608) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_train_csv(
    path: Path,
    features: list[str],
    *,
    outcomes: list[str] | None = None,
    sample_dates: list[str] | None = None,
    symbols: list[str] | None = None,
    metadata_columns: list[str] | None = None,
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
    symbols = symbols or [f"SYM{row_idx:03d}" for row_idx in range(len(outcomes))]
    metadata_columns = metadata_columns or ["symbol", "sample_date", "outcome"]

    rows = []
    for row_idx, outcome in enumerate(outcomes):
        row = {
            "symbol": symbols[row_idx],
            "sample_date": sample_dates[row_idx],
            "outcome": outcome,
        }
        row.update({feature: float((row_idx % 3) + 1) for feature in features})
        rows.append(row)

    pd.DataFrame(rows, columns=metadata_columns + features).to_csv(path, index=False)


def _write_split_meta(
    path: Path,
    *,
    train_rows: int = 6,
    test_rows: int = 3,
    total_rows: int = 9,
    feature_count: int = 608,
    dataset_version: str = SPLIT_VERSION,
    source_dataset_version: str = DATASET_VERSION,
    leakage_safe: bool = True,
) -> None:
    meta = {
        "dataset_version": dataset_version,
        "source_dataset_version": source_dataset_version,
        "train_row_count": train_rows,
        "test_row_count": test_rows,
        "total_eligible_row_count": total_rows,
        "feature_count": feature_count,
        "expected_feature_count": feature_count,
        "cutoff_date": "2025-07-09",
        "max_train_sample_date": "2025-07-08",
        "min_test_sample_date": "2025-07-09",
        "sample_date_overlap_count": 0,
        "leakage_safe": leakage_safe,
    }
    path.write_text(json.dumps(meta), encoding="utf-8")


def _paths(tmp_path: Path):
    split_dir = tmp_path / "exports" / SPLIT_VERSION
    train_path = split_dir / "train.csv"
    test_path = split_dir / "test.csv"
    split_meta_path = split_dir / "split_meta.json"
    output_dir = tmp_path / "models" / MODEL_VERSION
    split_dir.mkdir(parents=True)
    return train_path, test_path, split_meta_path, output_dir


def _run_success(tmp_path: Path):
    features = _features()
    train_path, test_path, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, features)
    test_path.write_text("this,file,must,not,be,read\n", encoding="utf-8")
    _write_split_meta(split_meta_path)

    metadata = train_timesplit_kurma_v3(
        train_csv_path=train_path,
        split_meta_json=split_meta_path,
        output_dir=output_dir,
        expected_train_rows=6,
        expected_test_rows=3,
        expected_total_rows=9,
    )
    return metadata, output_dir, train_path, test_path, split_meta_path


def test_constants_point_to_kurma_3_v3_paths():
    assert MODEL_VERSION == "stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
    assert MODEL_ALIAS == "Kurma 3"
    assert MODEL_FAMILY == "LogisticRegression"
    assert SPLIT_VERSION == "timesplit_regime_v3"
    assert DATASET_VERSION == "stock_opportunity_ohlcv_regime_v3"
    assert DEFAULT_TRAIN_CSV == Path("/app/data/exports/timesplit_regime_v3/train.csv")
    assert FORBIDDEN_TEST_CSV == Path("/app/data/exports/timesplit_regime_v3/test.csv")
    assert DEFAULT_SPLIT_META_JSON == Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
    assert DEFAULT_OUTPUT_DIR == Path(
        "/app/data/models/stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
    )


def test_model_identity_is_kurma_3_not_kurma_2():
    assert MODEL_ALIAS != "Kurma 2"
    assert MODEL_VERSION != KURMA_2_MODEL_VERSION
    assert MODEL_VERSION.endswith("_kurma_v3")


def test_source_has_no_old_model_or_old_schema_loads():
    source = Path(trainer.__file__).read_text(encoding="utf-8")
    assert "joblib.load" not in source
    assert "DEFAULT_SCHEMA_JSON" not in source
    assert "/app/data/models/stock_opportunity_hgb_regime_v1/feature_schema.json" not in source
    assert "timesplit_regime_v2" not in source
    assert "ml_dataset_ohlcv_regime_v1" not in source


def test_feature_schema_is_derived_from_train_csv_header(tmp_path):
    features = _features()
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(train_path, features)

    assert derive_feature_schema_from_train_header(train_path) == features


def test_608_features_are_required(tmp_path):
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(train_path, _features(607))

    with pytest.raises(ValueError, match="Total train column count must be exactly 611"):
        derive_feature_schema_from_train_header(train_path)


def test_first_three_metadata_columns_are_enforced(tmp_path):
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        metadata_columns=["sample_date", "symbol", "outcome"],
    )

    with pytest.raises(ValueError, match="First three columns must be exactly"):
        derive_feature_schema_from_train_header(train_path)


@pytest.mark.parametrize(
    "bad_path",
    [
        Path("exports/timesplit_regime_v3/test.csv"),
        Path("exports/timesplit_regime_v2/train.csv"),
        Path("exports/timesplit_regime_v3/not_train.csv"),
    ],
)
def test_old_or_unsafe_train_paths_are_rejected(tmp_path, bad_path):
    path = tmp_path / bad_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_train_csv(path, _features())

    with pytest.raises(ValueError):
        derive_feature_schema_from_train_header(path)


@pytest.mark.parametrize(
    "protected_dir",
    [
        KURMA_1_MODEL_VERSION,
        VARAHA_1_MODEL_VERSION,
        KURMA_2_MODEL_VERSION,
        VARAHA_2_MODEL_VERSION,
    ],
)
def test_protected_old_output_directories_are_rejected(tmp_path, protected_dir):
    features = _features()
    train_path, _, split_meta_path, _ = _paths(tmp_path)
    _write_train_csv(train_path, features)
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="protected model dir"):
        train_timesplit_kurma_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=tmp_path / "models" / protected_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
        )


def test_test_csv_is_not_read_during_training(tmp_path, monkeypatch):
    original_read_csv = trainer.pd.read_csv
    read_paths = []

    def tracking_read_csv(path, *args, **kwargs):
        read_paths.append(Path(path))
        if Path(path).name == "test.csv":
            raise AssertionError("test.csv must not be read during Kurma 3 training")
        return original_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(trainer.pd, "read_csv", tracking_read_csv)

    metadata, _, train_path, test_path, _ = _run_success(tmp_path)

    assert metadata["test_data_used"] is False
    assert train_path in read_paths
    assert test_path not in read_paths


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_version", "timesplit_regime_v2"),
        ("leakage_safe", False),
    ],
)
def test_split_meta_must_be_v3_and_leakage_safe(tmp_path, field, value):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, _features())
    kwargs = {field: value}
    _write_split_meta(split_meta_path, **kwargs)

    with pytest.raises(ValueError, match="locked v3 leakage-safe split"):
        train_timesplit_kurma_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
        )


def test_train_dates_must_be_strictly_before_cutoff(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        sample_dates=[
            "2025-07-04",
            "2025-07-05",
            "2025-07-06",
            "2025-07-08",
            "2025-07-09",
            "2025-07-10",
        ],
    )
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="sample_date >= 2025-07-09"):
        train_timesplit_kurma_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
        )


def test_duplicate_symbol_sample_date_rows_are_rejected(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        symbols=["DUP", "DUP", "SYM002", "SYM003", "SYM004", "SYM005"],
        sample_dates=[
            "2025-07-04",
            "2025-07-04",
            "2025-07-06",
            "2025-07-07",
            "2025-07-08",
            "2025-07-08",
        ],
    )
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="Duplicate symbol\\+sample_date"):
        train_timesplit_kurma_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
        )


def test_fresh_model_is_created_with_clean_train_only_metadata(tmp_path):
    metadata, output_dir, train_path, _, split_meta_path = _run_success(tmp_path)
    written_metadata = json.loads((output_dir / "model_metadata.json").read_text())
    written_schema = json.loads((output_dir / "feature_schema.json").read_text())

    assert (output_dir / "model.joblib").exists()
    assert set(path.name for path in output_dir.iterdir()) == {
        "model.joblib",
        "feature_schema.json",
        "model_metadata.json",
    }
    assert written_schema == _features()
    assert metadata["old_model_loaded"] is False
    assert metadata["old_schema_loaded"] is False
    assert metadata["train_only"] is True
    assert metadata["test_data_used"] is False
    assert metadata["feature_count"] == 608
    assert metadata["split_version"] == SPLIT_VERSION
    assert metadata["dataset_version"] == DATASET_VERSION
    assert metadata["feature_schema_source"] == "train_csv_header"
    assert metadata["feature_schema_match"] is True
    assert written_metadata["old_model_loaded"] is False
    assert written_metadata["old_schema_loaded"] is False
    assert written_metadata["train_only"] is True
    assert written_metadata["test_data_used"] is False
    assert written_metadata["feature_count"] == 608
    assert written_metadata["split_version"] == SPLIT_VERSION
    assert written_metadata["training_source_csv"] == str(train_path)
    assert written_metadata["split_meta_json"] == str(split_meta_path)
