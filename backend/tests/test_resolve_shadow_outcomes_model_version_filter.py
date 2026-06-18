"""Tests for V1.24 model-version filtering and dry-run safety in
resolve_shadow_outcomes.py.

All tests use a real in-memory / temp SQLite DB — no mocks of the DB layer.
The token_store / candle layer IS mocked so we do not need the full Dhan DB.
"""

import io
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.shadow_tracking import (
    DEFAULT_DB_PATH,
    init_db,
    get_observing_records_by_model,
    get_model_version_counts,
    get_connection,
)
from app.scripts.resolve_shadow_outcomes import run_resolver
from app.ml_foundation import ML_FUTURE_WINDOW_SESSIONS


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _temp_shadow_db() -> str:
    """Create a temp shadow tracking DB and return its path."""
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
    scored_sample_date: str = "2026-05-18",
) -> int:
    """Insert a synthetic shadow row and return its id."""
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
            rank, bucket, symbol, 0.65, "{}",
            tracking_status, None,
            now, now, None,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def _get_row(db_path: str, row_id: int) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM shadow_tracking WHERE id = ?", (row_id,)).fetchone()
    conn.close()
    return dict(row)


# ---------------------------------------------------------------------------
# Simulate future candle data
# ---------------------------------------------------------------------------

def _make_future_window(sessions: int = ML_FUTURE_WINDOW_SESSIONS, win: bool = True):
    """Return a list of fake candle dicts that resolve to WIN if win=True."""
    candles = []
    for i in range(sessions):
        if win and i == 2:
            # high > target price (entry_close * 1.07)
            candles.append({"trading_date": f"2026-05-{20+i:02d}", "high": 9999.0, "low": 100.0})
        else:
            candles.append({"trading_date": f"2026-05-{20+i:02d}", "high": 200.0, "low": 190.0})
    return candles


@contextmanager
def _patch_token_store(future_window, entry_close=150.0):
    """Context manager that patches the token_store connection used by the resolver.

    Injects fake instrument, entry candle, and future candle data.
    """
    mock_inst_row = MagicMock()
    mock_inst_row.__getitem__ = lambda self, key: 99 if key == "id" else None

    mock_entry_row = MagicMock()
    mock_entry_row.__getitem__ = lambda self, key: entry_close if key == "close" else None

    mock_future_rows = [MagicMock() for _ in future_window]
    for mock_row, candle in zip(mock_future_rows, future_window):
        mock_row.__getitem__ = lambda self, key, c=candle: c[key]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.row_factory = None

    def side_effect_execute(sql, params=()):
        mock_cursor = MagicMock()
        sql_upper = sql.strip().upper()
        if "FROM INSTRUMENTS" in sql_upper:
            mock_cursor.fetchone.return_value = mock_inst_row
        elif "FROM DAILY_CANDLES" in sql_upper and "LIMIT" not in sql_upper:
            mock_cursor.fetchone.return_value = mock_entry_row
        elif "FROM DAILY_CANDLES" in sql_upper and "LIMIT" in sql_upper:
            mock_cursor.fetchall.return_value = mock_future_rows
        else:
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.return_value = []
        return mock_cursor

    mock_conn.execute = side_effect_execute

    mock_token_store = MagicMock()
    mock_token_store._connect.return_value = mock_conn

    mock_settings = MagicMock()
    mock_settings.database_path = ":memory:"

    with (
        patch("app.scripts.resolve_shadow_outcomes.get_settings", return_value=mock_settings),
        patch("app.scripts.resolve_shadow_outcomes.TokenStore", return_value=mock_token_store),
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDryRunDoesNotWrite:
    """dry-run (execute=False) must never write to shadow_tracking."""

    def test_dry_run_leaves_rows_unchanged(self):
        db = _temp_shadow_db()
        _insert_row(db, "stock_opportunity_hgb_regime_v1", "AAAA", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)

        with _patch_token_store(future):
            run_resolver(shadow_db_path=db, model_version="stock_opportunity_hgb_regime_v1", execute=False)

        row = _get_row(db, 1)
        assert row["tracking_status"] == "OBSERVING", (
            "Dry-run must not change tracking_status"
        )
        assert row["future_observed_outcome"] is None, (
            "Dry-run must not set future_observed_outcome"
        )

    def test_dry_run_total_row_count_unchanged(self):
        db = _temp_shadow_db()
        _insert_row(db, "stock_opportunity_hgb_regime_v1", "BBBB", rank=1)
        _insert_row(db, "stock_opportunity_ohlcv_regime_v1", "CCCC", rank=1)

        counts_before = dict(get_model_version_counts(db))

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=False)
        with _patch_token_store(future):
            run_resolver(shadow_db_path=db, model_version="stock_opportunity_hgb_regime_v1", execute=False)

        counts_after = dict(get_model_version_counts(db))
        assert counts_before == counts_after, (
            f"DB counts changed during dry-run: before={counts_before} after={counts_after}"
        )


