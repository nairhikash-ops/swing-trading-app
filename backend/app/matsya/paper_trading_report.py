from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_V8_DEMO_DIR = Path(os.environ.get("V8_DEMO_OUTPUT_DIR", "/app/data/v8_demo_trader"))
DEFAULT_UPTREND_SIDEWAYS_DIR = Path(
    os.environ.get("UPTREND_SIDEWAYS_OUTPUT_DIR", "/app/data/uptrend_sideways_paper_trader")
)


class PaperTradingReportService:
    def __init__(
        self,
        v8_output_dir: Path = DEFAULT_V8_DEMO_DIR,
        uptrend_sideways_output_dir: Path = DEFAULT_UPTREND_SIDEWAYS_DIR,
    ) -> None:
        self.v8_output_dir = v8_output_dir
        self.uptrend_sideways_output_dir = uptrend_sideways_output_dir

    def combined_status(self, limit: int = 50) -> dict[str, Any]:
        strategies = [
            strategy_status(
                strategy_id="v8_demo",
                name="V8 Crash-Reversal Demo",
                output_dir=self.v8_output_dir,
                limit=limit,
                signal_count_key="eligible_signals",
            ),
            strategy_status(
                strategy_id="uptrend_sideways",
                name="Uptrend Sideways Branch",
                output_dir=self.uptrend_sideways_output_dir,
                limit=limit,
                signal_count_key="breakout_signals",
                include_watch=True,
            ),
        ]
        return {"summary": aggregate_summary(strategies), "strategies": strategies}


def strategy_status(
    strategy_id: str,
    name: str,
    output_dir: Path,
    limit: int,
    signal_count_key: str,
    include_watch: bool = False,
) -> dict[str, Any]:
    daily_rows = read_csv_tail(output_dir / "daily_report.csv", limit)
    latest = coerce_report(daily_rows[-1] if daily_rows else None)
    state = read_json(output_dir / "paper_broker_state.json", default={})
    fetch_failures = read_json(output_dir / "fetch_failures.json", default={})

    pending_orders = [coerce_numbers(row) for row in list(state.get("pending_orders") or [])]
    open_positions = [coerce_numbers(row) for row in list(state.get("open_positions") or [])]
    closed_trades = [coerce_numbers(row) for row in read_csv_tail(output_dir / "paper_trade_ledger.csv", limit)]
    order_ledger = [coerce_numbers(row) for row in read_csv_tail(output_dir / "paper_order_ledger.csv", limit)]
    signals = [coerce_numbers(row) for row in read_csv_tail(output_dir / "signals.csv", limit)]
    watch_candidates = [coerce_numbers(row) for row in read_csv_tail(output_dir / "watch_candidates.csv", limit)] if include_watch else []

    account = {
        "cash": as_float(state.get("cash")),
        "pending_orders_count": len(pending_orders),
        "open_positions_count": len(open_positions),
        "closed_trades_count": len(closed_trades),
    }
    return {
        "strategy_id": strategy_id,
        "name": name,
        "output_dir": str(output_dir),
        "latest": latest,
        "account": account,
        "pending_orders": pending_orders,
        "open_positions": open_positions,
        "closed_trades": closed_trades,
        "order_ledger": order_ledger,
        "signals": signals,
        "watch_candidates": watch_candidates,
        "daily_reports": [coerce_report(row) for row in daily_rows],
        "fetch_failures": fetch_failures,
        "signal_count_key": signal_count_key,
        "files": {
            "daily_report": file_meta(output_dir / "daily_report.csv"),
            "paper_broker_state": file_meta(output_dir / "paper_broker_state.json"),
            "fetch_failures": file_meta(output_dir / "fetch_failures.json"),
            "paper_trade_ledger": file_meta(output_dir / "paper_trade_ledger.csv"),
            "paper_order_ledger": file_meta(output_dir / "paper_order_ledger.csv"),
            "signals": file_meta(output_dir / "signals.csv"),
            "watch_candidates": file_meta(output_dir / "watch_candidates.csv"),
        },
    }


def aggregate_summary(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    latest_dates = [s.get("latest", {}).get("date") for s in strategies if s.get("latest")]
    return {
        "strategy_count": len(strategies),
        "latest_dates": sorted(set(str(date) for date in latest_dates if date)),
        "total_cash": sum(as_float(s.get("account", {}).get("cash")) for s in strategies),
        "total_pending_orders": sum(int(s.get("account", {}).get("pending_orders_count") or 0) for s in strategies),
        "total_open_positions": sum(int(s.get("account", {}).get("open_positions_count") or 0) for s in strategies),
        "total_closed_trades": sum(int(s.get("account", {}).get("closed_trades_count") or 0) for s in strategies),
        "total_signals_latest": sum(as_float((s.get("latest") or {}).get(s.get("signal_count_key", ""))) for s in strategies),
        "total_orders_placed_latest": sum(as_float((s.get("latest") or {}).get("orders_placed")) for s in strategies),
    }


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_csv_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    if limit <= 0:
        return rows
    return rows[-limit:]


def file_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "size_bytes": 0, "updated_at": None}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": stat.st_size,
        "updated_at": stat.st_mtime,
    }


def coerce_report(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return coerce_numbers(row)


def coerce_numbers(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (int, float)) or value is None:
            out[key] = value
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                out[key] = ""
                continue
            if stripped.lower() in {"true", "false"}:
                out[key] = stripped.lower() == "true"
                continue
            number = parse_number(stripped)
            out[key] = number if number is not None else value
            continue
        out[key] = value
    return out


def parse_number(value: str) -> int | float | None:
    try:
        if "." not in value and "e" not in value.lower():
            return int(value)
        return float(value)
    except ValueError:
        return None


def as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parsed = parse_number(value)
        if parsed is not None:
            return float(parsed)
    return 0.0
