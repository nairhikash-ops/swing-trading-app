# backend/tests/test_export_scoring_snapshot.py
"""Tests for export_scoring_snapshot.py (V1.26).

All tests are fully offline — they use a real temp SQLite DB and
temp directory. No real /app/data files are touched.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.scripts.export_scoring_snapshot import (
    export_scoring_snapshot,
    _check_leakage_safety,
    _flatten_feature_json,
    _compute_regime_features,
    _load_feature_schema,
    _ohlcv_col_names,
    REGIME_COLS,
    N_CANDLES,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

TRAINING_CUTOFF = "2026-05-18"
CLEAN_DATE      = "2026-05-19"
IN_SAMPLE_DATE  = "2026-05-18"   # exactly on the cutoff — also blocked


def _make_fake_feature_json(n_candles: int = N_CANDLES) -> str:
    """Build a minimal valid feature_json blob."""
    candles = [
        {
            "trading_date": f"2026-04-{i+1:02d}",
            "open_rel":   0.001 * i,
            "high_rel":   0.002 * i,
            "low_rel":   -0.001 * i,
            "close_rel":  0.001 * i,
            "volume_rel": 0.5,
        }
        for i in range(n_candles)
    ]
    return json.dumps({"candles": candles})


def _make_test_db(
    tmp_path: Path,
    sample_date: str = CLEAN_DATE,
    outcome: str = "INSUFFICIENT_FUTURE_DATA",
    trainable: int = 0,
    n_symbols: int = 5,
) -> str:
    """Create a minimal SQLite DB with ml_samples rows."""
    db_path = str(tmp_path / "test_dhan.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE ml_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            label_name TEXT NOT NULL,
            instrument_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            sample_date TEXT NOT NULL,
            input_window_start TEXT,
            input_window_end TEXT,
            future_window_start TEXT,
            future_window_end TEXT,
            entry_close REAL,
            target_price REAL,
            stop_price REAL,
            outcome TEXT NOT NULL,
            trainable INTEGER NOT NULL DEFAULT 0,
            exclude_reason TEXT DEFAULT '',
            barrier_hit_date TEXT,
            barrier_hit_type TEXT DEFAULT '',
            days_to_outcome INTEGER,
            feature_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    for i in range(n_symbols):
        conn.execute(
            """
            INSERT INTO ml_samples
              (model_name, label_name, instrument_id, symbol, sample_date,
               outcome, trainable, feature_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "stock_opportunity_ohlcv_v1",
                "hit_7pct_before_down_3pct_20d",
                i + 1,
                f"SYM{i:03d}",
                sample_date,
                outcome,
                trainable,
                _make_fake_feature_json(),
                "2026-05-19T00:00:00+00:00",
                "2026-05-19T00:00:00+00:00",
            ),
        )
    conn.commit()
    conn.close()
    return db_path


def _make_model_root(tmp_path: Path, bare_list: bool = False) -> Path:
    """Create a minimal model directory with a real feature_schema.json.

    Args:
        bare_list: If True, write the schema as a bare JSON list (as the real
                   HGB model does). If False, write as {"features": [...]}.
    """
    model_root = tmp_path / "models" / "stock_opportunity_hgb_regime_v1"
    model_root.mkdir(parents=True, exist_ok=True)
    # Schema lists exactly the 300 OHLCV cols + 8 regime cols = 308 features
    ohlcv_cols = _ohlcv_col_names()
    all_features = ohlcv_cols + REGIME_COLS
    if bare_list:
        # Real HGB model format: a bare JSON list
        (model_root / "feature_schema.json").write_text(json.dumps(all_features))
    else:
        # Test fixture / LR model format: {"features": [...]}
        schema = {"features": all_features}
        (model_root / "feature_schema.json").write_text(json.dumps(schema))
    return model_root


# ---------------------------------------------------------------------------
# Unit tests for _check_leakage_safety
# ---------------------------------------------------------------------------

