from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen


BASE_URL = "http://matsya-api:8020"
OUTPUT_DIR = Path("/app/data/uptrend_sideways_paper_trader")
DAILY_REPORT = OUTPUT_DIR / "daily_report.csv"


def latest_matsya_date() -> str:
    with urlopen(f"{BASE_URL}/api/matsya/market-data/status", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latest = payload.get("latest_candle_date")
    if not latest:
        raise RuntimeError("Matsya latest_candle_date is empty.")
    return str(latest)


def last_processed_date() -> str | None:
    if not DAILY_REPORT.exists():
        return None
    with DAILY_REPORT.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in reversed(rows):
        if row.get("date"):
            return str(row["date"])
    return None


def main() -> int:
    latest = latest_matsya_date()
    last = last_processed_date()
    if last == latest:
        print(f"Uptrend-sideways paper trader skipped: latest candle {latest} already processed.")
        return 0

    env = os.environ.copy()
    env["PYTHONPATH"] = f"/app/scripts:/app{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    cmd = [
        sys.executable,
        "app/scripts/uptrend_sideways_paper_trader.py",
        "--base-url",
        BASE_URL,
        "--output-dir",
        str(OUTPUT_DIR),
        "--broker",
        "paper",
        "--strict-health",
    ]
    print(f"Uptrend-sideways paper trader running for latest candle {latest}; last processed={last}.")
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
