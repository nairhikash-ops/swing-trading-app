import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.scripts import train_timesplit_varaha_v3 as trainer
from app.scripts.train_timesplit_varaha_v3 import (
    DATASET_VERSION,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SPLIT_META_JSON,
    DEFAULT_TRAIN_CSV,
    EXPECTED_FIRST_10_FEATURES,
    EXPECTED_LAST_8_REGIME_FEATURES,
    FORBIDDEN_TEST_CSV,
    KURMA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    KURMA_3_MODEL_VERSION,
    MODEL_ALIAS,
    MODEL_FAMILY,
    MODEL_VERSION,
    PROTECTED_MODEL_DIRS,
    SPLIT_VERSION,
    VARAHA_1_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
    derive_feature_schema_from_train_header,
    train_timesplit_varaha_v3,
)


class RecordingHGB:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fit_shape = None
        self.y_values = None
        RecordingHGB.calls.append({"kwargs": kwargs, "instance": self})

    def fit(self, X, y):
        self.fit_shape = X.shape
        self.y_values = y.tolist()
        return self


def _features(count: int = 608) -> list[str]:
    if count < len(EXPECTED_FIRST_10_FEATURES) + len(EXPECTED_LAST_8_REGIME_FEATURES):
        return [f"feature_{idx:03d}" for idx in range(count)]

    filler_count = count - len(EXPECTED_FIRST_10_FEATURES) - len(
        EXPECTED_LAST_8_REGIME_FEATURES
    )
    filler = [f"feature_{idx:03d}" for idx in range(10, 10 + filler_count)]
    return EXPECTED_FIRST_10_FEATURES + filler + EXPECTED_LAST_8_REGIME_FEATURES


def _write_train_csv(
    path: Path,
    features: list[str],
    *,
    outcomes: list[str] | None = None,
    sample_dates: list[str] | None = None,
    symbols: list[str] | None = None,
    metadata_columns: list[str] | None = None,
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
        if feature_value is not None:
            row[features[0]] = feature_value
        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
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
    max_train_sample_date: str = "2025-07-08",
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
        "max_train_sample_date": max_train_sample_date,
        "min_test_sample_date": "2025-07-09",
        "sample_date_overlap_count": 0,
        "leakage_safe": leakage_safe,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta), encoding="utf-8")


def _paths(tmp_path: Path):
    split_dir = tmp_path / "exports" / SPLIT_VERSION
    train_path = split_dir / "train.csv"
    test_path = split_dir / "test.csv"
    split_meta_path = split_dir / "split_meta.json"
    output_dir = tmp_path / "models" / MODEL_VERSION
    split_dir.mkdir(parents=True)
    return train_path, test_path, split_meta_path, output_dir


def _patch_model(monkeypatch):
    RecordingHGB.calls = []
    monkeypatch.setattr(trainer, "HistGradientBoostingClassifier", RecordingHGB)


def _run_success(tmp_path: Path, monkeypatch):
    _patch_model(monkeypatch)
    features = _features()
    train_path, test_path, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, features)
    test_path.write_text("this,file,must,not,be,read\n", encoding="utf-8")
    _write_split_meta(split_meta_path)

    metadata = train_timesplit_varaha_v3(
        train_csv_path=train_path,
        split_meta_json=split_meta_path,
        output_dir=output_dir,
        expected_train_rows=6,
        expected_test_rows=3,
        expected_total_rows=9,
        expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
    )
    return metadata, output_dir, train_path, test_path, split_meta_path


def test_constants_point_to_varaha_3_v3_paths():
    assert MODEL_VERSION == "stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
    assert MODEL_ALIAS == "Varaha 3"
    assert MODEL_FAMILY == "HistGradientBoostingClassifier"
    assert SPLIT_VERSION == "timesplit_regime_v3"
    assert DATASET_VERSION == "stock_opportunity_ohlcv_regime_v3"
    assert DEFAULT_TRAIN_CSV == Path("/app/data/exports/timesplit_regime_v3/train.csv")
    assert FORBIDDEN_TEST_CSV == Path("/app/data/exports/timesplit_regime_v3/test.csv")
    assert DEFAULT_SPLIT_META_JSON == Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
    assert DEFAULT_OUTPUT_DIR == Path(
        "/app/data/models/stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
    )


def test_source_has_no_old_paths_or_old_model_loads():
    source = Path(trainer.__file__).read_text(encoding="utf-8")
    assert "timesplit_regime_" + "v2" not in source
    assert (
        "/app/data/models/"
        + "stock_opportunity_hgb_regime_v1"
        + "/feature_schema.json"
        not in source
    )
    assert "joblib." + "load" not in source


