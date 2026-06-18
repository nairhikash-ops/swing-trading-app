# backend/tests/test_score_latest_hgb_regime.py
"""Tests for score_latest_hgb_regime.py (V1.25).

All tests use a real temporary directory and a minimal in-memory or
temp-file HGB model + dataset so no real /app/data files are touched.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from joblib import dump
from sklearn.ensemble import HistGradientBoostingClassifier

from app.scripts.score_latest_hgb_regime import score, _resolve_sample_date


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FEATURES = ["f1", "f2"]
DATES = ["2026-05-15", "2026-05-18", "2026-05-21"]
SYMBOLS = ["AAA", "BBB", "CCC"]


def _make_dataset_csv(path: Path, dates: list[str] = DATES) -> None:
    """Write a minimal fake ML dataset CSV with multiple sample_dates."""
    rows = []
    for date in dates:
        for sym in SYMBOLS:
            rows.append({"symbol": sym, "sample_date": date, "f1": 0.1, "f2": 0.2, "outcome": "WIN"})
    pd.DataFrame(rows).to_csv(path, index=False)


def _make_model_dir(model_root: Path) -> None:
    """Write a tiny fitted HGB model and feature_schema.json."""
    model_root.mkdir(parents=True, exist_ok=True)

    # Train a trivial model
    X = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
    y = np.array([1, 0, 1])
    clf = HistGradientBoostingClassifier(max_iter=5, random_state=42)
    clf.fit(X, y)
    dump(clf, model_root / "model.joblib")

    schema = {"features": FEATURES}
    (model_root / "feature_schema.json").write_text(json.dumps(schema))


@pytest.fixture
def scoring_env(tmp_path):
    """Set up a complete scoring environment: dataset CSV, model dir, exports dir."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    model_root = tmp_path / "models" / "stock_opportunity_hgb_regime_v1"

    dataset_csv = exports_dir / "ml_dataset_ohlcv_regime_v1.csv"
    _make_dataset_csv(dataset_csv)
    _make_model_dir(model_root)

    return {
        "dataset_csv": dataset_csv,
        "model_root": model_root,
        "exports_dir": exports_dir,
        "ranking_csv": exports_dir / "latest_hgb_regime_rankings.csv",
        "ranking_meta": exports_dir / "latest_hgb_regime_rankings.meta.json",
    }


# ---------------------------------------------------------------------------
# _resolve_sample_date unit tests (pure function, no I/O)
# ---------------------------------------------------------------------------

def _make_df(dates):
    return pd.DataFrame({"sample_date": dates * 3})


class TestResolveSampleDate:
    def test_none_returns_latest(self):
        df = _make_df(["2026-05-15", "2026-05-18", "2026-05-21"])
        result = _resolve_sample_date(df, None)
        assert result == "2026-05-21"

    def test_specific_date_present_is_returned(self):
        df = _make_df(["2026-05-15", "2026-05-18", "2026-05-21"])
        result = _resolve_sample_date(df, "2026-05-15")
        assert result == "2026-05-15"

    def test_missing_date_raises_value_error(self):
        df = _make_df(["2026-05-15", "2026-05-18"])
        with pytest.raises(ValueError, match="not present in the dataset"):
            _resolve_sample_date(df, "2026-06-01")


# ---------------------------------------------------------------------------
# Integration tests: score() function
# ---------------------------------------------------------------------------

class TestScoreSampleDateFlag:
    def test_no_flag_scores_latest_date(self, scoring_env):
        """Without --sample-date, the output CSV contains only the latest date."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
            sample_date=None,
        )
        df_out = pd.read_csv(e["ranking_csv"])
        assert set(df_out["sample_date"].unique()) == {"2026-05-21"}

    def test_flag_filters_to_requested_date(self, scoring_env):
        """With --sample-date 2026-05-15, only rows for that date are output."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
            sample_date="2026-05-15",
        )
        df_out = pd.read_csv(e["ranking_csv"])
        assert set(df_out["sample_date"].unique()) == {"2026-05-15"}

    def test_invalid_date_raises_loudly(self, scoring_env):
        """A date not in the dataset raises ValueError immediately."""
        e = scoring_env
        with pytest.raises(ValueError, match="not present in the dataset"):
            score(
                dataset_csv=e["dataset_csv"],
                model_root=e["model_root"],
                ranking_csv=e["ranking_csv"],
                ranking_meta=e["ranking_meta"],
                exports_dir=e["exports_dir"],
                sample_date="2099-01-01",
            )


