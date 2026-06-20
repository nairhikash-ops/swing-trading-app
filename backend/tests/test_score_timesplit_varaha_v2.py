import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.scripts.score_timesplit_varaha_v2 import (
    MODEL_VERSION,
    score_timesplit_varaha_v2,
)


def _features(count: int = 308) -> list[str]:
    return [f"feature_{idx:03d}" for idx in range(count)]


def _write_schema(path, features: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(features), encoding="utf-8")


def _write_model(path, features: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    labels = []
    for idx in range(12):
        label = 1 if idx % 2 == 0 else 0
        rows.append({feature: float(label + (idx * 0.001)) for feature in features})
        labels.append(label)
    X = pd.DataFrame(rows, columns=features)
    y = np.array(labels)
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=200, random_state=42)),
        ]
    )
    model.fit(X, y)
    joblib.dump(model, path)


def _write_test_csv(
    path,
    features: list[str],
    *,
    outcomes: list[str] | None = None,
    sample_dates: list[str] | None = None,
    feature_value=None,
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
    model_dir = tmp_path / "models" / MODEL_VERSION
    exports_dir = tmp_path / "exports" / "timesplit_regime_v2"
    output_dir = tmp_path / "evaluations" / MODEL_VERSION
    model_path = model_dir / "model.joblib"
    schema_path = model_dir / "feature_schema.json"
    test_path = exports_dir / "test.csv"
    return model_path, schema_path, test_path, output_dir


def _build_success_env(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features)
    return features, model_path, schema_path, test_path, output_dir


def _run_success(tmp_path):
    _, model_path, schema_path, test_path, output_dir = _build_success_env(tmp_path)
    metrics, metadata = score_timesplit_varaha_v2(
        model_path=model_path,
        schema_path=schema_path,
        test_csv_path=test_path,
        output_dir=output_dir,
        expected_test_rows=6,
    )
    return metrics, metadata, output_dir


def _sha256(path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def test_missing_model_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features)

    with pytest.raises(FileNotFoundError, match="Model not found"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_missing_schema_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_test_csv(test_path, features)

    with pytest.raises(FileNotFoundError, match="Feature schema not found"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_missing_test_csv_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)

    with pytest.raises(FileNotFoundError, match="Test CSV not found"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_train_csv_path_is_rejected_before_read(tmp_path, monkeypatch):
    features = _features()
    model_path, schema_path, _, output_dir = _paths(tmp_path)
    train_path = tmp_path / "exports" / "timesplit_regime_v2" / "train.csv"
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_test_csv(train_path, features)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("train.csv must be rejected before any CSV read")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="Refusing to score train CSV"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=train_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_wrong_feature_count_is_rejected(tmp_path):
    schema_features = _features()
    test_features = schema_features[:-1]
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, schema_features)
    _write_schema(schema_path, schema_features)
    _write_test_csv(test_path, test_features)

    with pytest.raises(ValueError, match="Expected 308 feature columns"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_feature_schema_mismatch_is_rejected(tmp_path):
    schema_features = _features()
    test_features = schema_features.copy()
    test_features[7] = "unexpected_feature_007"
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, schema_features)
    _write_schema(schema_path, schema_features)
    _write_test_csv(test_path, test_features)

    with pytest.raises(ValueError, match="Feature schema does not match"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_unsupported_outcome_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_test_csv(
        test_path,
        features,
        outcomes=["WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "WIN", "LOSS"],
    )

    with pytest.raises(ValueError, match="unsupported outcomes"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_missing_required_outcome_class_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features, outcomes=["WIN", "LOSS", "WIN", "LOSS", "WIN", "LOSS"])

    with pytest.raises(ValueError, match="missing required outcome classes"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_unsafe_test_date_before_cutoff_is_rejected(tmp_path):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)
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
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


@pytest.mark.parametrize("feature_value, message", [(np.nan, "NaN"), (np.inf, "Infinite")])
def test_nan_or_infinite_feature_is_rejected(tmp_path, feature_value, message):
    features = _features()
    model_path, schema_path, test_path, output_dir = _paths(tmp_path)
    _write_model(model_path, features)
    _write_schema(schema_path, features)
    _write_test_csv(test_path, features, feature_value=feature_value)

    with pytest.raises(ValueError, match=message):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=output_dir,
            expected_test_rows=6,
        )


def test_output_directory_outside_evaluations_is_rejected(tmp_path):
    features, model_path, schema_path, test_path, _ = _build_success_env(tmp_path)
    assert features

    with pytest.raises(ValueError, match="evaluations directory"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=tmp_path / MODEL_VERSION,
            expected_test_rows=6,
        )

    with pytest.raises(ValueError, match="model directory"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=tmp_path / "models" / "unsafe" / "evaluations" / MODEL_VERSION,
            expected_test_rows=6,
        )


def test_output_directory_basename_mismatch_is_rejected(tmp_path):
    _, model_path, schema_path, test_path, _ = _build_success_env(tmp_path)

    with pytest.raises(ValueError, match="Expected directory name"):
        score_timesplit_varaha_v2(
            model_path=model_path,
            schema_path=schema_path,
            test_csv_path=test_path,
            output_dir=tmp_path / "evaluations" / "wrong_model",
            expected_test_rows=6,
        )


def test_db_path_files_are_not_touched(tmp_path):
    main_db = tmp_path / "dhan_auth.sqlite3"
    shadow_db = tmp_path / "shadow_tracking.sqlite3"
    main_db.write_bytes(b"main-db-before")
    shadow_db.write_bytes(b"shadow-db-before")
    before = {
        main_db: (_sha256(main_db), main_db.stat().st_mtime_ns),
        shadow_db: (_sha256(shadow_db), shadow_db.stat().st_mtime_ns),
    }

    _run_success(tmp_path / "scoring")

    assert before[main_db] == (_sha256(main_db), main_db.stat().st_mtime_ns)
    assert before[shadow_db] == (_sha256(shadow_db), shadow_db.stat().st_mtime_ns)


def test_metadata_records_offline_no_mutation_flags(tmp_path):
    _, metadata, output_dir = _run_success(tmp_path)
    written_metadata = json.loads((output_dir / "score_metadata.json").read_text())

    assert metadata["train_data_used"] is False
    assert metadata["db_mutation"] is False
    assert metadata["deployed"] is False
    assert metadata["test_only"] is True
    assert written_metadata["train_data_used"] is False
    assert written_metadata["db_mutation"] is False
    assert written_metadata["deployed"] is False
    assert written_metadata["test_only"] is True


def test_predictions_metrics_and_metadata_are_written_on_success(tmp_path):
    metrics, metadata, output_dir = _run_success(tmp_path)

    predictions = pd.read_csv(output_dir / "test_predictions.csv")
    written_metrics = json.loads((output_dir / "evaluation_metrics.json").read_text())
    written_metadata = json.loads((output_dir / "score_metadata.json").read_text())

    assert len(predictions) == 6
    assert list(predictions.columns) == [
        "symbol",
        "sample_date",
        "outcome",
        "target",
        "win_probability",
        "predicted_label",
    ]
    assert metrics["row_count"] == 6
    assert written_metrics["row_count"] == 6
    assert written_metrics["feature_count"] == 308
    assert written_metrics["classification_threshold"] == 0.5
    assert written_metrics["predicted_positive_count_at_threshold_0_5"] == written_metrics[
        "predicted_positive_count"
    ]
    assert set(written_metrics["confusion_matrix"]) == {
        "true_negative",
        "false_positive",
        "false_negative",
        "true_positive",
    }
    assert metadata["test_row_count"] == 6
    assert written_metadata["model_version"] == MODEL_VERSION
    assert written_metadata["model_alias"] == "Varaha 2"
    assert written_metadata["model_family"] == "HistGradientBoostingClassifier"
    assert written_metadata["forbidden_train_csv"].endswith("/train.csv")
    assert written_metadata["feature_schema_match"] is True


def test_train_csv_is_never_read(tmp_path, monkeypatch):
    features, model_path, schema_path, test_path, output_dir = _build_success_env(tmp_path)
    train_path = tmp_path / "exports" / "timesplit_regime_v2" / "train.csv"
    _write_test_csv(train_path, features)

    original_read_csv = pd.read_csv
    read_paths = []

    def tracking_read_csv(path, *args, **kwargs):
        read_paths.append(str(path))
        if Path(path).name == "train.csv":
            raise AssertionError("train.csv must not be read")
        return original_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", tracking_read_csv)

    score_timesplit_varaha_v2(
        model_path=model_path,
        schema_path=schema_path,
        test_csv_path=test_path,
        output_dir=output_dir,
        expected_test_rows=6,
    )

    assert str(train_path) not in read_paths
    assert read_paths == [str(test_path), str(test_path)]
