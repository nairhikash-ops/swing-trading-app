from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from paper_trader_continuity import (
    build_plan,
    fetch_trading_dates,
    read_report_dates,
    write_continuity,
)


def ensure_empty_output_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise RuntimeError(f"Reconstruction output must be a fresh empty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def command_for(strategy: str, base_url: str, output_dir: Path, run_date: str) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    if strategy == "v8_demo":
        script = "scripts/v8_demo_trader.py"
    else:
        script = "app/scripts/uptrend_sideways_paper_trader.py"
        env["PYTHONPATH"] = f"/app/scripts:/app{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return (
        [
            sys.executable, script, "--base-url", base_url, "--output-dir", str(output_dir),
            "--broker", "paper", "--strict-health", "--as-of-date", run_date,
        ],
        env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an immutable, explicitly reconstructed paper ledger.")
    parser.add_argument("--strategy", choices=("v8_demo", "uptrend_sideways"), required=True)
    parser.add_argument("--base-url", default="http://matsya-api:8020")
    parser.add_argument("--from-date", type=date.fromisoformat, required=True)
    parser.add_argument("--to-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date")
    ensure_empty_output_dir(args.output_dir)
    dates = fetch_trading_dates(args.base_url, args.from_date.isoformat(), args.to_date.isoformat())
    if not dates:
        raise RuntimeError("No stored Matsya trading sessions exist in the requested reconstruction range.")

    status_path = args.output_dir / "continuity_status.json"
    for run_date in dates:
        cmd, env = command_for(args.strategy, args.base_url, args.output_dir, run_date)
        print(f"Reconstructing {args.strategy} for {run_date}.")
        if subprocess.call(cmd, env=env) != 0:
            partial = build_plan(read_report_dates(args.output_dir / "daily_report.csv"), dates)
            write_continuity(
                status_path,
                strategy_id=args.strategy,
                plan=replace(partial, status="reconstruction_failed", forward_valid=False),
                replayed_dates=read_report_dates(args.output_dir / "daily_report.csv"),
                message=f"Historical reconstruction failed at {run_date}.",
            )
            return 1

    complete = build_plan(read_report_dates(args.output_dir / "daily_report.csv"), dates)
    write_continuity(
        status_path,
        strategy_id=args.strategy,
        plan=complete,
        replayed_dates=dates,
        message="Historical reconstruction completed; this is not original forward evidence.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