class TestArchiveFiles:
    def test_archive_csv_written_to_dated_path(self, scoring_env):
        """Date-stamped archive CSV is created alongside latest files."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
            sample_date="2026-05-18",
        )
        archive_csv = e["exports_dir"] / "hgb_regime_rankings_2026-05-18.csv"
        assert archive_csv.exists(), "Archive CSV must be written"
        df_archive = pd.read_csv(archive_csv)
        assert set(df_archive["sample_date"].unique()) == {"2026-05-18"}

    def test_archive_meta_written_to_dated_path(self, scoring_env):
        """Date-stamped archive meta JSON is created."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
            sample_date="2026-05-18",
        )
        archive_meta = e["exports_dir"] / "hgb_regime_rankings_2026-05-18.meta.json"
        assert archive_meta.exists(), "Archive meta must be written"
        meta = json.loads(archive_meta.read_text())
        assert meta["scored_sample_date"] == "2026-05-18"

    def test_archive_csv_refuses_overwrite(self, scoring_env):
        """If archive CSV already exists, scorer raises FileExistsError."""
        e = scoring_env
        archive_csv = e["exports_dir"] / "hgb_regime_rankings_2026-05-18.csv"
        archive_csv.write_text("pre-existing")   # simulate existing archive
        with pytest.raises(FileExistsError, match="already exists"):
            score(
                dataset_csv=e["dataset_csv"],
                model_root=e["model_root"],
                ranking_csv=e["ranking_csv"],
                ranking_meta=e["ranking_meta"],
                exports_dir=e["exports_dir"],
                sample_date="2026-05-18",
            )

    def test_archive_meta_refuses_overwrite(self, scoring_env):
        """If archive meta already exists, scorer raises FileExistsError."""
        e = scoring_env
        archive_meta = e["exports_dir"] / "hgb_regime_rankings_2026-05-18.meta.json"
        archive_meta.write_text("{}")    # simulate existing archive meta
        with pytest.raises(FileExistsError, match="already exists"):
            score(
                dataset_csv=e["dataset_csv"],
                model_root=e["model_root"],
                ranking_csv=e["ranking_csv"],
                ranking_meta=e["ranking_meta"],
                exports_dir=e["exports_dir"],
                sample_date="2026-05-18",
            )

    def test_latest_files_also_written(self, scoring_env):
        """Latest files are updated in addition to archive files."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
            sample_date="2026-05-15",
        )
        assert e["ranking_csv"].exists(), "Latest CSV must be written"
        assert e["ranking_meta"].exists(), "Latest meta must be written"


class TestOutputSchema:
    def test_output_csv_has_win_probability_column(self, scoring_env):
        """Output CSV must have 'win_probability', not 'win_prob'."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
        )
        df_out = pd.read_csv(e["ranking_csv"])
        assert "win_probability" in df_out.columns, "Column must be 'win_probability'"
        assert "win_prob" not in df_out.columns, "Column 'win_prob' must not exist"

    def test_meta_has_scored_sample_date(self, scoring_env):
        """Meta JSON must contain 'scored_sample_date', not 'scored_date'."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
        )
        meta = json.loads(e["ranking_meta"].read_text())
        assert "scored_sample_date" in meta, "Meta must have 'scored_sample_date'"
        assert "scored_date" not in meta, "'scored_date' is the wrong key name"

    def test_meta_has_is_live_today(self, scoring_env):
        """Meta JSON must contain 'is_live_today' boolean."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
        )
        meta = json.loads(e["ranking_meta"].read_text())
        assert "is_live_today" in meta, "Meta must have 'is_live_today'"
        assert isinstance(meta["is_live_today"], bool)

    def test_meta_has_model_version(self, scoring_env):
        """Meta JSON must contain 'model_version'."""
        e = scoring_env
        score(
            dataset_csv=e["dataset_csv"],
            model_root=e["model_root"],
            ranking_csv=e["ranking_csv"],
            ranking_meta=e["ranking_meta"],
            exports_dir=e["exports_dir"],
        )
        meta = json.loads(e["ranking_meta"].read_text())
        assert meta.get("model_version") == "stock_opportunity_hgb_regime_v1"
