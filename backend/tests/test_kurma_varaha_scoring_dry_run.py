from __future__ import annotations

import inspect
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from app.matsya import kurma_varaha_scoring_dry_run as scorer
from app.matsya.kurma_varaha_artifacts import (
    DATASET_VERSION,
    FEATURE_NAMES,
    KURMA_3_MODEL_VERSION,
    MODEL_FEATURE_COUNT,
    SPLIT_VERSION,
    VARAHA_3_MODEL_VERSION,
)
from app.matsya.kurma_varaha_scoring_dry_run import score_kurma_varaha_dry_run


class SyntheticKurmaModel(LogisticRegression):
    proba_calls = 0
    direct_label_calls = 0

    def predict_proba(self, features):
        type(self).proba_calls += 1
        values = np.linspace(0.20, 0.80, len(features))
        return np.column_stack([1.0 - values, values])

    def __getattribute__(self, name: str):
        if name == "pre" + "dict":
            type(self).direct_label_calls += 1
            raise AssertionError("predict must not be called")
        return super().__getattribute__(name)


class SyntheticVarahaModel(HistGradientBoostingClassifier):
    proba_calls = 0

    def predict_proba(self, features):
        type(self).proba_calls += 1
        values = np.linspace(0.10, 0.40, len(features))
        return np.column_stack([1.0 - values, values])


class BadProbabilityModel(LogisticRegression):
    def predict_proba(self, features):
        return np.array([0.5] * len(features))


def _reset_model_counters() -> None:
    SyntheticKurmaModel.proba_calls = 0
    SyntheticKurmaModel.direct_label_calls = 0
    SyntheticVarahaModel.proba_calls = 0


def _write_artifact_dir(
    artifact_dir: Path,
    *,
    model: object,
    model_version: str,
    model_alias: str,
    model_family: str,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_dir / "model.joblib")
    (artifact_dir / "feature_schema.json").write_text(json.dumps(FEATURE_NAMES), encoding="utf-8")
    metadata = {
        "model_version": model_version,
        "model_alias": model_alias,
        "model_family": model_family,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "feature_count": str(MODEL_FEATURE_COUNT),
        "train_only": True,
        "test_data_used": False,
    }
    (artifact_dir / "model_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _write_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_artifact_dir(
        kurma_dir,
        model=SyntheticKurmaModel(),
        model_version=KURMA_3_MODEL_VERSION,
        model_alias="Kurma 3",
        model_family="LogisticRegression",
    )
    _write_artifact_dir(
        varaha_dir,
        model=SyntheticVarahaModel(),
        model_version=VARAHA_3_MODEL_VERSION,
        model_alias="Varaha 3",
        model_family="HistGradientBoostingClassifier",
    )
    return kurma_dir, varaha_dir


def _snapshot_frame(row_count: int = 3) -> pd.DataFrame:
    rows = []
    for index in range(row_count):
        row = {
            "symbol": f"SYM{index:03d}",
            "sample_date": "2026-06-26",
        }
        row.update({feature: float(index + 1) for feature in FEATURE_NAMES})
        rows.append(row)
    return pd.DataFrame(rows, columns=["symbol", "sample_date"] + FEATURE_NAMES)


def _write_snapshot(path: Path, frame: pd.DataFrame | None = None) -> Path:
    (frame if frame is not None else _snapshot_frame()).to_csv(path, index=False)
    return path


def _run_success(tmp_path: Path):
    _reset_model_counters()
    snapshot_path = _write_snapshot(tmp_path / "snapshot.csv")
    kurma_dir, varaha_dir = _write_artifacts(tmp_path)
    output_path = tmp_path / "dry-run.json"

    report = score_kurma_varaha_dry_run(
        snapshot_csv=snapshot_path,
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
        output_path=output_path,
    )
    return report, output_path


