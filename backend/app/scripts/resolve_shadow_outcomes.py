import sys
import argparse
from typing import Any

from app.config import get_settings
from app.store import TokenStore
from app.shadow_tracking import (
    DEFAULT_DB_PATH,
    init_db,
    get_observing_records,
    update_shadow_outcome
)
from app.ml_samples import classify_outcome
from app.ml_foundation import (
    ML_FUTURE_WINDOW_SESSIONS,
    ML_TARGET_PERCENT,
    ML_STOP_PERCENT
)

def run_resolver(
    shadow_db_path: str = DEFAULT_DB_PATH,
):
    settings = get_settings()
    token_store = TokenStore(settings.database_path)
    
    init_db(shadow_db_path)
    records = get_observing_records(shadow_db_path)
    
    if not records:
        print("No OBSERVING records found in shadow tracking.")
        return
        
    print(f"Found {len(records)} OBSERVING records.")
    
    resolved_count = 0
    skipped_count = 0
    
    with token_store._connect() as conn:
        for record in records:
            symbol = record["symbol"]
            scored_sample_date = record["scored_sample_date"]
            
            # Resolve instrument
            inst_row = conn.execute('''
                SELECT id FROM instruments
                WHERE active = 1 AND exchange_id = 'NSE' AND segment = 'E' AND UPPER(underlying_symbol) = ?
                ORDER BY
                  CASE WHEN instrument = 'EQUITY' THEN 0 ELSE 1 END,
                  CASE WHEN series = 'EQ' THEN 0 ELSE 1 END,
                  id
                LIMIT 1
            ''', (symbol.upper(),)).fetchone()
            
            if not inst_row:
                print(f"Skipping {symbol} on {scored_sample_date}: could not resolve instrument.")
                skipped_count += 1
                continue
                
            instrument_id = int(inst_row["id"])
            
            # Fetch entry candle
            entry_row = conn.execute('''
                SELECT close FROM daily_candles
                WHERE instrument_id = ? AND trading_date = ?
            ''', (instrument_id, scored_sample_date)).fetchone()
            
            if not entry_row:
                print(f"Skipping {symbol} on {scored_sample_date}: entry candle not found.")
                skipped_count += 1
                continue
                
            entry_close = float(entry_row["close"])
            
            # Fetch exactly the next ML_FUTURE_WINDOW_SESSIONS candles
            future_rows = conn.execute('''
                SELECT trading_date, high, low FROM daily_candles
                WHERE instrument_id = ? AND trading_date > ?
                ORDER BY trading_date ASC
                LIMIT ?
            ''', (instrument_id, scored_sample_date, ML_FUTURE_WINDOW_SESSIONS)).fetchall()
            
            future_window = [dict(row) for row in future_rows]
            
            # The strict V1.10 rule: do not resolve early!
            if len(future_window) < ML_FUTURE_WINDOW_SESSIONS:
                print(f"Skipping {symbol} on {scored_sample_date}: insufficient future data ({len(future_window)}/{ML_FUTURE_WINDOW_SESSIONS})")
                skipped_count += 1
                continue
                
            # Classify
            target_price = entry_close * (1 + ML_TARGET_PERCENT / 100.0)
            stop_price = entry_close * (1 - ML_STOP_PERCENT / 100.0)
            
            outcome_data = classify_outcome(
                future_window=future_window,
                future_window_sessions=ML_FUTURE_WINDOW_SESSIONS,
                target_price=target_price,
                stop_price=stop_price
            )
            
            # The outcome from classify_outcome should never be INSUFFICIENT_FUTURE_DATA 
            # if we verified len(future_window) == 20, but just to be safe:
            if outcome_data["outcome"] == "INSUFFICIENT_FUTURE_DATA":
                print(f"Skipping {symbol} on {scored_sample_date}: insufficient future data returned by classify.")
                skipped_count += 1
                continue
                
            # It's WIN, LOSS, AMBIGUOUS, or TIMEOUT
            print(f"Resolving {symbol} on {scored_sample_date} -> {outcome_data['outcome']}")
            update_shadow_outcome(shadow_db_path, record["id"], outcome_data)
            resolved_count += 1
            
    print("=== RESOLVER SUMMARY ===")
    print(f"Total OBSERVING scanned: {len(records)}")
    print(f"Resolved: {resolved_count}")
    print(f"Skipped (still observing): {skipped_count}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve outcomes for shadow tracking journal")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="Path to shadow tracking DB")
    args = parser.parse_args()
    
    run_resolver(shadow_db_path=args.db_path)

if __name__ == "__main__":
    main()
