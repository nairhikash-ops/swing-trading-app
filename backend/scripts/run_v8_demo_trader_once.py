from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

BASE_URL = "http://matsya-api:8020"
OUTPUT_DIR = Path("/app/data/v8_demo_trader")
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
        print(f"V8 demo trader skipped: latest candle {latest} already processed.")
        return 0
    cmd = [
        sys.executable,
        "scripts/v8_demo_trader.py",
        "--base-url",
        BASE_URL,
        "--output-dir",
        str(OUTPUT_DIR),
        "--broker",
        "paper",
        "--strict-health",
    ]
    print(f"V8 demo trader running for latest candle {latest}; last processed={last}.")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
