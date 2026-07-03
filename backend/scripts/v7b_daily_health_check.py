import os
import sys
import csv
import argparse
from datetime import datetime
from pathlib import Path

DEFAULT_LOG_PATH = r"D:\app\data\exports\forward_paper_log_matsya\forward_paper_daily_log.csv"

def run_health_check(log_path: str, target_date: str = None) -> int:
    """
    Reads the forward paper daily log and ensures the health criteria are met for the latest (or target) date:
      - matsya_token_state == 'active'
      - matsya_latest_candle_date == target_date (or log's date)
      - symbols_loaded == 500
      - fetch_failures == 0
    Returns 0 if healthy, 1 if failures detected.
    """
    if not os.path.exists(log_path):
        print(f"ERROR: Log file not found at {log_path}")
        return 1

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if not reader:
                print(f"ERROR: Log file {log_path} is empty.")
                return 1
            
            # Find the target row
            if target_date:
                rows = [r for r in reader if r["date"] == target_date]
                if not rows:
                    print(f"ERROR: No log entry found for date {target_date}")
                    return 1
                row = rows[-1] # Take the latest entry for that date if multiple
            else:
                row = reader[-1] # Latest overall
                
    except Exception as e:
        print(f"ERROR: Failed to read log file: {e}")
        return 1

    date = row.get("date", "UNKNOWN")
    matsya_latest_candle_date = row.get("matsya_latest_candle_date", "")
    matsya_token_state = row.get("matsya_token_state", "")
    
    try:
        symbols_loaded = int(row.get("symbols_loaded", "0"))
        fetch_failures = int(row.get("fetch_failures", "-1"))
    except ValueError:
        print(f"ERROR: Invalid numeric data in log for date {date}: loaded={row.get('symbols_loaded')}, failures={row.get('fetch_failures')}")
        return 1

    errors = []

    if matsya_token_state.lower() != "active":
        errors.append(f"Token state is '{matsya_token_state}', expected 'active'.")
        
    if matsya_latest_candle_date != date:
        errors.append(f"Matsya latest candle date '{matsya_latest_candle_date}' does not match log date '{date}'.")
        
    if symbols_loaded != 500:
        errors.append(f"Symbols loaded is {symbols_loaded}, expected 500.")
        
    if fetch_failures != 0:
        errors.append(f"Fetch failures is {fetch_failures}, expected 0.")

    print(f"=== Health Check for {date} ===")
    if errors:
        print("STATUS: FAILED")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("STATUS: PASSED")
        print("  - Token state: active")
        print(f"  - Candle date matches: {date}")
        print("  - Symbols loaded: 500")
        print("  - Fetch failures: 0")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Daily Health Check for Forward Paper Logger")
    parser.add_argument("--log-path", type=str, default=DEFAULT_LOG_PATH, help="Path to the daily log CSV")
    parser.add_argument("--date", type=str, default=None, help="Specific date to check (YYYY-MM-DD). Defaults to the latest entry.")
    
    args = parser.parse_args()
    
    exit_code = run_health_check(args.log_path, args.date)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
