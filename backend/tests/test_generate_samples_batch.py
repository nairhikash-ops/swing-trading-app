import sys
from unittest.mock import MagicMock, patch

import pytest

from app.scripts.generate_samples_batch import run_batch


@pytest.fixture
def mock_ml_service():
    return MagicMock()


@pytest.fixture
def mock_universe_service():
    srv = MagicMock()
    srv.nifty_500_constituents.return_value = [{"symbol": "RELIANCE"}, {"symbol": "TCS"}, {"symbol": "INFY"}]
    return srv


@pytest.fixture
def mock_ml_store():
    store = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"symbol": "TCS"}]
    mock_conn.execute.return_value = mock_cursor

    class MockContext:
        def __enter__(self):
            return mock_conn
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    store._connect.return_value = MockContext()
    return store


def test_default_is_dry_run(mock_ml_service, mock_universe_service, mock_ml_store):
    mock_ml_service.generate_one.return_value = {"samples_created": 10, "samples_updated": 0}

    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=True,
        limit=None,
        symbols_str=None,
    )

    assert summary["dry_run"] is True
    assert summary["execute"] is False
    assert mock_ml_service.generate_one.call_count == 2  # RELIANCE, INFY (TCS skipped)
    mock_ml_service.generate_one.assert_any_call(symbol="RELIANCE", dry_run=True)
    mock_ml_service.generate_one.assert_any_call(symbol="INFY", dry_run=True)
    assert summary["total_would_create"] == 20
    assert summary["total_created"] == 0


def test_execute_without_limit_fails_in_main():
    from app.scripts.generate_samples_batch import main
    with patch.object(sys, "argv", ["generate_samples_batch.py", "--execute"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


def test_already_generated_symbols_are_skipped(mock_ml_service, mock_universe_service, mock_ml_store):
    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=True,
        limit=None,
        symbols_str=None,
    )

    assert summary["already_generated_count"] == 1
    assert summary["skipped_count"] == 1
    assert summary["attempted_count"] == 2
    for call in mock_ml_service.generate_one.call_args_list:
        assert call.kwargs["symbol"] != "TCS"


def test_symbols_override_works(mock_ml_service, mock_universe_service, mock_ml_store):
    mock_ml_service.generate_one.return_value = {"samples_created": 5, "samples_updated": 0}

    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=True,
        limit=None,
        symbols_str="HDFC, TCS, SBIN",
    )

    assert summary["requested_symbol_count"] == 3
    assert summary["attempted_count"] == 2  # HDFC, SBIN (TCS is skipped)
    mock_universe_service.nifty_500_constituents.assert_not_called()


def test_limit_restricts_attempted_symbols(mock_ml_service, mock_universe_service, mock_ml_store):
    mock_universe_service.nifty_500_constituents.return_value = [{"symbol": f"SYM{i}"} for i in range(100)]
    mock_ml_service.generate_one.return_value = {"samples_created": 1, "samples_updated": 0}

    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=False,
        limit=5,
        symbols_str=None,
    )

    assert summary["attempted_count"] == 5
    assert mock_ml_service.generate_one.call_count == 5


def test_per_symbol_error_recorded_and_continues(mock_ml_service, mock_universe_service, mock_ml_store):
    def side_effect(symbol, dry_run):
        if symbol == "RELIANCE":
            raise ValueError("Quality gate failed")
        return {"samples_created": 1, "samples_updated": 0}

    mock_ml_service.generate_one.side_effect = side_effect

    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=True,
        limit=None,
        symbols_str=None,
    )

    assert summary["attempted_count"] == 2
    assert summary["succeeded_count"] == 1
    assert summary["failed_count"] == 1
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["symbol"] == "RELIANCE"
    assert "Quality gate failed" in summary["errors"][0]["message"]


def test_summary_counts_are_correct(mock_ml_service, mock_universe_service, mock_ml_store):
    mock_ml_service.generate_one.return_value = {"samples_created": 2, "samples_updated": 1}

    summary = run_batch(
        ml_service=mock_ml_service,
        universe_service=mock_universe_service,
        ml_store=mock_ml_store,
        dry_run=False,
        limit=2,
        symbols_str=None,
    )

    assert summary["execute"] is True
    assert summary["dry_run"] is False
    assert summary["total_created"] == 4
    assert summary["total_updated"] == 2


def test_main_default_is_dry_run():
    from app.scripts.generate_samples_batch import main
    with patch("app.scripts.generate_samples_batch.run_batch") as mock_run_batch:
        with patch.object(sys, "argv", ["generate_samples_batch.py"]):
            main()
            mock_run_batch.assert_called_once()
            _, kwargs = mock_run_batch.call_args
            assert kwargs["dry_run"] is True
            assert kwargs["limit"] is None
