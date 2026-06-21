import ast
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from app.scripts import score_timesplit_varaha_v3 as scorer
from app.scripts.score_timesplit_varaha_v3 import (
    DATASET_VERSION,
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_METADATA_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_SPLIT_META_JSON,
    DEFAULT_TEST_CSV,
    EXPECTED_FIRST_10_FEATURES,
    EXPECTED_LAST_8_REGIME_FEATURES,
    FORBIDDEN_TRAIN_CSV,
    KURMA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    KURMA_3_MODEL_VERSION,
    LABEL_ENCODING,
    MODEL_ALIAS,
    MODEL_FAMILY,
    MODEL_VERSION,
    MVP_GATE_DEFINITION,
    MVP_PRECISION_THRESHOLD,
    PROTECTED_MODEL_DIRS,
    SPLIT_VERSION,
    VARAHA_1_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
    load_feature_schema,
    score_timesplit_varaha_v3,
)


SMALL_TEST_OUTCOME_COUNTS = {"WIN": 2, "LOSS": 2, "TIMEOUT": 2}


class PredictOnlyHGB(HistGradientBoostingClassifier):
    def __init__(self, probability: float = 0.6):
        super().__init__(random_state=42)
        self.probability = probability

    def predict_proba(self, X):
        positive = np.full(len(X), self.probability, dtype=float)
        return np.column_stack([1.0 - positive, positive])


def _features(count: int = 608) -> list[str]:
    if count < len(EXPECTED_FIRST_10_FEATURES) + len(EXPECTED_LAST_8_REGIME_FEATURES):
        return [f"feature_{idx:03d}" for idx in range(count)]

    filler_count = count - len(EXPECTED_FIRST_10_FEATURES) - len(
        EXPECTED_LAST_8_REGIME_FEATURES
    )
    filler = [f"feature_{idx:03d}" for idx in range(10, 10 + filler_count)]
    return EXPECTED_FIRST_10_FEATURES + filler + EXPECTED_LAST_8_REGIME_FEATURES