class TestDryRunPrintsExpectedOutput:
    """Dry-run output must contain all required fields."""

    def test_dry_run_prints_required_fields(self, capsys):
        db = _temp_shadow_db()
        _insert_row(db, "stock_opportunity_hgb_regime_v1", "DDDD", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)
        with _patch_token_store(future):
            run_resolver(shadow_db_path=db, model_version="stock_opportunity_hgb_regime_v1", execute=False)

        captured = capsys.readouterr().out

        assert "stock_opportunity_hgb_regime_v1" in captured
        assert "Total OBSERVING rows" in captured
        assert "Rows with enough future candles" in captured
        assert "Rows with insufficient future data" in captured
        assert "Expected WIN count" in captured
        assert "Expected LOSS count" in captured
        assert "Expected TIMEOUT count" in captured
        assert "Expected AMBIGUOUS count" in captured
        assert "Expected rows that WOULD be updated" in captured
        assert "DB COUNTS BEFORE" in captured
        assert "DB COUNTS AFTER DRY-RUN" in captured
        assert "DRY RUN ONLY - NO DB WRITE" in captured


class TestModelVersionFilterIsolation:
    """Model-version filter must prevent cross-model contamination."""

    def test_only_target_model_rows_are_resolved(self):
        db = _temp_shadow_db()
        hgb_id = _insert_row(db, "stock_opportunity_hgb_regime_v1", "EEEE", rank=1)
        lr_id  = _insert_row(db, "stock_opportunity_ohlcv_regime_v1", "FFFF", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)
        with _patch_token_store(future):
            run_resolver(
                shadow_db_path=db,
                model_version="stock_opportunity_hgb_regime_v1",
                execute=True,
            )

        hgb_row = _get_row(db, hgb_id)
        lr_row  = _get_row(db, lr_id)

        assert hgb_row["tracking_status"] == "RESOLVED", (
            "HGB row must be resolved after execute"
        )
        assert lr_row["tracking_status"] == "OBSERVING", (
            "LR row must remain OBSERVING — must not be touched by HGB resolver"
        )

    def test_lr_outcome_not_set_after_hgb_resolution(self):
        db = _temp_shadow_db()
        _insert_row(db, "stock_opportunity_hgb_regime_v1", "GGGG", rank=1)
        lr_id = _insert_row(db, "stock_opportunity_ohlcv_regime_v1", "HHHH", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)
        with _patch_token_store(future):
            run_resolver(
                shadow_db_path=db,
                model_version="stock_opportunity_hgb_regime_v1",
                execute=True,
            )

        lr_row = _get_row(db, lr_id)
        assert lr_row["future_observed_outcome"] is None, (
            "LR future_observed_outcome must remain None"
        )

    def test_unfiltered_resolver_touches_all_models(self):
        """Without --model-version, resolver processes all OBSERVING rows."""
        db = _temp_shadow_db()
        hgb_id = _insert_row(db, "stock_opportunity_hgb_regime_v1", "IIII", rank=1)
        lr_id  = _insert_row(db, "stock_opportunity_ohlcv_regime_v1", "JJJJ", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)
        with _patch_token_store(future):
            run_resolver(shadow_db_path=db, model_version=None, execute=True)

        hgb_row = _get_row(db, hgb_id)
        lr_row  = _get_row(db, lr_id)

        # Both are resolved when no filter is applied
        assert hgb_row["tracking_status"] == "RESOLVED"
        assert lr_row["tracking_status"] == "RESOLVED"


class TestExecuteWritesOutcomes:
    """--execute flag must write correct outcomes to the DB."""

    def test_execute_writes_win(self):
        db = _temp_shadow_db()
        row_id = _insert_row(db, "stock_opportunity_hgb_regime_v1", "KKKK", rank=1)

        future = _make_future_window(ML_FUTURE_WINDOW_SESSIONS, win=True)
        with _patch_token_store(future):
            run_resolver(
                shadow_db_path=db,
                model_version="stock_opportunity_hgb_regime_v1",
                execute=True,
            )

        row = _get_row(db, row_id)
        assert row["tracking_status"] == "RESOLVED"
        assert row["future_observed_outcome"] == "WIN"

    def test_execute_skips_insufficient_data(self):
        db = _temp_shadow_db()
        row_id = _insert_row(db, "stock_opportunity_hgb_regime_v1", "LLLL", rank=1)

        # Only 5 future sessions — not enough
        future = _make_future_window(sessions=5, win=True)
        with _patch_token_store(future):
            run_resolver(
                shadow_db_path=db,
                model_version="stock_opportunity_hgb_regime_v1",
                execute=True,
            )

        row = _get_row(db, row_id)
        assert row["tracking_status"] == "OBSERVING", (
            "Row with insufficient future data must remain OBSERVING"
        )


class TestGetObservingRecordsByModel:
    """Unit tests for the shadow_tracking helper used by the resolver."""

    def test_returns_only_target_model_observing(self):
        db = _temp_shadow_db()
        _insert_row(db, "model_a", "AAA", rank=1, tracking_status="OBSERVING")
        _insert_row(db, "model_b", "BBB", rank=1, tracking_status="OBSERVING")
        _insert_row(db, "model_a", "CCC", rank=2, tracking_status="RESOLVED")

        rows = get_observing_records_by_model(db, "model_a")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAA"
        assert rows[0]["model_version"] == "model_a"

    def test_returns_empty_if_none_observing_for_model(self):
        db = _temp_shadow_db()
        _insert_row(db, "model_a", "AAA", rank=1, tracking_status="RESOLVED")
        rows = get_observing_records_by_model(db, "model_a")
        assert rows == []