def test_protected_model_dirs_include_all_old_model_versions():
    assert {
        KURMA_1_MODEL_VERSION,
        VARAHA_1_MODEL_VERSION,
        KURMA_2_MODEL_VERSION,
        VARAHA_2_MODEL_VERSION,
        KURMA_3_MODEL_VERSION,
    }.issubset(PROTECTED_MODEL_DIRS)


@pytest.mark.parametrize(
    "protected_dir",
    [
        KURMA_1_MODEL_VERSION,
        VARAHA_1_MODEL_VERSION,
        KURMA_2_MODEL_VERSION,
        VARAHA_2_MODEL_VERSION,
        KURMA_3_MODEL_VERSION,
    ],
)
def test_protected_old_output_directories_are_rejected(tmp_path, protected_dir):
    train_path, _, split_meta_path, _ = _paths(tmp_path)
    _write_train_csv(train_path, _features())
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="protected model dir"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=tmp_path / "models" / protected_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_output_directory_must_be_varaha_3_model_version(tmp_path):
    train_path, _, split_meta_path, _ = _paths(tmp_path)
    _write_train_csv(train_path, _features())
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="Unsafe output directory"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=tmp_path / "models" / "unexpected_model",
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


@pytest.mark.parametrize(
    "bad_path",
    [
        Path("exports") / SPLIT_VERSION / "test.csv",
        Path("exports") / ("timesplit_regime_" + "v2") / "train.csv",
        Path("exports") / SPLIT_VERSION / "not_train.csv",
    ],
)
def test_old_or_unsafe_train_paths_are_rejected(tmp_path, bad_path):
    path = tmp_path / bad_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_train_csv(path, _features())

    with pytest.raises(ValueError):
        derive_feature_schema_from_train_header(path)


def test_split_metadata_is_validated_exactly(tmp_path, monkeypatch):
    metadata, _, _, _, _ = _run_success(tmp_path, monkeypatch)

    assert metadata["split_metadata_validated"] is True
    assert metadata["split_version"] == SPLIT_VERSION
    assert metadata["dataset_version"] == DATASET_VERSION
    assert metadata["feature_count"] == 608


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("leakage_safe", False, "locked v3 leakage-safe split"),
        ("feature_count", 607, "locked v3 leakage-safe split"),
    ],
)
def test_split_meta_must_be_leakage_safe_with_608_features(tmp_path, field, value, message):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, _features())
    kwargs = {field: value}
    _write_split_meta(split_meta_path, **kwargs)

    with pytest.raises(ValueError, match=message):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_first_three_metadata_columns_are_enforced(tmp_path):
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        metadata_columns=["sample_date", "symbol", "outcome"],
    )

    with pytest.raises(ValueError, match="First three columns must be exactly"):
        derive_feature_schema_from_train_header(train_path)


def test_608_features_are_required(tmp_path):
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(train_path, _features(607))

    with pytest.raises(ValueError, match="Total train column count must be exactly 611"):
        derive_feature_schema_from_train_header(train_path)


def test_metadata_column_inside_feature_schema_is_rejected(tmp_path):
    train_path, _, _, _ = _paths(tmp_path)
    features = _features()
    features[12] = "outcome"
    _write_train_csv(train_path, features)

    with pytest.raises(ValueError, match="metadata columns"):
        derive_feature_schema_from_train_header(train_path)


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
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_wrong_max_train_sample_date_is_rejected(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        sample_dates=[
            "2025-07-03",
            "2025-07-04",
            "2025-07-05",
            "2025-07-06",
            "2025-07-07",
            "2025-07-07",
        ],
    )
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="Max train sample_date"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_unsupported_outcomes_are_rejected(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        outcomes=["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN", "LOSS"],
    )
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="unsupported outcomes"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_missing_required_outcome_class_is_rejected(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(
        train_path,
        _features(),
        outcomes=["WIN", "LOSS", "WIN", "LOSS"],
        sample_dates=["2025-07-04", "2025-07-05", "2025-07-06", "2025-07-08"],
    )
    _write_split_meta(split_meta_path, train_rows=4, total_rows=7)

    with pytest.raises(ValueError, match="missing required outcome classes"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=4,
            expected_test_rows=3,
            expected_total_rows=7,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 0},
        )


def test_wrong_train_outcome_counts_are_rejected(tmp_path):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, _features())
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match="Train outcome counts do not match"):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 3, "LOSS": 2, "TIMEOUT": 1},
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
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


@pytest.mark.parametrize("feature_value, message", [(np.nan, "NaN"), (np.inf, "Infinite")])
def test_nan_or_infinite_feature_values_are_rejected(tmp_path, feature_value, message):
    train_path, _, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, _features(), feature_value=feature_value)
    _write_split_meta(split_meta_path)

    with pytest.raises(ValueError, match=message):
        train_timesplit_varaha_v3(
            train_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=6,
            expected_test_rows=3,
            expected_total_rows=9,
            expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
        )