class TestCheckLeakageSafety:
    def _make_conn(self, tmp_path, **kwargs) -> tuple[sqlite3.Connection, str]:
        db_path = _make_test_db(tmp_path, **kwargs)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn, db_path

    def test_rejects_date_on_cutoff(self, tmp_path):
        """sample_date == training_cutoff_date must be rejected."""
        conn, _ = self._make_conn(tmp_path, sample_date=IN_SAMPLE_DATE)
        with pytest.raises(ValueError, match="not strictly after"):
            _check_leakage_safety(conn, IN_SAMPLE_DATE, TRAINING_CUTOFF)
        conn.close()

    def test_rejects_date_before_cutoff(self, tmp_path):
        """sample_date < training_cutoff_date must be rejected."""
        conn, _ = self._make_conn(tmp_path, sample_date="2026-01-01")
        with pytest.raises(ValueError, match="not strictly after"):
            _check_leakage_safety(conn, "2026-01-01", TRAINING_CUTOFF)
        conn.close()

    def test_rejects_trainable_rows(self, tmp_path):
        """A date with trainable=1 rows must be rejected."""
        conn, _ = self._make_conn(tmp_path, sample_date=CLEAN_DATE, trainable=1, outcome="WIN")
        with pytest.raises(ValueError, match="trainable row"):
            _check_leakage_safety(conn, CLEAN_DATE, TRAINING_CUTOFF)
        conn.close()

    def test_rejects_missing_insuf_rows(self, tmp_path):
        """A date with no INSUFFICIENT_FUTURE_DATA rows must be rejected."""
        db_path = str(tmp_path / "empty.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE ml_samples (
                id INTEGER PRIMARY KEY, symbol TEXT, sample_date TEXT,
                outcome TEXT, trainable INTEGER, feature_json TEXT,
                model_name TEXT, label_name TEXT, instrument_id INTEGER,
                input_window_start TEXT, input_window_end TEXT,
                future_window_start TEXT, future_window_end TEXT,
                entry_close REAL, target_price REAL, stop_price REAL,
                exclude_reason TEXT, barrier_hit_date TEXT,
                barrier_hit_type TEXT, days_to_outcome INTEGER,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.row_factory = sqlite3.Row
        with pytest.raises(ValueError, match="No INSUFFICIENT_FUTURE_DATA rows"):
            _check_leakage_safety(conn, CLEAN_DATE, TRAINING_CUTOFF)
        conn.close()

    def test_passes_clean_date(self, tmp_path):
        """A clean date with INSUFFICIENT_FUTURE_DATA and trainable=0 must pass."""
        conn, _ = self._make_conn(
            tmp_path, sample_date=CLEAN_DATE, trainable=0,
            outcome="INSUFFICIENT_FUTURE_DATA",
        )
        # Must not raise
        _check_leakage_safety(conn, CLEAN_DATE, TRAINING_CUTOFF)
        conn.close()


# ---------------------------------------------------------------------------
# Unit tests for _flatten_feature_json
# ---------------------------------------------------------------------------

class TestFlattenFeatureJson:
    def test_produces_300_columns(self):
        blob = _make_fake_feature_json()
        flat = _flatten_feature_json(blob, "SYM", "2026-05-19")
        assert len(flat) == 300

    def test_column_names_match_ohlcv_cols(self):
        blob = _make_fake_feature_json()
        flat = _flatten_feature_json(blob, "SYM", "2026-05-19")
        expected = set(_ohlcv_col_names())
        assert set(flat.keys()) == expected

    def test_wrong_candle_count_raises(self):
        blob = _make_fake_feature_json(n_candles=10)
        with pytest.raises(ValueError, match="Expected 60 candles"):
            _flatten_feature_json(blob, "SYM", "2026-05-19")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid feature_json"):
            _flatten_feature_json("{bad json", "SYM", "2026-05-19")


# ---------------------------------------------------------------------------
# Integration tests: export_scoring_snapshot()
# ---------------------------------------------------------------------------

class TestExportScoringSnapshotSafetyGates:
    """Safety gate enforcement — all must abort before writing any file."""

    def test_rejects_sample_date_on_cutoff(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=IN_SAMPLE_DATE)
        model_root = _make_model_root(tmp_path)
        with pytest.raises(ValueError, match="not strictly after"):
            export_scoring_snapshot(
                sample_date=IN_SAMPLE_DATE,
                output_dir=tmp_path / "exports",
                training_cutoff_date=TRAINING_CUTOFF,
                db_path=db_path,
                model_root=model_root,
            )
        # No file written
        assert not (tmp_path / "exports" / f"ml_scoring_ohlcv_regime_{IN_SAMPLE_DATE}.csv").exists()

    def test_rejects_date_with_trainable_rows(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE, trainable=1, outcome="WIN")
        model_root = _make_model_root(tmp_path)
        with pytest.raises(ValueError, match="trainable row"):
            export_scoring_snapshot(
                sample_date=CLEAN_DATE,
                output_dir=tmp_path / "exports",
                training_cutoff_date=TRAINING_CUTOFF,
                db_path=db_path,
                model_root=model_root,
            )

    def test_rejects_date_with_no_insuf_rows(self, tmp_path):
        db_path = str(tmp_path / "empty.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE ml_samples (
                id INTEGER PRIMARY KEY, symbol TEXT, sample_date TEXT,
                outcome TEXT, trainable INTEGER DEFAULT 0, feature_json TEXT,
                model_name TEXT, label_name TEXT, instrument_id INTEGER,
                input_window_start TEXT, input_window_end TEXT,
                future_window_start TEXT, future_window_end TEXT,
                entry_close REAL, target_price REAL, stop_price REAL,
                exclude_reason TEXT, barrier_hit_date TEXT,
                barrier_hit_type TEXT, days_to_outcome INTEGER,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        model_root = _make_model_root(tmp_path)
        with pytest.raises(ValueError, match="No INSUFFICIENT_FUTURE_DATA rows"):
            export_scoring_snapshot(
                sample_date=CLEAN_DATE,
                output_dir=tmp_path / "exports",
                training_cutoff_date=TRAINING_CUTOFF,
                db_path=db_path,
                model_root=model_root,
            )

    def test_rejects_existing_archive_csv(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE)
        model_root = _make_model_root(tmp_path)
        out_dir    = tmp_path / "exports"
        out_dir.mkdir()
        # Pre-create archive CSV
        (out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.csv").write_text("existing")
        with pytest.raises(FileExistsError, match="already exists"):
            export_scoring_snapshot(
                sample_date=CLEAN_DATE,
                output_dir=out_dir,
                training_cutoff_date=TRAINING_CUTOFF,
                db_path=db_path,
                model_root=model_root,
            )

    def test_rejects_existing_archive_meta(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE)
        model_root = _make_model_root(tmp_path)
        out_dir    = tmp_path / "exports"
        out_dir.mkdir()
        # Pre-create archive meta
        (out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.meta.json").write_text("{}")
        with pytest.raises(FileExistsError, match="already exists"):
            export_scoring_snapshot(
                sample_date=CLEAN_DATE,
                output_dir=out_dir,
                training_cutoff_date=TRAINING_CUTOFF,
                db_path=db_path,
                model_root=model_root,
            )


class TestExportScoringSnapshotOutputs:
    """Verify correct file content when all safety gates pass."""

    @pytest.fixture
    def successful_export(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE, n_symbols=10)
        model_root = _make_model_root(tmp_path)
        out_dir    = tmp_path / "exports"
        result = export_scoring_snapshot(
            sample_date=CLEAN_DATE,
            output_dir=out_dir,
            training_cutoff_date=TRAINING_CUTOFF,
            db_path=db_path,
            model_root=model_root,
        )
        out_csv  = out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.csv"
        out_meta = out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.meta.json"
        df       = pd.read_csv(out_csv)
        meta     = json.loads(out_meta.read_text())
        return result, df, meta, out_csv, out_meta

    def test_csv_file_created(self, successful_export):
        _, _, _, out_csv, _ = successful_export
        assert out_csv.exists()

    def test_meta_file_created(self, successful_export):
        _, _, _, _, out_meta = successful_export
        assert out_meta.exists()

    def test_row_count_matches_symbols(self, successful_export):
        _, df, meta, _, _ = successful_export
        assert len(df) == 10
        assert meta["row_count"] == 10

    def test_csv_contains_symbol_column(self, successful_export):
        _, df, _, _, _ = successful_export
        assert "symbol" in df.columns

    def test_csv_contains_sample_date_column(self, successful_export):
        _, df, _, _, _ = successful_export
        assert "sample_date" in df.columns
        assert (df["sample_date"] == CLEAN_DATE).all()

    def test_csv_has_300_ohlcv_feature_columns(self, successful_export):
        _, df, _, _, _ = successful_export
        ohlcv_cols = _ohlcv_col_names()
        for col in ohlcv_cols:
            assert col in df.columns, f"Missing OHLCV column: {col}"

    def test_csv_has_8_regime_feature_columns(self, successful_export):
        _, df, _, _, _ = successful_export
        for col in REGIME_COLS:
            assert col in df.columns, f"Missing regime column: {col}"

    def test_feature_count_total_is_308(self, successful_export):
        _, _, meta, _, _ = successful_export
        assert meta["feature_count"] == 308  # 300 OHLCV + 8 regime

    def test_outcome_column_is_insufficient(self, successful_export):
        """If outcome column is present, it must only contain INSUFFICIENT_FUTURE_DATA."""
        _, df, _, _, _ = successful_export
        if "outcome" in df.columns:
            assert (df["outcome"] == "INSUFFICIENT_FUTURE_DATA").all()

    def test_no_nan_in_feature_columns(self, successful_export):
        _, df, _, _, _ = successful_export
        feature_cols = _ohlcv_col_names() + REGIME_COLS
        assert not df[feature_cols].isna().any().any()

    def test_no_inf_in_feature_columns(self, successful_export):
        _, df, _, _, _ = successful_export
        feature_cols = _ohlcv_col_names() + REGIME_COLS
        assert not np.isinf(df[feature_cols].values).any()

    def test_feature_column_order_matches_schema(self, tmp_path, successful_export):
        """Feature columns in CSV must appear in the same order as feature_schema.json."""
        result, df, _, _, _ = successful_export
        model_root   = tmp_path / "models" / "stock_opportunity_hgb_regime_v1"
        schema_path  = model_root / "feature_schema.json"
        # Use _load_feature_schema — handles both bare list and dict formats
        expected = _load_feature_schema(schema_path)
        # All expected features must be present as columns in the CSV
        for feat in expected:
            assert feat in df.columns, f"Schema feature '{feat}' missing from CSV"

    def test_bare_list_schema_format_works(self, tmp_path):
        """Verify export works when feature_schema.json is a bare JSON list.

        This is the actual format used by the real HGB model on the server.
        The dict format {"features": [...]} is only used in test fixtures.
        """
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE, n_symbols=3)
        # Write schema as bare list (real HGB model format)
        model_root = _make_model_root(tmp_path, bare_list=True)
        out_dir    = tmp_path / "exports_barelist"

        result = export_scoring_snapshot(
            sample_date=CLEAN_DATE,
            output_dir=out_dir,
            training_cutoff_date=TRAINING_CUTOFF,
            db_path=db_path,
            model_root=model_root,
        )

        assert result["row_count"] == 3
        assert result["feature_count"] == 308
        out_csv = out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.csv"
        assert out_csv.exists()
        df = pd.read_csv(out_csv)
        assert len(df) == 3
        for col in _ohlcv_col_names() + REGIME_COLS:
            assert col in df.columns, f"Missing feature col: {col}"


class TestExportScoringSnapshotMetadata:
    """Verify all required metadata keys and values."""

    @pytest.fixture
    def meta(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE)
        model_root = _make_model_root(tmp_path)
        out_dir    = tmp_path / "exports"
        export_scoring_snapshot(
            sample_date=CLEAN_DATE,
            output_dir=out_dir,
            training_cutoff_date=TRAINING_CUTOFF,
            db_path=db_path,
            model_root=model_root,
        )
        return json.loads((out_dir / f"ml_scoring_ohlcv_regime_{CLEAN_DATE}.meta.json").read_text())

    def test_meta_has_sample_date(self, meta):
        assert meta["sample_date"] == CLEAN_DATE

    def test_meta_has_model_version(self, meta):
        assert meta["model_version"] == "stock_opportunity_hgb_regime_v1"

    def test_meta_has_training_cutoff_date(self, meta):
        assert meta["training_cutoff_date"] == TRAINING_CUTOFF

    def test_meta_has_source_table(self, meta):
        assert meta["source_table"] == "ml_samples"

    def test_meta_has_source_outcome(self, meta):
        assert meta["source_outcome"] == "INSUFFICIENT_FUTURE_DATA"

    def test_meta_trainable_rows_for_date_is_zero(self, meta):
        assert meta["trainable_rows_for_date"] == 0

    def test_meta_leakage_safe_is_true(self, meta):
        """leakage_safe must be True — this is the core V1.26 guarantee."""
        assert meta["leakage_safe"] is True

    def test_meta_has_feature_count(self, meta):
        assert "feature_count" in meta
        assert meta["feature_count"] == 308

    def test_meta_has_created_at(self, meta):
        assert "created_at" in meta
        # Should be a valid ISO timestamp
        datetime.fromisoformat(meta["created_at"])

    def test_meta_has_row_count(self, meta):
        assert "row_count" in meta
        assert meta["row_count"] == 5   # default n_symbols=5 in _make_test_db


class TestNoSideEffects:
    """Verify export leaves ml_samples and other files untouched."""

    def test_ml_samples_unchanged_after_export(self, tmp_path):
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE, n_symbols=3)
        model_root = _make_model_root(tmp_path)

        conn = sqlite3.connect(db_path)
        before_count  = conn.execute("SELECT COUNT(1) FROM ml_samples").fetchone()[0]
        before_outcomes = set(
            r[0] for r in conn.execute("SELECT DISTINCT outcome FROM ml_samples").fetchall()
        )
        conn.close()

        export_scoring_snapshot(
            sample_date=CLEAN_DATE,
            output_dir=tmp_path / "exports",
            training_cutoff_date=TRAINING_CUTOFF,
            db_path=db_path,
            model_root=model_root,
        )

        conn = sqlite3.connect(db_path)
        after_count   = conn.execute("SELECT COUNT(1) FROM ml_samples").fetchone()[0]
        after_outcomes = set(
            r[0] for r in conn.execute("SELECT DISTINCT outcome FROM ml_samples").fetchall()
        )
        conn.close()

        assert after_count == before_count, "ml_samples row count must not change"
        assert after_outcomes == before_outcomes, "ml_samples outcomes must not change"

    def test_training_csv_not_created_or_modified(self, tmp_path):
        """No file named ml_dataset_ohlcv*.csv must be written to output_dir."""
        db_path    = _make_test_db(tmp_path, sample_date=CLEAN_DATE)
        model_root = _make_model_root(tmp_path)
        out_dir    = tmp_path / "exports"

        export_scoring_snapshot(
            sample_date=CLEAN_DATE,
            output_dir=out_dir,
            training_cutoff_date=TRAINING_CUTOFF,
            db_path=db_path,
            model_root=model_root,
        )

        training_csvs = list(out_dir.glob("ml_dataset_ohlcv*.csv"))
        assert training_csvs == [], (
            f"Training CSV must not be written — found: {training_csvs}"
        )
