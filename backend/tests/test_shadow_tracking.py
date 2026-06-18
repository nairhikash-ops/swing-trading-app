import os
import json
import pytest
import sqlite3
import pandas as pd
from app.shadow_tracking import init_db, insert_shadow_records, get_connection
from app.scripts.track_shadow_shortlist import run_track_shadow_shortlist

@pytest.fixture
def temp_db_env(tmp_path):
    data_dir = tmp_path / "data"
    exports_dir = data_dir / "exports"
    os.makedirs(exports_dir, exist_ok=True)
    
    db_path = str(data_dir / "shadow_tracking.sqlite3")
    csv_path = str(exports_dir / "latest_regime_rankings.csv")
    meta_path = str(exports_dir / "latest_regime_rankings.meta.json")
    
    # Create 100 dummy ranking rows
    records = []
    regime_cols = [
        "market_median_20d_return", "market_breakout_rate", "market_breakdown_rate",
        "market_breadth_delta", "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median", "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    for i in range(1, 101):
        row = {
            "rank": i,
            "symbol": f"SYM{i}",
            "sample_date": "2026-05-15",
            "win_probability": 0.9 - (i * 0.001)
        }
        for c in regime_cols:
            row[c] = 0.01
        records.append(row)
        
    pd.DataFrame(records).to_csv(csv_path, index=False)
    
    # Create meta json
    meta = {
        "model_version": "test_v1",
        "source_csv": "test.csv",
        "scored_sample_date": "2026-05-15",
        "row_count": 100,
        "ranking_count": 100,
        "is_live_today": False
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f)
        
    return {
        "db_path": db_path,
        "exports_dir": str(exports_dir)
    }

def test_shadow_tracking_db_init_and_insert(temp_db_env):
    db_path = temp_db_env["db_path"]
    init_db(db_path)
    
    records = [{
        "scored_sample_date": "2026-05-15",
        "model_version": "test_v1",
        "model_commit": "abc1234",
        "rank": 1,
        "bucket": "PRIMARY_TOP_1",
        "symbol": "SYM1",
        "win_probability": 0.85,
        "regime_context_json": "{}",
    }]
    
    # Insert once
    inserted = insert_shadow_records(db_path, records)
    assert inserted == 1
    
    # Check DB
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM shadow_tracking")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["tracking_status"] == "OBSERVING"
    assert rows[0]["future_observed_outcome"] is None
    
    # Insert again to test duplicate prevention
    inserted_dup = insert_shadow_records(db_path, records)
    assert inserted_dup == 0 # Should skip duplicate
    
    cur.execute("SELECT * FROM shadow_tracking")
    rows_after = cur.fetchall()
    assert len(rows_after) == 1
    conn.close()

def test_run_track_shadow_shortlist(temp_db_env, capsys):
    exports_dir = temp_db_env["exports_dir"]
    db_path = temp_db_env["db_path"]
    
    # Run the script
    run_track_shadow_shortlist(exports_dir=exports_dir, db_path=db_path)
    
    # Capture output
    captured = capsys.readouterr().out
    assert "Ranking rows: 100" in captured
    assert "Top 5% tracked: 5" in captured
    assert "Primary Top 1%: 1" in captured
    assert "Inserted: 5" in captured
    assert "Skipped duplicates: 0" in captured
    
    # Verify DB directly
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT rank, bucket, symbol FROM shadow_tracking ORDER BY rank ASC")
    rows = cur.fetchall()
    assert len(rows) == 5
    
    # Top 1% = 1 row (rank 1)
    assert rows[0]["bucket"] == "PRIMARY_TOP_1"
    assert rows[0]["symbol"] == "SYM1"
    
    # Remaining 4 rows should be WATCH_TOP_5
    for r in rows[1:]:
        assert r["bucket"] == "WATCH_TOP_5"
        
    conn.close()
    
    # Run again to test duplicate handling in script
    run_track_shadow_shortlist(exports_dir=exports_dir, db_path=db_path)
    captured2 = capsys.readouterr().out
    assert "Inserted: 0" in captured2
    assert "Skipped duplicates: 5" in captured2
