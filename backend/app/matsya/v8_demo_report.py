from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_V8_DEMO_DIR = Path(os.environ.get("V8_DEMO_OUTPUT_DIR", "/app/data/v8_demo_trader"))


class V8DemoReportService:
    def __init__(self, output_dir: Path = DEFAULT_V8_DEMO_DIR) -> None:
        self.output_dir = output_dir

    def status(self, limit: int = 50) -> dict[str, Any]:
        daily_rows = read_csv_tail(self.output_dir / "daily_report.csv", limit)
        latest = daily_rows[-1] if daily_rows else None
        state = read_json(self.output_dir / "paper_broker_state.json", default={})
        fetch_failures = read_json(self.output_dir / "fetch_failures.json", default={})
        pending_orders = list(state.get("pending_orders") or [])
        open_positions = list(state.get("open_positions") or [])
        closed_trades = read_csv_tail(self.output_dir / "paper_trade_ledger.csv", limit)
        order_ledger = read_csv_tail(self.output_dir / "paper_order_ledger.csv", limit)
        signals = read_csv_tail(self.output_dir / "signals.csv", limit)
        return {
            "output_dir": str(self.output_dir),
            "files": {
                "daily_report": file_meta(self.output_dir / "daily_report.csv"),
                "paper_broker_state": file_meta(self.output_dir / "paper_broker_state.json"),
                "fetch_failures": file_meta(self.output_dir / "fetch_failures.json"),
                "paper_trade_ledger": file_meta(self.output_dir / "paper_trade_ledger.csv"),
                "paper_order_ledger": file_meta(self.output_dir / "paper_order_ledger.csv"),
                "signals": file_meta(self.output_dir / "signals.csv"),
            },
            "latest": coerce_report(latest),
            "daily_reports": [coerce_report(row) for row in daily_rows],
            "account": {
                "cash": as_float(state.get("cash")),
                "pending_orders_count": len(pending_orders),
                "open_positions_count": len(open_positions),
            },
            "pending_orders": [coerce_numbers(row) for row in pending_orders],
            "open_positions": [coerce_numbers(row) for row in open_positions],
            "closed_trades": [coerce_numbers(row) for row in closed_trades],
            "order_ledger": [coerce_numbers(row) for row in order_ledger],
            "signals": [coerce_numbers(row) for row in signals],
            "fetch_failures": fetch_failures,
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
    return rows[-limit:] if limit > 0 else rows


def file_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "size_bytes": 0, "updated_at": None}
    stat = path.stat()
    return {"exists": True, "path": str(path), "size_bytes": stat.st_size, "updated_at": stat.st_mtime}


def coerce_report(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else coerce_numbers(row)


def coerce_numbers(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (int, float)) or value is None:
            out[key] = value
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                out[key] = ""
            elif stripped.lower() in {"true", "false"}:
                out[key] = stripped.lower() == "true"
            else:
                number = parse_number(stripped)
                out[key] = number if number is not None else value
        else:
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