def test_missing_snapshot_path_fails_closed(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_artifacts(tmp_path)

    report = score_kurma_varaha_dry_run(
        snapshot_csv=tmp_path / "missing.csv",
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
        output_path=tmp_path / "dry-run.json",
    )

    assert report.status == "invalid"
    assert "snapshot csv missing" in report.failure_reason.lower()


def test_missing_required_feature_column_fails_closed(tmp_path: Path) -> None:
    frame = _snapshot_frame().drop(columns=[FEATURE_NAMES[0]])
    snapshot_path = _write_snapshot(tmp_path / "snapshot.csv", frame)
    kurma_dir, varaha_dir = _write_artifacts(tmp_path)

    report = score_kurma_varaha_dry_run(
        snapshot_csv=snapshot_path,
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
        output_path=tmp_path / "dry-run.json",
    )

    assert report.status == "invalid"
    assert "missing feature columns" in report.failure_reason.lower()


def test_wrong_feature_order_fails_closed(tmp_path: Path) -> None:
    frame = _snapshot_frame()
    columns = list(frame.columns)
    first = columns.index(FEATURE_NAMES[0])
    second = columns.index(FEATURE_NAMES[1])
    columns[first], columns[second] = columns[second], columns[first]
    snapshot_path = _write_snapshot(tmp_path / "snapshot.csv", frame.loc[:, columns])
    kurma_dir, varaha_dir = _write_artifacts(tmp_path)

    report = score_kurma_varaha_dry_run(
        snapshot_csv=snapshot_path,
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
        output_path=tmp_path / "dry-run.json",
    )

    assert report.status == "invalid"
    assert "feature order" in report.failure_reason.lower()


def test_nan_or_infinite_feature_values_fail_closed(tmp_path: Path) -> None:
    for bad_value in [np.nan, np.inf]:
        frame = _snapshot_frame()
        frame.loc[0, FEATURE_NAMES[0]] = bad_value
        snapshot_path = _write_snapshot(tmp_path / f"snapshot-{bad_value}.csv", frame)
        kurma_dir, varaha_dir = _write_artifacts(tmp_path / str(bad_value))

        report = score_kurma_varaha_dry_run(
            snapshot_csv=snapshot_path,
            kurma_artifact_dir=kurma_dir,
            varaha_artifact_dir=varaha_dir,
            output_path=tmp_path / f"dry-run-{bad_value}.json",
        )

        assert report.status == "invalid"
        assert "feature values" in report.failure_reason.lower()


def test_registry_or_model_validation_failure_prevents_scoring(tmp_path: Path) -> None:
    _reset_model_counters()
    snapshot_path = _write_snapshot(tmp_path / "snapshot.csv")
    kurma_dir, _ = _write_artifacts(tmp_path)

    report = score_kurma_varaha_dry_run(
        snapshot_csv=snapshot_path,
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=tmp_path / "missing-varaha",
        output_path=tmp_path / "dry-run.json",
    )

    assert report.status == "invalid"
    assert SyntheticKurmaModel.proba_calls == 0


def test_scoring_calls_predict_proba_on_both_models(tmp_path: Path) -> None:
    report, _ = _run_success(tmp_path)

    assert report.status == "valid"
    assert SyntheticKurmaModel.proba_calls == 1
    assert SyntheticVarahaModel.proba_calls == 1


def test_scoring_does_not_call_direct_label_method(tmp_path: Path) -> None:
    report, _ = _run_success(tmp_path)

    assert report.status == "valid"
    assert SyntheticKurmaModel.direct_label_calls == 0


def test_output_contains_kurma_and_varaha_probabilities(tmp_path: Path) -> None:
    report, output_path = _run_success(tmp_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert report.status == "valid"
    assert "kurma_prob" in payload["rows"][0]
    assert "varaha_prob" in payload["rows"][0]


def test_output_does_not_contain_action_fields(tmp_path: Path) -> None:
    _, output_path = _run_success(tmp_path)
    payload_text = output_path.read_text(encoding="utf-8").lower()

    for forbidden in ["selected", "buy", "or" + "der", "demo", "locked" + "_pocket"]:
        assert forbidden not in payload_text


def test_output_row_count_matches_input_row_count(tmp_path: Path) -> None:
    report, payload_path = _run_success(tmp_path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    assert report.row_count == 3
    assert payload["row_count"] == 3
    assert len(payload["rows"]) == 3


def test_output_is_marked_dry_run_true(tmp_path: Path) -> None:
    report, payload_path = _run_success(tmp_path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    assert report.dry_run is True
    assert payload["dry_run"] is True


def test_no_threshold_selection_rule_is_applied(tmp_path: Path) -> None:
    report, _ = _run_success(tmp_path)

    assert report.status == "valid"
    assert len(report.rows) == 3
    assert all("selection" not in row for row in report.rows)


def test_probability_shape_mismatch_fails_closed(tmp_path: Path) -> None:
    snapshot_path = _write_snapshot(tmp_path / "snapshot.csv")
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_artifact_dir(
        kurma_dir,
        model=BadProbabilityModel(),
        model_version=KURMA_3_MODEL_VERSION,
        model_alias="Kurma 3",
        model_family="LogisticRegression",
    )
    _write_artifact_dir(
        varaha_dir,
        model=SyntheticVarahaModel(),
        model_version=VARAHA_3_MODEL_VERSION,
        model_alias="Varaha 3",
        model_family="HistGradientBoostingClassifier",
    )

    report = score_kurma_varaha_dry_run(
        snapshot_csv=snapshot_path,
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
        output_path=tmp_path / "dry-run.json",
    )

    assert report.status == "invalid"
    assert "probability shape unexpected" in report.failure_reason.lower()


def test_no_db_writes_occur_in_source() -> None:
    source = inspect.getsource(scorer).lower()

    for forbidden in ["ins" + "ert ", "up" + "date ", "del" + "ete ", "conn" + "ect("]:
        assert forbidden not in source
