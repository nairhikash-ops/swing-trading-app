import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.scripts import score_timesplit_kurma_v3 as scorer
from app.scripts.score_timesplit_kurma_v3 import (
    DATASET_VERSION,
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_METADATA_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_SPLIT_META_JSON,
    DEFAULT_TEST_CSV,
    FORBIDDEN_TRAIN_CSV,
    KURMA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    MODEL_ALIAS,
    MODEL_FAMILY,
    MODEL_VERSION,
    SPLIT_VERSION,
    VARAHA_1_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
    load_feature_schema,
    score_timesplit_kurma_v3,
)


SMALL_TEST_OUTCOME_COUNTS = {"WIN": 2, "LOSS": 2, "TIMEOUT": 2}


def _features(count: int = 608) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_schema(path: Path, features: list[str]) -> None:
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_model(path: Path, features: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feature_count = len(features)
    scaler = StandardScaler()
    scaler.mean_ = np.zeros(feature_count)
    scaler.scale_ = np.ones(feature_count)
    scaler.var_ = np.ones(feature_count)
    scaler.n_features_in_ = feature_count
    scaler.n_samples_seen_ = np.int64(1)
    scaler.feature_names_in_ = np.array(features, dtype=object)

    lr = LogisticRegression(max_iter=200, random_state=42)
    lr.classes_ = np.array([0, 1])
    lr.coef_ = np.zeros((1, feature_count))
    lr.coef_[0, : min(5, feature_count)] = 0.1
    lr.intercept_ = np.array([0.0])
    lr.n_features_in_ = feature_count

    model = Pipeline(
        [
            ("scaler", scaler),
            ("lr", lr),
        ]
    )
    joblib.dump(model, path)


def _write_model_metadata(path: Path, *, model_alias: str = MODEL_ALIAS, feature_count: int = 608) -> None:
    metadata = {
        "model_version": MODEL_VERSION,
        "model_alias": model_alias,
        "model_family": MODEL_FAMILY,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "training_source_csv": str(FORBIDDEN_TRAIN_CSV),
        "forbidden_test_csv": str(DEFAULT_TEST_CSV),
        "train_row_count": 12,
        "feature_count": feature_count,
        "train_only": True,
        "test_data_used": False,
        "old_model_loaded": False,
        "old_schema_loaded": False,
        "feature_schema_source": "train_csv_header",
        "feature_schema_match": True,
    }
    path.write_text(json.dumps(metadata), encoding="utf-8")


def _write_split_meta(
    path: Path,
    *,
    dataset_version: str = SPLIT_VERSION,
    leakage_safe: bool = True,
    feature_count: int = 608,
) -> None:
    meta = {
        "dataset_version": dataset_version,
        "source_dataset_version": DATASET_VERSION,
        "train_row_count": 12,
        "test_row_count": 6,
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
    feature_value: float = 0.2,
) -> None:
    outcomes = outcomes or ["WIN", "LOSS", "TIMEOUT", "WIN", "LOSS", "TIMEOUT"]
    sample_dates = sample_dates or [
        "2025-07-09",
        "2025-07-09",
        "2025-07-10",
        "2025-07-11",
        "2025-07-12",
        "2025-07-13",
    ]
    symbols = symbols or [f"SYM{row_idx:03d}" for row_idx in range(len(outcomes))]
    rows = []
    for row_idx, outcome in enumerate(outcomes):
        row = {
            "symbol": symbols[row_idx],
            "sample_date": sample_dates[row_idx],
            "outcome": outcome,
        }
        row.update({feature: float(feature_value + row_idx * 0.01) for feature in features})
        rows.append(row)
    pd.DataFrame(rows, columns=["symbol", "sample_date", "outcome"] + features).to_csv(
        path, index=False
    )


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
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_model_metadata(model_metadata_path)
    _write_test_csv(test_path, features)
    _write_split_meta(split_meta_path)
    return features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir


def _run_success(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    metrics, metadata = score_timesplit_kurma_v3(
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


def test_constants_point_to_kurma_3_v3_paths():
    assert MODEL_VERSION == "stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
    assert MODEL_ALIAS == "Kurma 3"
    assert MODEL_FAMILY == "LogisticRegression"
    assert SPLIT_VERSION == "timesplit_regime_v3"
    assert DATASET_VERSION == "stock_opportunity_ohlcv_regime_v3"
    assert DEFAULT_MODEL_DIR == Path("/app/data/models/stock_opportunity_ohlcv_regime_timesplit_kurma_v3")
    assert DEFAULT_MODEL_PATH == DEFAULT_MODEL_DIR / "model.joblib"
    assert DEFAULT_SCHEMA_PATH == DEFAULT_MODEL_DIR / "feature_schema.json"
    assert DEFAULT_MODEL_METADATA_PATH == DEFAULT_MODEL_DIR / "model_metadata.json"
    assert DEFAULT_TEST_CSV == Path("/app/data/exports/timesplit_regime_v3/test.csv")
    assert FORBIDDEN_TRAIN_CSV == Path("/app/data/exports/timesplit_regime_v3/train.csv")
    assert DEFAULT_SPLIT_META_JSON == Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
    assert DEFAULT_OUTPUT_DIR == Path(
        "/app/data/evaluations/stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
    )


def test_scorer_rejects_train_csv(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, _, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    train_path = tmp_path / "exports" / SPLIT_VERSION / "train.csv"
    _write_test_csv(train_path, features)

    with pytest.raises(ValueError, match="test.csv"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_v2_test_csv_path_or_wrong_parent(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, _, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    v2_test_path = tmp_path / "exports" / "timesplit_regime_v2" / "test.csv"
    v2_test_path.parent.mkdir(parents=True)
    _write_test_csv(v2_test_path, features)

    with pytest.raises(ValueError, match="timesplit_regime_v3"):
        score_timesplit_kurma_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=v2_test_path,
            split_meta_json=split_meta_path,
            output_dir=output_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_scorer_requires_608_feature_schema(tmp_path: Path):
    model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = _paths(
        tmp_path
    )
    features = _features(607)
    _write_schema(schema_path, features)
    _write_model_metadata(model_metadata_path, feature_count=608)
    _write_split_meta(split_meta_path)
    _write_test_csv(test_path, features)
    _write_model(model_path, _features())

    with pytest.raises(ValueError, match="Expected 608 features"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_schema_mismatch(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    swapped_schema = features.copy()
    swapped_schema[0], swapped_schema[1] = swapped_schema[1], swapped_schema[0]
    _write_schema(schema_path, swapped_schema)

    with pytest.raises(ValueError, match="Feature schema does not match"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_model_metadata_mismatch(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_model_metadata(model_metadata_path, model_alias="Kurma 2")

    with pytest.raises(ValueError, match="model metadata validation failed"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_split_metadata_mismatch(tmp_path: Path):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    _write_split_meta(split_meta_path, dataset_version="timesplit_regime_v2")

    with pytest.raises(ValueError, match="locked v3 leakage-safe split"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_test_dates_before_cutoff(tmp_path: Path):
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
            "2025-07-13",
        ],
    )

    with pytest.raises(ValueError, match="sample_date < 2025-07-09"):
        score_timesplit_kurma_v3(
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


def test_scorer_rejects_duplicate_symbol_sample_date_rows(tmp_path: Path):
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
            "2025-07-13",
        ],
    )

    with pytest.raises(ValueError, match="Duplicate symbol\\+sample_date"):
        score_timesplit_kurma_v3(
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


def test_scorer_validates_model_is_pipeline_with_scaler_lr(tmp_path: Path):
    features, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )
    bad_model = Pipeline([("scaler", StandardScaler()), ("not_lr", LogisticRegression())])
    joblib.dump(bad_model, model_path)

    with pytest.raises(ValueError, match="pipeline steps"):
        score_timesplit_kurma_v3(
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


def test_scorer_does_not_call_fit_during_scoring(tmp_path: Path, monkeypatch):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, output_dir = (
        _build_success_env(tmp_path)
    )

    def fail_fit(self, *args, **kwargs):
        raise AssertionError("score_timesplit_kurma_v3 must not call fit")

    monkeypatch.setattr(Pipeline, "fit", fail_fit)
    score_timesplit_kurma_v3(
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


def test_scorer_writes_only_prediction_metrics_metadata_files(tmp_path: Path):
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
    assert metrics["row_count"] == 6
    assert written_metrics["feature_count"] == 608
    assert metadata["test_only"] is True
    assert metadata["train_data_used"] is False
    assert metadata["db_mutation"] is False
    assert metadata["deployed"] is False
    assert metadata["champion_selected"] is False
    assert metadata["feature_count"] == 608
    assert metadata["split_version"] == SPLIT_VERSION
    assert metadata["model_metadata_validated"] is True
    assert metadata["split_metadata_validated"] is True
    assert written_metadata["test_only"] is True
    assert written_metadata["train_data_used"] is False
    assert written_metadata["db_mutation"] is False
    assert written_metadata["deployed"] is False
    assert written_metadata["champion_selected"] is False
    assert written_metadata["feature_count"] == 608
    assert written_metadata["split_version"] == SPLIT_VERSION
    assert written_metadata["model_metadata_validated"] is True
    assert written_metadata["split_metadata_validated"] is True


@pytest.mark.parametrize(
    "protected_dir",
    [
        KURMA_1_MODEL_VERSION,
        VARAHA_1_MODEL_VERSION,
        KURMA_2_MODEL_VERSION,
        VARAHA_2_MODEL_VERSION,
    ],
)
def test_scorer_rejects_protected_output_dirs(tmp_path: Path, protected_dir: str):
    _, model_path, schema_path, model_metadata_path, test_path, split_meta_path, _ = (
        _build_success_env(tmp_path)
    )

    with pytest.raises(ValueError, match="protected dir"):
        score_timesplit_kurma_v3(
            model_path=model_path,
            schema_path=schema_path,
            model_metadata_path=model_metadata_path,
            test_csv_path=test_path,
            split_meta_json=split_meta_path,
            output_dir=tmp_path / "evaluations" / protected_dir,
            expected_train_rows=12,
            expected_test_rows=6,
            expected_total_rows=18,
            expected_test_outcome_counts=SMALL_TEST_OUTCOME_COUNTS,
        )


def test_scorer_source_does_not_train_or_reference_old_split_paths():
    source = Path(scorer.__file__).read_text(encoding="utf-8")
    assert ".fit(" not in source
    assert "timesplit_regime_v2" not in source
    assert "ml_dataset_ohlcv_regime_v1" not in source
    assert "stock_opportunity_hgb_regime_v1/feature_schema.json" not in source
    assert "DEFAULT_TRAIN_CSV" not in source


def test_load_feature_schema_rejects_metadata_columns(tmp_path: Path):
    schema_path = tmp_path / "feature_schema.json"
    _write_schema(schema_path, ["symbol"] + _features(607))

    with pytest.raises(ValueError, match="metadata columns"):
        load_feature_schema(schema_path)
