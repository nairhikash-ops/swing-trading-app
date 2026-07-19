from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from paper_trader_continuity import (
    build_plan,
    fetch_latest_date,
    fetch_trading_dates,
    read_report_dates,
    write_continuity,
)


BASE_URL = "http://matsya-api:8020"
OUTPUT_DIR = Path("/app/data/uptrend_sideways_paper_trader")
DAILY_REPORT = OUTPUT_DIR / "daily_report.csv"
CONTINUITY_STATUS = OUTPUT_DIR / "continuity_status.json"


def main() -> int:
    latest = fetch_latest_date(BASE_URL)
    processed = read_report_dates(DAILY_REPORT)
    start = min(processed) if processed else latest
    plan = build_plan(processed, fetch_trading_dates(BASE_URL, start, latest))
    if not plan.forward_valid:
        write_continuity(
            CONTINUITY_STATUS,
            strategy_id="uptrend_sideways",
            plan=plan,
            message="Ledger continuity is invalid; automatic processing refused until a new epoch is started.",
        )
        print(
            f"Uptrend-sideways continuity invalid; status={plan.status} "
            f"missing={list(plan.missing_dates)} duplicates={list(plan.duplicate_dates)}"
        )
        return 2

    env = os.environ.copy()
    env["PYTHONPATH"] = f"/app/scripts:/app{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    replayed = list(plan.run_dates) if len(plan.run_dates) > 1 else []
    for run_date in plan.run_dates:
        cmd = [
            sys.executable, "app/scripts/uptrend_sideways_paper_trader.py", "--base-url", BASE_URL,
            "--output-dir", str(OUTPUT_DIR), "--broker", "paper", "--strict-health",
            "--as-of-date", run_date,
        ]
        print(f"Uptrend-sideways paper trader running for candle {run_date}; latest={latest}.")
        if subprocess.call(cmd, env=env) != 0:
            write_continuity(CONTINUITY_STATUS, strategy_id="uptrend_sideways", plan=plan, message=f"Replay failed at {run_date}.")
            return 1

    final_processed = read_report_dates(DAILY_REPORT)
    final_plan = build_plan(final_processed, fetch_trading_dates(BASE_URL, min(final_processed), latest))
    write_continuity(
        CONTINUITY_STATUS, strategy_id="uptrend_sideways", plan=final_plan, replayed_dates=replayed,
        message="All stored trading sessions in this epoch are present.",
    )
    if not plan.run_dates:
        print(f"Uptrend-sideways paper trader skipped: latest candle {latest} already processed with complete continuity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