def _write_schema(path: Path, features: list[str]) -> None:
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_model(path: Path, probability: float = 0.6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(PredictOnlyHGB(probability=probability), path)


def _write_model_metadata(
    path: Path,
    *,
    model_version: str = MODEL_VERSION,
    model_family: str = MODEL_FAMILY,
    test_data_used: bool = False,
    feature_count: int = 608,
) -> None:
    metadata = {
        "model_version": model_version,
        "model_alias": MODEL_ALIAS,
        "model_family": model_family,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "training_source_csv": str(FORBIDDEN_TRAIN_CSV),
        "forbidden_test_csv": str(DEFAULT_TEST_CSV),
        "train_row_count": 12,
        "feature_count": feature_count,
        "min_train_sample_date": "2021-09-13",
        "max_train_sample_date": "2025-07-08",
        "train_outcome_counts": {"WIN": 120505, "LOSS": 228899, "TIMEOUT": 17667},
        "label_encoding": LABEL_ENCODING,
        "train_only": True,
        "test_data_used": test_data_used,
        "old_model_loaded": False,
        "old_schema_loaded": False,
        "feature_schema_source": "train_csv_header",
        "feature_schema_match": True,
        "split_metadata_validated": True,
        "db_mutation": False,
        "deployed": False,
        "champion_selected": False,
    }
    path.write_text(json.dumps(metadata), encoding="utf-8")


def _write_split_meta(
    path: Path,
    *,
    leakage_safe: bool = True,
    feature_count: int = 608,
    test_row_count: int = 6,
) -> None:
    meta = {
        "dataset_version": SPLIT_VERSION,
        "source_dataset_version": DATASET_VERSION,
        "train_row_count": 12,
        "test_row_count": test_row_count,
        "total_eligible_row_count": 18,
        "feature_count": feature_count,
        "expected_feature_count": feature_count,
        "cutoff_date": "2025-07-09",
        "max_train_sample_date": "2025-07-08",
        "min_test_sample_date": "2025-07-09",
        "sample_date_overlap_count": 0,
        "leakage_safe": leakage_safe,
    }
    path.write_text(json.dumps(meta), encoding="utf-8")


def _write_test_csv(
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
        "2025-07-09",
        "2025-07-09",
        "2025-07-10",
        "2025-07-11",
        "2025-07-12",
        "2026-05-18",
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
    pd.DataFrame(rows, columns=metadata_columns + features).to_csv(path, index=False)


def _paths(tmp_path: Path):
    model_dir = tmp_path / "models" / MODEL_VERSION
    split_dir = tmp_path / "exports" / SPLIT_VERSION
    output_dir = tmp_path / "evaluations" / MODEL_VERSION
    model_path = model_dir / "model.joblib"
    schema_path = model_dir / "feature_schema.json"
    model_metadata_path = model_dir / "model_metadata.json"
    test_path = split_dir / "test.csv"
    split_meta_path = split_dir / "split_meta.json"
    model_dir.mkdir(parents=True)
    split_dir.mkdir(parents=True)
    return model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir


def _build_success_env(tmp_path: Path):
    features = _features()
    model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = _paths(
        tmp_path
    )
    _write_model(model_path)
    _write_schema(schema_path, features)
    _write_model_metadata(model_metadata_path)
    _write_test_csv(test_path, features)
    _write_split_meta(split_meta_path)
    return features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir


def _run_success(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    metrics, metadata = score_timesplit_varaha_v3(
        model_path=model_path,
        schema_path=schema_path,
        model_metadata_path=model_metadata_path,
        test_csv_path=test_path,
        split_meta_json=split_meta_path,
        output_dir=output_dir,
        expected_train_rows=12,
        expected_test_rows=6,
        expected_total_rows=18,
        expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
    )
    return metrics, metadata, output_dir


def test_constants_point_to_varaha_3_v3_paths():
    assert MODEL_VERSION == "stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
    assert MODEL_ALIAS == "Varaha 3"
    assert MODEL_FAMILY == "HistGradientBoostingClassifier"
    assert SPLIT_VERSION == "timesplit_regime_v3"
    assert DATASET_VERSION == "stock_opportunity_ohlcv_regime_v3"
    assert DEFAULT_MODEL_DIR == Path("/app/data/models/stock_opportunity_ohlcv_regime_timesplit_varaha_v3")
    assert DEFAULT_MODEL_PATH == DEFAULT_MODEL_DIR / "model.joblib"
    assert DEFAULT_SCHEMA_PATH == DEFAULT_MODEL_DIR / "feature_schema.json"
    assert DEFAULT_MODEL_METADATA_PATH == DEFAULT_MODEL_DIR / "model_metadata.json"
    assert DEFAULT_TEST_CSV == Path("/app/data/exports/timesplit_regime_v3/test.csv")
    assert FORBIDDEN_TRAIN_CSV == Path("/app/data/exports/timesplit_regime_v3/train.csv")
    assert DEFAULT_SPLIT_META_JSON == Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
    assert DEFAULT_OUTPUT_DIR == Path(
        "/app/data/evaluations/stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
    )


def test_source_safety_and_joblib_load_usage():
    source = Path(scorer.__file__).read_text(encoding="utf-8")
    assert "timesplit_regime_" + "v2" not in source
    assert (
        "/app/data/models/"
        + "stock_opportunity_hgb_regime_v1"
        + "/feature_schema.json"
        not in source
    )
    assert ".fit" + "(" not in source
    assert "model." + "fit" not in source
    assert "train_timesplit_varaha_v3" not in source
    assert "joblib." + "load" in source


def test_ast_has_no_fit_calls():
    source = Path(scorer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fit_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fit"
    ]
    assert fit_calls == []


def test_protected_model_dirs_include_old_models():
    assert {
        KURMA_1_MODEL_VERSION,
        VARAHA_1_MODEL_VERSION,
        KURMA_2_MODEL_VERSION,
        VARAHA_2_MODEL_VERSION,
        KURMA_3_MODEL_VERSION,
    }.issubset(PROTECTED_MODEL_DIRS)


def test_scorer_rejects_train_csv(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, _, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    train_path = tmp_path / "exports" / SPLIT_VERSION / "train.csv"
    _write_test_csv(train_path, features)

    with pytest.raises(ValueError, match="test.csv"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=train_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_scorer_rejects_wrong_split_parent(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, _, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    wrong_test_path = tmp_path / "exports" / "wrong_split" / "test.csv"
    wrong_test_path.parent.mkdir(parents=True)
    _write_test_csv(wrong_test_path, features)

    with pytest.raises(ValueError, match=SPLIT_VERSION):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=wrong_test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_scorer_rejects_model_dir_not_named_varaha_3(tmp_path: Path):
    features, _, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    wrong_model_path = tmp_path / "models" / "unexpected_model" / "model.joblib"
    _write_model(wrong_model_path)

    with pytest.raises(ValueError, match=MODEL_VERSION):
        score_timesplit_varaha_v3(
            model_path=wrong_model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )
    assert features[:10] == EXPECTED_FIRST_10_FEATURES


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
def test_scorer_rejects_old_model_dir_paths(tmp_path: Path, protected_dir: str):
    _, _, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    old_model_path = tmp_path / "models" / protected_dir / "model.joblib"
    _write_model(old_model_path)

    with pytest.raises(ValueError, match="protected old model dir"):
        score_timesplit_varaha_v3(
            model_path=old_model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_model_metadata_is_validated(tmp_path: Path):
    metrics, metadata, _ = _run_success(tmp_path)

    assert metadata["model_metadata_validated"] is True
    assert metadata["model_version"] == MODEL_VERSION
    assert metrics["feature_count"] == 608


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_version", "wrong_model", "model metadata validation failed"),
        ("model_family", "LogisticRegression", "model metadata validation failed"),
        ("test_data_used", True, "model metadata validation failed"),
    ],
)
def test_model_metadata_mismatches_are_rejected(tmp_path: Path, field, value, message):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    kwargs = {field: value}
    _write_model_metadata(model_metadata_path, **kwargs)

    with pytest.raises(ValueError, match=message):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_split_metadata_is_validated(tmp_path: Path):
    _, metadata, _ = _run_success(tmp_path)
    assert metadata["split_metadata_validated"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leakage_safe", False),
        ("feature_count", 607),
        ("test_row_count", 7),
    ],
)
def test_split_metadata_mismatches_are_rejected(tmp_path: Path, field, value):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    kwargs = {field: value}
    _write_split_meta(split_meta_path, **kwargs)

    with pytest.raises(ValueError, match="locked v3 leakage-safe split"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_wrong_first_metadata_columns_are_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(
        test_path,
        features,
        metadata_columns=["sample_date", "symbol", "outcome"],
    )

    with pytest.raises(ValueError, match="First three columns"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_wrong_feature_count_is_rejected(tmp_path: Path):
    model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = _paths(
        tmp_path
    )
    features = _features(607)
    _write_model(model_path)
    _write_schema(schema_path, features)
    _write_model_metadata(model_metadata_path)
    _write_split_meta(split_meta_path)
    _write_test_csv(test_path, features)

    with pytest.raises(ValueError, match="Expected 608 features"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_schema_mismatch_is_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    swapped_schema = features.copy()
    swapped_schema[10], swapped_schema[11] = swapped_schema[11], swapped_schema[10]
    _write_schema(schema_path, swapped_schema)

    with pytest.raises(ValueError, match="Feature schema does not match"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_missing_first_10_v3_features_are_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    features[0] = "not_c00_open_rel"
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features)

    with pytest.raises(ValueError, match="candle anatomy"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_missing_last_8_regime_features_are_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    features[-1] = "not_stock_breakout_while_market_weak"
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features)

    with pytest.raises(ValueError, match="regime features"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_test_dates_before_cutoff_are_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(
        test_path,
        features,
        sample_dates=[
            "2025-07-08",
            "2025-07-09",
            "2025-07-10",
            "2025-07-11",
            "2025-07-12",
            "2026-05-18",
        ],
    )

    with pytest.raises(ValueError, match="sample_date < 2025-07-09"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


@pytest.mark.parametrize(
    ("sample_dates", "message"),
    [
        (
            ["2025-07-10", "2025-07-10", "2025-07-11", "2025-07-12", "2025-07-13", "2026-05-18"],
            "Min test sample_date",
        ),
        (
            ["2025-07-09", "2025-07-09", "2025-07-10", "2025-07-11", "2025-07-12", "2026-05-17"],
            "Max test sample_date",
        ),
    ],
)
def test_wrong_min_or_max_test_date_is_rejected(tmp_path: Path, sample_dates, message):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(test_path, features, sample_dates=sample_dates)

    with pytest.raises(ValueError, match=message):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_duplicate_symbol_sample_date_rows_are_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(
        test_path,
        features,
        symbols=["DUP", "DUP", "SYM002", "SYM003", "SYM004", "SYM005"],
        sample_dates=[
            "2025-07-09",
            "2025-07-09",
            "2025-07-10",
            "2025-07-11",
            "2025-07-12",
            "2026-05-18",
        ],
    )

    with pytest.raises(ValueError, match="Duplicate symbol\\+sample_date"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_unsupported_outcome_is_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(
        test_path,
        features,
        outcomes=["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN", "LOSS"],
    )

    with pytest.raises(ValueError, match="unsupported outcomes"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_missing_required_outcome_is_rejected(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(test_path, features, outcomes=["WIN", "LOSS", "WIN", "LOSS", "WIN", "LOSS"])

    with pytest.raises(ValueError, match="missing required outcome"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts={"WIN": 3, "LOSS": 3, "TIMEOUT": 0},
        )


def test_wrong_outcome_counts_are_rejected(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )

    with pytest.raises(ValueError, match="Test outcome counts do not match"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts={"WIN": 3, "LOSS": 2, "TIMEOUT": 1},
        )


@pytest.mark.parametrize("feature_value, message", [(np.nan, "NaN"), (np.inf, "Infinite")])
def test_nan_or_infinite_feature_values_are_rejected(tmp_path: Path, feature_value, message):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_test_csv(test_path, features, feature_value=feature_value)

    with pytest.raises(ValueError, match=message):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_loaded_model_must_be_hgb(tmp_path: Path):
    metrics, _, _ = _run_success(tmp_path)
    assert metrics["predicted_positive_count"] == 6


def test_non_hgb_model_is_rejected(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    joblib.dump({"not": "a model"}, model_path)

    with pytest.raises(ValueError, match="HistGradientBoostingClassifier"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_output_files_predictions_metrics_and_metadata_are_written(tmp_path: Path):
    metrics, metadata, output_dir = _run_success(tmp_path)
    written_metadata = json.loads((output_dir / "score_metadata.json").read_text())
    written_metrics = json.loads((output_dir / "evaluation_metrics.json").read_text())
    predictions = pd.read_csv(output_dir / "test_predictions.csv")

    assert set(path.name for path in output_dir.iterdir()) == {
        "test_predictions.csv",
        "evaluation_metrics.json",
        "score_metadata.json",
    }
    assert list(predictions.columns) == [
        "symbol",
        "sample_date",
        "outcome",
        "target",
        "win_probability",
        "predicted_label",
    ]

    for key in [
        "row_count",
        "feature_count",
        "outcome_counts",
        "positive_label_rate",
        "classification_threshold",
        "predicted_positive_count",
        "predicted_positive_rate",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "roc_auc",
        "confusion_matrix",
        "mvp_precision_threshold",
        "mvp_precision_gate_met",
        "mvp_gate_definition",
    ]:
        assert key in metrics
        assert key in written_metrics

    assert metrics["mvp_precision_threshold"] == MVP_PRECISION_THRESHOLD
    assert metrics["mvp_precision_gate_met"] is False
    assert metrics["mvp_gate_definition"] == MVP_GATE_DEFINITION
    assert written_metrics["classification_threshold"] == 0.5

    for payload in [metadata, written_metadata]:
        assert payload["test_only"] is True
        assert payload["train_data_used"] is False
        assert payload["db_mutation"] is False
        assert payload["deployed"] is False
        assert payload["champion_selected"] is False
        assert payload["feature_count"] == 608
        assert payload["split_version"] == SPLIT_VERSION
        assert payload["model_metadata_validated"] is True
        assert payload["split_metadata_validated"] is True
        assert payload["mvp_precision_threshold"] == MVP_PRECISION_THRESHOLD
        assert payload["mvp_precision_gate_met"] is False
        assert payload["mvp_gate_definition"] == MVP_GATE_DEFINITION


def test_output_dir_with_unexpected_files_is_rejected(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    output_dir.mkdir(parents=True)
    (output_dir / "unexpected.txt").write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected files"):
        score_timesplit_varaha_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_load_feature_schema_rejects_metadata_columns(tmp_path: Path):
    schema_path = tmp_path / "feature_schema.json"
    _write_schema(schema_path, ["symbol"] + _features(607))

    with pytest.raises(ValueError, match="metadata columns"):
        load_feature_schema(schema_path)
