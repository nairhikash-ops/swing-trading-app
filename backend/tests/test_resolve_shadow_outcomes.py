import os
import sqlite3
import pytest
from datetime import datetime, timezone

from app.config import get_settings
from app.shadow_tracking import (
    get_connection as get_shadow_connection,
    init_db,
    insert_shadow_records,
    get_observing_records
)
from app.store import TokenStore
from app.ml_foundation import ML_FUTURE_WINDOW_SESSIONS, ML_TARGET_PERCENT, ML_STOP_PERCENT
from app.scripts.resolve_shadow_outcomes import run_resolver

@pytest.fixture
def mock_dhan_db(tmp_path):
    db_path = str(tmp_path / "dhan.sqlite3")
    conn = sqlite3.connect(db_path)
    
    conn.execute('''
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY,
            active INTEGER,
            exchange_id TEXT,
            segment TEXT,
            instrument TEXT,
            series TEXT,
            underlying_symbol TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE daily_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER,
            trading_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER
        )
    ''')
    
    # Insert dummy instrument
    conn.execute('''
        INSERT INTO instruments (id, active, exchange_id, segment, instrument, series, underlying_symbol)
        VALUES (1, 1, 'NSE', 'E', 'EQUITY', 'EQ', 'TESTSYM')
    ''')
    
    conn.commit()
    conn.close()
    
    # We must patch get_settings so it returns this db_path
    original_get_settings = get_settings
    
    def mock_get_settings():
        settings = original_get_settings()
        return settings
        
    import app.scripts.resolve_shadow_outcomes as resolver_module
    
    original_token_store = resolver_module.TokenStore
    class MockTokenStore:
        def __init__(self, _):
            self.db_path = db_path
        def _connect(self):
            return sqlite3.connect(self.db_path)
            
    resolver_module.TokenStore = MockTokenStore
    
    yield db_path
    
    resolver_module.TokenStore = original_token_store


@pytest.fixture
def temp_shadow_db(tmp_path):
    db_path = str(tmp_path / "shadow.sqlite3")
    init_db(db_path)
    return db_path

def seed_future_candles(dhan_db_path, instrument_id, start_date, entry_close, num_candles, hit_type="none"):
    """
    Seeds `num_candles` into daily_candles after start_date.
    hit_type can be 'target', 'stop', 'both', 'none'.
    """
    conn = sqlite3.connect(dhan_db_path)
    
    # Insert entry candle
    conn.execute('''
        INSERT INTO daily_candles (instrument_id, trading_date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (instrument_id, start_date, entry_close, entry_close, entry_close, entry_close, 100))
    
    # Determine targets
    target_price = entry_close * (1 + ML_TARGET_PERCENT / 100.0)
    stop_price = entry_close * (1 - ML_STOP_PERCENT / 100.0)
    
    for i in range(1, num_candles + 1):
        date_str = f"2026-06-{i:02d}"  # simple dates
        high = entry_close
        low = entry_close
        
        # If this is the last candle, apply the hit
        if i == num_candles:
            if hit_type == "target":
                high = target_price + 1
            elif hit_type == "stop":
                low = stop_price - 1
            elif hit_type == "both":
                high = target_price + 1
                low = stop_price - 1
                
        conn.execute('''
            INSERT INTO daily_candles (instrument_id, trading_date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (instrument_id, date_str, entry_close, high, low, entry_close, 100))
        
    conn.commit()
    conn.close()

def insert_dummy_shadow(shadow_db_path, symbol="TESTSYM", date="2026-05-31", status="OBSERVING"):
    records = [{
        "date_scored": "2026-05-31T00:00:00",
        "scored_sample_date": date,
        "model_version": "v1.8",
        "model_commit": "unknown",
        "rank": 1,
        "bucket": "PRIMARY_TOP_1",
        "symbol": symbol,
        "win_probability": 0.85,
        "regime_context_json": "{}",
        "tracking_status": status
    }]
    insert_shadow_records(shadow_db_path, records)


def test_resolver_win_full_future(mock_dhan_db, temp_shadow_db):
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 20, "target")
    insert_dummy_shadow(temp_shadow_db)
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    assert row["tracking_status"] == "RESOLVED"
    assert row["future_observed_outcome"] == "WIN"
    assert row["barrier_hit_type"] == "target"

def test_resolver_loss_full_future(mock_dhan_db, temp_shadow_db):
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 20, "stop")
    insert_dummy_shadow(temp_shadow_db)
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    assert row["tracking_status"] == "RESOLVED"
    assert row["future_observed_outcome"] == "LOSS"
    assert row["barrier_hit_type"] == "stop"

def test_resolver_ambiguous_full_future(mock_dhan_db, temp_shadow_db):
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 20, "both")
    insert_dummy_shadow(temp_shadow_db)
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    assert row["tracking_status"] == "RESOLVED"
    assert row["future_observed_outcome"] == "AMBIGUOUS"
    assert row["barrier_hit_type"] == "both"

def test_resolver_timeout_full_future(mock_dhan_db, temp_shadow_db):
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 20, "none")
    insert_dummy_shadow(temp_shadow_db)
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    assert row["tracking_status"] == "RESOLVED"
    assert row["future_observed_outcome"] == "TIMEOUT"
    assert row["days_to_outcome"] == 20

def test_resolver_insufficient_future_even_if_hit(mock_dhan_db, temp_shadow_db):
    # Only 5 candles exist, but it hits target. 
    # Must stay OBSERVING to ensure strict parity.
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 5, "target")
    insert_dummy_shadow(temp_shadow_db)
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    # Should STILL be OBSERVING because it hasn't reached 20 candles
    assert row["tracking_status"] == "OBSERVING"
    assert row["future_observed_outcome"] is None

def test_resolver_ignores_resolved(mock_dhan_db, temp_shadow_db):
    seed_future_candles(mock_dhan_db, 1, "2026-05-31", 100.0, 20, "target")
    # Insert as RESOLVED already
    insert_dummy_shadow(temp_shadow_db, status="RESOLVED")
    
    run_resolver(shadow_db_path=temp_shadow_db)
    
    conn = get_shadow_connection(temp_shadow_db)
    row = conn.execute("SELECT * FROM shadow_tracking LIMIT 1").fetchone()
    conn.close()
    
    # Should remain unchanged (no outcome updated, etc since it was skipped)
    assert row["tracking_status"] == "RESOLVED"
    assert row["future_observed_outcome"] is None # we inserted it as None

