import os
import sys
import json
import sqlite3
import subprocess
from app.shadow_tracking import DEFAULT_DB_PATH

def run_module(module_name: str) -> None:
    print(f"\n============================================================")
    print(f"RUNNING: {module_name}")
    print(f"============================================================")
    result = subprocess.run([sys.executable, "-m", module_name])
    if result.returncode != 0:
        print(f"ERROR: {module_name} failed with return code {result.returncode}")
        sys.exit(result.returncode)

def get_shadow_db_count(db_path: str = DEFAULT_DB_PATH) -> int:
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM shadow_tracking")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_shadow_db_status_counts(db_path: str = DEFAULT_DB_PATH) -> dict:
    if not os.path.exists(db_path):
        return {"OBSERVING": 0, "RESOLVED": 0}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT tracking_status, COUNT(*) as c FROM shadow_tracking GROUP BY tracking_status")
    rows = cursor.fetchall()
    conn.close()
    
    status_counts = {"OBSERVING": 0, "RESOLVED": 0}
    for r in rows:
        status_counts[r["tracking_status"]] = r["c"]
    return status_counts

def run_pipeline() -> None:
    print("V1.12 GUARDED MANUAL SHADOW PIPELINE RUNNER")
    print("Starting pipeline execution...\n")
    
    # 1. Verify required artifacts
    artifacts = [
        "/app/data/models/stock_opportunity_ohlcv_regime_v1/model.joblib",
        "/app/data/models/stock_opportunity_ohlcv_regime_v1/feature_schema.json",
        "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv"
    ]
    
    for path in artifacts:
        if not os.path.exists(path):
            print(f"CRITICAL ERROR: Required artifact missing: {path}")
            sys.exit(1)
            
    print("[✓] All required artifacts verified present.")
    
    # Record state before running
    count_before = get_shadow_db_count()
    status_before = get_shadow_db_status_counts()
    
    # 2. Score Latest Regime
    run_module("app.scripts.score_latest_regime")
    
    # Extract metadata about what was scored
    meta_path = "/app/data/exports/latest_regime_rankings.meta.json"
    if not os.path.exists(meta_path):
        print(f"ERROR: {meta_path} was not generated.")
        sys.exit(1)
        
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    scored_sample_date = meta.get("scored_sample_date", "unknown")
    ranking_rows = meta.get("ranking_count", 0)
    top_5_count = max(1, int(round(0.05 * ranking_rows)))
    
    # 3. Track Shadow Shortlist
    run_module("app.scripts.track_shadow_shortlist")
    
    # 4. Resolve Shadow Outcomes
    run_module("app.scripts.resolve_shadow_outcomes")
    
    # 5. Report Shadow Performance
    run_module("app.scripts.report_shadow_performance")
    
    # Record state after running
    count_after = get_shadow_db_count()
    status_after = get_shadow_db_status_counts()
    
    # Calculate deltas
    inserted_rows = count_after - count_before
    skipped_duplicates = top_5_count - inserted_rows
    
    # The number of newly resolved rows is the difference in RESOLVED count 
    # (assuming no rows are ever deleted)
    resolved_count_delta = status_after.get("RESOLVED", 0) - status_before.get("RESOLVED", 0)
    
    print(f"\n============================================================")
    print("FINAL SUMMARY: V1.12 DAILY SHADOW PIPELINE")
    print(f"============================================================")
    print(f"Scored sample date:  {scored_sample_date}")
    print(f"Ranking rows scored: {ranking_rows}")
    print(f"Shadow tracked Top5%: {top_5_count}")
    print(f"Inserted shadow rows:{inserted_rows}")
    print(f"Skipped duplicates:  {skipped_duplicates}")
    print(f"Newly resolved rows: {resolved_count_delta}")
    print(f"Total observing:     {status_after.get('OBSERVING', 0)}")
    print(f"Total resolved:      {status_after.get('RESOLVED', 0)}")
    print(f"Report JSON path:    /app/data/exports/shadow_performance_summary.json")
    print(f"Report Text path:    /app/data/exports/shadow_performance_report_v1.txt")
    print(f"============================================================\n")

if __name__ == "__main__":
    run_pipeline()
