"""Tests for compare_shadow_model_versions.py.

Verifies:
- Script is read-only (shadow_tracking DB never mutated)
- Premature-comparison warning appears when OBSERVING rows exist
- Overlap analysis correctly identifies shared symbols
- Disclaimer is always present in output
- No crash when one model has 0 RESOLVED rows
"""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.shadow_tracking import init_db, get_all_records_by_model
from app.scripts.compare_shadow_model_versions import (
    run_comparison,
    build_model_status,
    build_overlap,
    DISCLAIMER,
    FULL_DISCLAIMER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL_HGB = "stock_opportunity_hgb_regime_v1"
MODEL_LR  = "stock_opportunity_ohlcv_regime_v1"
SCORED_DATE = "2026-05-18"


def _temp_shadow_db() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    f.close()
    init_db(f.name)
    return f.name


def _insert_row(
    db_path: str,
    model_version: str,
    symbol: str,
    rank: int = 1,
    bucket: str = "PRIMARY_TOP_1",
    tracking_status: str = "OBSERVING",
    future_observed_outcome: str = None,
    scored_sample_date: str = SCORED_DATE,
    win_probability: float = 0.65,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        INSERT INTO shadow_tracking (
            date_scored, scored_sample_date, model_version, model_commit,
            rank, bucket, symbol, win_probability, regime_context_json,
            tracking_status, future_observed_outcome,
            created_at, updated_at, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now, scored_sample_date, model_version, "abc1234",
            rank, bucket, symbol, win_probability, "{}",
            tracking_status, future_observed_outcome,
            now, now, None,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def _get_all_rows(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM shadow_tracking").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _snapshot(db_path: str) -> List[Dict[str, Any]]:
    """Full snapshot of shadow_tracking for before/after comparison."""
    return _get_all_rows(db_path)


# ---------------------------------------------------------------------------
# Tests: read-only safety
# ---------------------------------------------------------------------------

class TestComparisonIsReadOnly:
    """run_comparison must never mutate shadow_tracking."""

    def test_no_rows_modified(self, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        _insert_row(db, MODEL_HGB, "AAAA", tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "BBBB", tracking_status="RESOLVED", future_observed_outcome="LOSS")

        before = _snapshot(db)
        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )
        after = _snapshot(db)

        assert before == after, "shadow_tracking rows must not change after run_comparison"

    def test_no_rows_inserted(self, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        _insert_row(db, MODEL_HGB, "CCCC", tracking_status="OBSERVING")

        count_before = len(_get_all_rows(db))
        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )
        count_after = len(_get_all_rows(db))

        assert count_before == count_after, "run_comparison must not insert any rows"

    def test_no_rows_deleted(self, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        _insert_row(db, MODEL_HGB, "DDDD", tracking_status="RESOLVED", future_observed_outcome="WIN")

        count_before = len(_get_all_rows(db))
        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )
        count_after = len(_get_all_rows(db))

        assert count_before == count_after, "run_comparison must not delete any rows"


# ---------------------------------------------------------------------------
# Tests: premature-comparison warning
# ---------------------------------------------------------------------------

class TestPrematureComparisonWarning:

    def test_warning_shown_when_observing_rows_exist(self, capsys, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        # HGB has an OBSERVING row (not yet resolved)
        _insert_row(db, MODEL_HGB, "EEEE", tracking_status="OBSERVING")
        _insert_row(db, MODEL_LR,  "FFFF", tracking_status="RESOLVED", future_observed_outcome="WIN")

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )

        out = capsys.readouterr().out
        assert "premature" in out.lower() or "OBSERVING" in out, (
            "Output must warn about premature comparison when OBSERVING rows exist"
        )

    def test_no_warning_when_all_resolved(self, capsys, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        _insert_row(db, MODEL_HGB, "GGGG", tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "HHHH", tracking_status="RESOLVED", future_observed_outcome="LOSS")

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )

        out = capsys.readouterr().out
        # Should not say "premature" if zero OBSERVING rows
        # (we do check is_premature=False in status)
        all_rows_hgb = get_all_records_by_model(db, MODEL_HGB)
        status_hgb = build_model_status(all_rows_hgb, SCORED_DATE)
        assert not status_hgb["is_premature"]

    def test_build_model_status_includes_observing_count(self):
        db = _temp_shadow_db()
        _insert_row(db, MODEL_HGB, "IIII", tracking_status="OBSERVING")
        _insert_row(db, MODEL_HGB, "JJJJ", tracking_status="RESOLVED", future_observed_outcome="WIN")

        rows = get_all_records_by_model(db, MODEL_HGB)
        status = build_model_status(rows, SCORED_DATE)

        assert status["total_rows_on_date"] == 2
        assert status["observing_count"] == 1
        assert status["resolved_count"] == 1
        assert status["is_premature"] is True


# ---------------------------------------------------------------------------
# Tests: overlap analysis
# ---------------------------------------------------------------------------

class TestOverlapAnalysis:

    def test_shared_symbol_detected(self, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        # "SHARED" appears in both models
        _insert_row(db, MODEL_HGB, "SHARED", rank=1, tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "SHARED", rank=2, tracking_status="RESOLVED", future_observed_outcome="LOSS")
        _insert_row(db, MODEL_HGB, "ONLY_HGB", rank=2, tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "ONLY_LR",  rank=3, tracking_status="RESOLVED", future_observed_outcome="WIN")

        all_a = get_all_records_by_model(db, MODEL_HGB)
        all_b = get_all_records_by_model(db, MODEL_LR)
        status_a = build_model_status(all_a, SCORED_DATE)
        status_b = build_model_status(all_b, SCORED_DATE)

        overlap = build_overlap(status_a, status_b, MODEL_HGB, MODEL_LR, all_a, all_b, SCORED_DATE)

        assert len(overlap) == 1
        assert overlap[0]["symbol"] == "SHARED"

    def test_no_overlap_when_no_shared_symbols(self, tmp_path):
        db = _temp_shadow_db()
        exports = str(tmp_path)

        _insert_row(db, MODEL_HGB, "AAAA", rank=1, tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "BBBB", rank=1, tracking_status="RESOLVED", future_observed_outcome="WIN")

        all_a = get_all_records_by_model(db, MODEL_HGB)
        all_b = get_all_records_by_model(db, MODEL_LR)
        status_a = build_model_status(all_a, SCORED_DATE)
        status_b = build_model_status(all_b, SCORED_DATE)

        overlap = build_overlap(status_a, status_b, MODEL_HGB, MODEL_LR, all_a, all_b, SCORED_DATE)
        assert overlap == []

    def test_overlap_includes_both_model_outcomes(self):
        db = _temp_shadow_db()

        _insert_row(db, MODEL_HGB, "SYM", rank=1, tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "SYM", rank=5, tracking_status="RESOLVED", future_observed_outcome="LOSS")

        all_a = get_all_records_by_model(db, MODEL_HGB)
        all_b = get_all_records_by_model(db, MODEL_LR)
        status_a = build_model_status(all_a, SCORED_DATE)
        status_b = build_model_status(all_b, SCORED_DATE)

        overlap = build_overlap(status_a, status_b, MODEL_HGB, MODEL_LR, all_a, all_b, SCORED_DATE)

        assert len(overlap) == 1
        row = overlap[0]
        assert row[f"{MODEL_HGB}_outcome"] == "WIN"
        assert row[f"{MODEL_LR}_outcome"] == "LOSS"


# ---------------------------------------------------------------------------
# Tests: disclaimer always present
# ---------------------------------------------------------------------------

class TestDisclaimerAlwaysPresent:

    def test_disclaimer_in_output_with_data(self, capsys, tmp_path):
        db = _temp_shadow_db()
        _insert_row(db, MODEL_HGB, "AAAA", tracking_status="RESOLVED", future_observed_outcome="WIN")
        _insert_row(db, MODEL_LR,  "BBBB", tracking_status="RESOLVED", future_observed_outcome="WIN")

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=str(tmp_path),
        )

        out = capsys.readouterr().out
        assert "One scored date only" in out
        assert "Shadow diagnostic only" in out
        assert "Not enough evidence for model promotion" in out

    def test_disclaimer_in_output_with_no_data(self, capsys, tmp_path):
        db = _temp_shadow_db()  # empty DB

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=str(tmp_path),
        )

        out = capsys.readouterr().out
        assert "One scored date only" in out
        assert "Not enough evidence for model promotion" in out


# ---------------------------------------------------------------------------
# Tests: graceful handling of empty / zero-resolved rows
# ---------------------------------------------------------------------------

class TestEmptyResolvedRowsNoCrash:

    def test_no_crash_when_model_a_has_zero_resolved(self, tmp_path, capsys):
        db = _temp_shadow_db()
        # Model A has only OBSERVING rows; model B has a resolved row
        _insert_row(db, MODEL_HGB, "AAAA", tracking_status="OBSERVING")
        _insert_row(db, MODEL_LR,  "BBBB", tracking_status="RESOLVED", future_observed_outcome="WIN")

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=str(tmp_path),
        )
        # No assertion needed — test passes if no exception raised

    def test_no_crash_with_completely_empty_db(self, tmp_path, capsys):
        db = _temp_shadow_db()  # no rows at all

        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=str(tmp_path),
        )
        # Test passes if no exception raised

    def test_json_export_written(self, tmp_path):
        db = _temp_shadow_db()
        _insert_row(db, MODEL_HGB, "AAAA", tracking_status="RESOLVED", future_observed_outcome="WIN")

        exports = str(tmp_path)
        run_comparison(
            shadow_db_path=db,
            scored_date=SCORED_DATE,
            model_a=MODEL_HGB,
            model_b=MODEL_LR,
            exports_dir=exports,
        )

        # Find the JSON export file
        json_files = [f for f in os.listdir(exports) if f.endswith(".json")]
        assert len(json_files) == 1, f"Expected 1 JSON export file, found: {json_files}"

        with open(os.path.join(exports, json_files[0])) as f:
            data = json.load(f)

        assert data["scored_date"] == SCORED_DATE
        assert data["model_a"] == MODEL_HGB
        assert data["model_b"] == MODEL_LR
        assert "disclaimer" in data
        assert "One scored date only" in data["disclaimer"]