def test_fresh_hgb_model_is_created_with_random_state_42_and_fit_called(tmp_path, monkeypatch):
    metadata, _, _, _, _ = _run_success(tmp_path, monkeypatch)

    assert metadata["model_family"] == "HistGradientBoostingClassifier"
    assert len(RecordingHGB.calls) == 1
    model = RecordingHGB.calls[0]["instance"]
    assert RecordingHGB.calls[0]["kwargs"] == {"random_state": 42}
    assert model.fit_shape == (6, 608)
    assert model.y_values == [1, 0, 0, 1, 0, 0]


def test_fit_call_only_exists_in_training_function():
    source = Path(trainer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fit_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "fit":
                function_name = None
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.FunctionDef) and any(child is node for child in ast.walk(parent)):
                        function_name = parent.name
                        break
                fit_calls.append(function_name)

    assert fit_calls == ["train_timesplit_varaha_v3"]


def test_writes_only_model_schema_and_metadata_to_varaha_3_output_dir(tmp_path, monkeypatch):
    metadata, output_dir, train_path, _, split_meta_path = _run_success(tmp_path, monkeypatch)
    written_metadata = json.loads((output_dir / "model_metadata.json").read_text())
    written_schema = json.loads((output_dir / "feature_schema.json").read_text())

    assert output_dir.name == MODEL_VERSION
    assert set(path.name for path in output_dir.iterdir()) == {
        "model.joblib",
        "feature_schema.json",
        "model_metadata.json",
    }
    assert (output_dir / "model.joblib").exists()
    assert written_schema == _features()
    assert written_metadata["model_version"] == MODEL_VERSION
    assert written_metadata["model_alias"] == MODEL_ALIAS
    assert written_metadata["model_family"] == MODEL_FAMILY
    assert written_metadata["training_source_csv"] == str(train_path)
    assert written_metadata["split_meta_json"] == str(split_meta_path)
    assert written_metadata["feature_count"] == 608
    assert metadata["feature_count"] == 608


def test_metadata_records_clean_train_only_safety_flags(tmp_path, monkeypatch):
    metadata, output_dir, _, _, _ = _run_success(tmp_path, monkeypatch)
    written_metadata = json.loads((output_dir / "model_metadata.json").read_text())

    for payload in [metadata, written_metadata]:
        assert payload["train_only"] is True
        assert payload["test_data_used"] is False
        assert payload["old_model_loaded"] is False
        assert payload["old_schema_loaded"] is False
        assert payload["db_mutation"] is False
        assert payload["deployed"] is False
        assert payload["champion_selected"] is False
        assert payload["feature_schema_source"] == "train_csv_header"
        assert payload["feature_schema_match"] is True
        assert payload["split_metadata_validated"] is True


def test_feature_schema_is_derived_from_train_csv_header(tmp_path):
    features = _features()
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(train_path, features)

    assert derive_feature_schema_from_train_header(train_path) == features


def test_first_10_v3_features_and_last_8_regime_features_are_preserved(tmp_path):
    features = _features()
    train_path, _, _, _ = _paths(tmp_path)
    _write_train_csv(train_path, features)
    derived = derive_feature_schema_from_train_header(train_path)

    assert derived[:10] == EXPECTED_FIRST_10_FEATURES
    assert derived[-8:] == EXPECTED_LAST_8_REGIME_FEATURES


def test_test_csv_is_not_read_during_training(tmp_path, monkeypatch):
    _patch_model(monkeypatch)
    original_read_csv = trainer.pd.read_csv
    read_paths = []

    def tracking_read_csv(path, *args, **kwargs):
        read_paths.append(Path(path))
        if Path(path).name == "test.csv":
            raise AssertionError("test.csv must not be read during Varaha 3 training")
        return original_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(trainer.pd, "read_csv", tracking_read_csv)

    features = _features()
    train_path, test_path, split_meta_path, output_dir = _paths(tmp_path)
    _write_train_csv(train_path, features)
    test_path.write_text("this,file,must,not,be,read\n", encoding="utf-8")
    _write_split_meta(split_meta_path)

    metadata = train_timesplit_varaha_v3(
        train_csv_path=train_path,
        split_meta_json=split_meta_path,
        output_dir=output_dir,
        expected_train_rows=6,
        expected_test_rows=3,
        expected_total_rows=9,
        expected_train_outcome_counts={"WIN": 2, "LOSS": 2, "TIMEOUT": 2},
    )

    assert metadata["test_data_used"] is False
    assert train_path in read_paths
    assert test_path not in read_paths
