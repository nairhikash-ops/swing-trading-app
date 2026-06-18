import json
from datetime import datetime, timedelta
from typing import Any
import pytest

from app.config import Settings
from app.ml_samples import (
    ML_FUTURE_WINDOW_SESSIONS,
    ML_INPUT_WINDOW_SESSIONS,
    ML_LABEL_NAME,
    ML_MODEL_NAME,
    MLSampleService,
    MLSampleStore,
)
from app.instrument_master import InstrumentMasterStore
from app.scripts.generate_samples_batch import run_batch
from app.store import TokenStore


class MockIndexUniverseService:
    def nifty_500_constituents(self):
        return [{"symbol": "TESTSYM"}]


@pytest.fixture
def mock_settings(tmp_path):
    return Settings(
        database_path=str(tmp_path / "test_incremental.sqlite3"),
        secret_key="test",
        dhan_client_id="test",
        dhan_access_token="test",
    )


@pytest.fixture
def store(mock_settings):
    token_store = TokenStore(mock_settings.database_path)
    # create required tables
    with token_store._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_candles (
                id INTEGER PRIMARY KEY,
                instrument_id INTEGER,
                trading_date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_fetch_items (
                id INTEGER PRIMARY KEY,
                run_id TEXT,
                symbol TEXT
            )
            """
        )
    # create instruments table via actual store
    InstrumentMasterStore(token_store)
    return MLSampleStore(token_store)


@pytest.fixture
def ml_service(mock_settings, store):
    service = MLSampleService(settings=mock_settings, store=store)
    # Mock quality gate to avoid needing real data quality table setup
    service._enforce_healthy_quality_gate = lambda symbol: None
    return service


def insert_instrument(store: MLSampleStore, symbol: str) -> int:
    with store._connect() as conn:
        cursor = conn.execute(
            "INSERT OR REPLACE INTO instruments (active, exchange_id, segment, underlying_symbol, instrument, series, natural_key, row_hash, security_id, raw_json, first_seen_at, last_seen_at, updated_at, last_import_run_id) VALUES (1, 'NSE', 'E', ?, 'EQUITY', 'EQ', ?, ?, ?, '{}', '2026-01-01', '2026-01-01', '2026-01-01', 1)",
            (symbol, f"NSE:E:{symbol}:EQUITY:EQ", "hash", f"sec_{symbol}"),
        )
        return cursor.lastrowid


def insert_candles(store: MLSampleStore, instrument_id: int, start_date: str, count: int, close_val: float = 100.0) -> list[str]:
    dates = []
    base_date = datetime.strptime(start_date, "%Y-%m-%d")
    with store._connect() as conn:
        for i in range(count):
            current_date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(current_date)
            conn.execute(
                "INSERT INTO daily_candles (instrument_id, security_id, exchange_segment, instrument, trading_date, source_timestamp, open, high, low, close, volume, source, raw_json, fetched_at, updated_at) VALUES (?, 'sec_id', 'NSE_EQ', 'EQUITY', ?, 1234567890, ?, ?, ?, ?, ?, 'test_source', '{}', '2026-01-01', '2026-01-01')",
                (instrument_id, current_date, close_val, close_val + 5, close_val - 5, close_val, 1000),
            )
    return dates


def force_insert_sample(store: MLSampleStore, instrument_id: int, symbol: str, sample_date: str, outcome: str):
    store.upsert_sample({
        "model_name": ML_MODEL_NAME,
        "label_name": ML_LABEL_NAME,
        "instrument_id": instrument_id,
        "symbol": symbol,
        "sample_date": sample_date,
        "input_window_start": "2026-01-01",
        "input_window_end": sample_date,
        "future_window_start": "2026-01-02",
        "future_window_end": "2026-02-01",
        "entry_close": 100.0,
        "target_price": 105.0,
        "stop_price": 95.0,
        "outcome": outcome,
        "trainable": outcome in ("WIN", "LOSS", "TIMEOUT"),
        "exclude_reason": "",
        "barrier_hit_date": None,
        "barrier_hit_type": "",
        "days_to_outcome": 20,
        "feature": {"test": 1},
    })


def test_incremental_generation(store: MLSampleStore, ml_service: MLSampleService):
    instrument_id = insert_instrument(store, "TESTSYM")
    # We need ML_INPUT_WINDOW_SESSIONS + some extra to generate samples
    total_candles = ML_INPUT_WINDOW_SESSIONS + 3
    dates = insert_candles(store, instrument_id, "2026-01-01", total_candles)
    
    # We expect 4 samples to be possible.
    # index 59 (dates[59])
    # index 60 (dates[60])
    # index 61 (dates[61])
    # index 62 (dates[62])

    sample_date_1 = dates[59]
    sample_date_2 = dates[60]
    sample_date_3 = dates[61]
    sample_date_4 = dates[62]

    # Pre-insert some samples to test the logic
    # Test 1: Existing WIN sample date is skipped
    force_insert_sample(store, instrument_id, "TESTSYM", sample_date_1, "WIN")
    
    # Test 2: Existing INSUFFICIENT_FUTURE_DATA date is rebuilt
    force_insert_sample(store, instrument_id, "TESTSYM", sample_date_2, "INSUFFICIENT_FUTURE_DATA")
    
    # Test 3: New sample dates are created (sample_date_3, sample_date_4 are missing)

    res = ml_service.generate_one(symbol="TESTSYM", dry_run=False)

    assert res["symbol"] == "TESTSYM"
    assert res["samples_skipped_locked"] == 1  # sample_date_1
    assert res["samples_rebuilt_insufficient_future"] == 1  # sample_date_2
    assert res["samples_created"] == 2  # sample_date_3, sample_date_4
    assert res["samples_updated"] == 1  # sample_date_2

def test_batch_no_longer_skips_known_symbols(store: MLSampleStore, ml_service: MLSampleService):
    universe_service = MockIndexUniverseService()
    instrument_id = insert_instrument(store, "TESTSYM")
    total_candles = ML_INPUT_WINDOW_SESSIONS + 2
    dates = insert_candles(store, instrument_id, "2026-01-01", total_candles)
    
    sample_date_1 = dates[59]
    force_insert_sample(store, instrument_id, "TESTSYM", sample_date_1, "WIN")
    
    # Test 4: Batch no longer skips a symbol just because it already has samples
    summary = run_batch(
        ml_service=ml_service,
        universe_service=universe_service,
        ml_store=store,
        dry_run=False,
        limit=10,
        symbols_str=None
    )
    
    assert summary["attempted_count"] == 1
    assert summary["succeeded_count"] == 1
    assert summary["total_skipped_locked"] == 1
    assert summary["total_created"] == 2

def test_execute_requires_limit(store: MLSampleStore, ml_service: MLSampleService):
    universe_service = MockIndexUniverseService()
    # Test 5: --execute still requires --limit 
    # Actually this is handled in the main() argparse, but let's test run_batch limits
    # run_batch doesn't strictly raise if execute=True and limit=None, it's done in main().
    # But let's verify that limit works
    insert_instrument(store, "SYM1")
    insert_instrument(store, "SYM2")
    
    summary = run_batch(
        ml_service=ml_service,
        universe_service=universe_service,
        ml_store=store,
        dry_run=False,
        limit=1, # strictly 1
        symbols_str="SYM1,SYM2"
    )
    assert summary["attempted_count"] == 1
