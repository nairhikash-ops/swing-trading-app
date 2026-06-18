import sqlite3
import os
from datetime import datetime, timezone
import json
from typing import List, Dict, Any

DEFAULT_DB_PATH = "/app/data/shadow_tracking.sqlite3"

def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shadow_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_scored TEXT NOT NULL,
            scored_sample_date TEXT NOT NULL,
            model_version TEXT NOT NULL,
            model_commit TEXT NOT NULL,
            rank INTEGER NOT NULL,
            bucket TEXT NOT NULL,
            symbol TEXT NOT NULL,
            win_probability REAL NOT NULL,
            regime_context_json TEXT NOT NULL,
            tracking_status TEXT NOT NULL,
            future_observed_outcome TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT,
            UNIQUE(model_version, scored_sample_date, symbol)
        )
    ''')
    conn.commit()
    conn.close()

def insert_shadow_records(db_path: str, records: List[Dict[str, Any]]) -> int:
    """
    Inserts a list of dictionary records into the shadow_tracking table.
    Safely ignores duplicates based on the unique constraint.
    Returns the number of successfully inserted rows.
    """
    if not records:
        return 0
        
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    inserted_count = 0
    now = datetime.now(timezone.utc).isoformat()
    
    for record in records:
        try:
            cursor.execute('''
                INSERT INTO shadow_tracking (
                    date_scored, scored_sample_date, model_version, model_commit,
                    rank, bucket, symbol, win_probability, regime_context_json,
                    tracking_status, future_observed_outcome, created_at, updated_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.get("date_scored", now),
                record["scored_sample_date"],
                record["model_version"],
                record["model_commit"],
                record["rank"],
                record["bucket"],
                record["symbol"],
                record["win_probability"],
                record["regime_context_json"],
                record.get("tracking_status", "OBSERVING"),
                record.get("future_observed_outcome", None),
                now,
                now,
                record.get("notes", None)
            ))
            inserted_count += 1
        except sqlite3.IntegrityError:
            # Duplicate based on UNIQUE constraint
            pass
            
    conn.commit()
    conn.close()
    
    return inserted_count
