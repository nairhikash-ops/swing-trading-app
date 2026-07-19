from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.matsya.intraday_paper import intraday_dashboard_state


DEFAULT_V8_DEMO_DIR = Path(os.environ.get("V8_DEMO_OUTPUT_DIR", "/app/data/v8_demo_trader"))
DEFAULT_UPTREND_SIDEWAYS_DIR = Path(
    os.environ.get("UPTREND_SIDEWAYS_OUTPUT_DIR", "/app/data/uptrend_sideways_paper_trader")
)

STRATEGY_SCHEDULES = {
    "v8_demo": "07:30 IST, Monday-Saturday",
    "uptrend_sideways": "19:20 IST, Monday-Friday",
}


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
                include_watch=True,
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
        intraday = aggregate_intraday(strategies)
        return {
            "mode": "forward_paper_walk_forward",
            "leakage_guard": (
                "date-locked signals; entries require the first valid next-session live price"
                if intraday["enabled"]
                else "date-locked candles only; entries fill next open"
            ),
            "summary": aggregate_summary(strategies),
            "intraday": intraday,
            "strategies": strategies,
        }


def strategy_status(
    strategy_id: str,
    name: str,
    output_dir: Path,
    limit: int,
    signal_count_key: str,
    include_watch: bool = False,
) -> dict[str, Any]:
    daily_rows_all = read_csv_rows(output_dir / "daily_report.csv")
    daily_rows = tail_rows(daily_rows_all, limit)
    latest = coerce_report(daily_rows[-1] if daily_rows else None)
    state = read_json(output_dir / "paper_broker_state.json", default={})
    fetch_failures = read_json(output_dir / "fetch_failures.json", default={})
    continuity = read_json(
        output_dir / "continuity_status.json",
        default={
            "status": "unknown",
            "forward_valid": False,
            "missing_dates": [],
            "message": "Continuity has not been checked by the current runner.",
        },
    )

    pending_orders = tag_rows(
        [derive_movement_fields(coerce_numbers(row)) for row in list(state.get("pending_orders") or [])],
        strategy_id,
        name,
    )
    open_positions = tag_rows(
        [derive_movement_fields(coerce_numbers(row)) for row in list(state.get("open_positions") or [])],
        strategy_id,
        name,
    )
    order_ledger_all = tag_rows(
        [derive_movement_fields(coerce_numbers(row)) for row in read_csv_rows(output_dir / "paper_order_ledger.csv")],
        strategy_id,
        name,
    )
    order_ledger = tail_rows(order_ledger_all, limit)
    closed_trade_rows_all = attach_missing_signal_dates(
        read_csv_rows(output_dir / "paper_trade_ledger.csv"),
        order_ledger_all,
    )
    closed_trades_all = tag_rows(
        [derive_movement_fields(coerce_numbers(row)) for row in closed_trade_rows_all],
        strategy_id,
        name,
    )
    closed_trades = tail_rows(closed_trades_all, limit)
    signals = [derive_movement_fields(coerce_numbers(row)) for row in read_csv_tail(output_dir / "signals.csv", limit)]
    watch_candidates = [derive_movement_fields(coerce_numbers(row)) for row in read_csv_tail(output_dir / "watch_candidates.csv", limit)] if include_watch else []

    account = account_metrics(
        state=state,
        latest=latest,
        daily_rows=[coerce_report(row) for row in daily_rows_all],
        open_positions=open_positions,
        closed_trades=closed_trades_all,
        pending_orders=pending_orders,
    )
    daily_meta = file_meta(output_dir / "daily_report.csv")
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
        "continuity": continuity,
        "signal_count_key": signal_count_key,
        "schedule": STRATEGY_SCHEDULES.get(strategy_id, "-"),
        "last_run_at": timestamp_text(daily_meta.get("updated_at")),
        "intraday": intraday_dashboard_state(state),
        "files": {
            "daily_report": daily_meta,
            "paper_broker_state": file_meta(output_dir / "paper_broker_state.json"),
            "fetch_failures": file_meta(output_dir / "fetch_failures.json"),
            "paper_trade_ledger": file_meta(output_dir / "paper_trade_ledger.csv"),
            "paper_order_ledger": file_meta(output_dir / "paper_order_ledger.csv"),
            "signals": file_meta(output_dir / "signals.csv"),
            "watch_candidates": file_meta(output_dir / "watch_candidates.csv"),
            "continuity_status": file_meta(output_dir / "continuity_status.json"),
        },
    }


def aggregate_intraday(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    states = [dict(strategy.get("intraday") or {}) for strategy in strategies]
    statuses = [str(state.get("feed_status") or "disabled") for state in states]
    if "recovery_failed" in statuses:
        feed_status = "recovery_failed"
    elif "reconnecting" in statuses:
        feed_status = "reconnecting"
    elif "live" in statuses:
        feed_status = "live"
    elif "idle" in statuses:
        feed_status = "idle"
    else:
        feed_status = statuses[0] if statuses else "disabled"
    return {
        "enabled": any(bool(state.get("enabled")) for state in states),
        "feed_status": feed_status,
        "subscription_count": max((int(state.get("subscription_count") or 0) for state in states), default=0),
        "pending_entries": sum(int(state.get("pending_entries") or 0) for state in states),
        "open_positions": sum(int(state.get("open_positions") or 0) for state in states),
        "missed_entries": sum(len(state.get("missed_entries") or []) for state in states),
        "reconnects": max((int(state.get("reconnects") or 0) for state in states), default=0),
        "last_packet_at": max((str(state.get("last_packet_at") or "") for state in states), default="") or None,
        "last_reconciliation_at": max(
            (str(state.get("last_reconciliation_at") or "") for state in states), default=""
        ) or None,
        "recovery_status": next(
            (str(state.get("recovery_status")) for state in states if state.get("recovery_status")), "pending"
        ),
        "stops": [row for state in states for row in list(state.get("stops") or [])],
        "targets": [row for state in states for row in list(state.get("targets") or [])],
    }


def aggregate_summary(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    latest_dates = [s.get("latest", {}).get("date") for s in strategies if s.get("latest")]
    accounts = [s.get("account", {}) for s in strategies]
    starting_equity = sum(as_float(account.get("starting_equity")) for account in accounts)
    total_equity = sum(as_float(account.get("equity")) for account in accounts)
    total_pnl = total_equity - starting_equity
    return {
        "strategy_count": len(strategies),
        "latest_dates": sorted(set(str(date) for date in latest_dates if date)),
        "starting_equity": starting_equity,
        "total_equity": total_equity,
        "total_cash": sum(as_float(account.get("cash")) for account in accounts),
        "total_open_value": sum(as_float(account.get("open_value")) for account in accounts),
        "total_cost_basis": sum(as_float(account.get("cost_basis")) for account in accounts),
        "total_realized_pnl": sum(as_float(account.get("realized_pnl")) for account in accounts),
        "total_unrealized_pnl": sum(as_float(account.get("unrealized_pnl")) for account in accounts),
        "total_pnl": total_pnl,
        "total_return_pct": total_pnl / starting_equity if starting_equity > 0 else 0.0,
        "total_pending_orders": sum(int(account.get("pending_orders_count") or 0) for account in accounts),
        "total_open_positions": sum(int(account.get("open_positions_count") or 0) for account in accounts),
        "total_closed_trades": sum(int(account.get("closed_trades_count") or 0) for account in accounts),
        "total_signals_latest": sum(as_float((s.get("latest") or {}).get(s.get("signal_count_key", ""))) for s in strategies),
        "total_watch_candidates_latest": sum(as_float((s.get("latest") or {}).get("watch_candidates")) for s in strategies),
        "total_orders_placed_latest": sum(as_float((s.get("latest") or {}).get("orders_placed")) for s in strategies),
    }


def account_metrics(
    *,
    state: dict[str, Any],
    latest: dict[str, Any] | None,
    daily_rows: list[dict[str, Any] | None],
    open_positions: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    pending_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    reports = [row for row in daily_rows if row]
    equity_values = [as_float(row.get("equity")) for row in reports if as_float(row.get("equity")) > 0]
    equity = as_float((latest or {}).get("equity"))
    starting_equity = equity_values[0] if equity_values else equity
    cash = as_float(state.get("cash"))
    open_value = as_float((latest or {}).get("open_value"))
    cost_basis = sum(as_float(row.get("invested_value")) for row in open_positions)
    realized_values = [as_float(row.get("pnl_value")) for row in closed_trades]
    realized_pnl = sum(realized_values)
    unrealized_pnl = open_value - cost_basis
    total_pnl = equity - starting_equity
    wins = [row for row in closed_trades if as_float(row.get("pnl_value")) > 0]
    losses = [row for row in closed_trades if as_float(row.get("pnl_value")) < 0]
    gross_profit = sum(as_float(row.get("pnl_value")) for row in wins)
    gross_loss = abs(sum(as_float(row.get("pnl_value")) for row in losses))
    return {
        "cash": cash,
        "starting_equity": starting_equity,
        "equity": equity,
        "open_value": open_value,
        "cost_basis": cost_basis,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "return_pct": total_pnl / starting_equity if starting_equity > 0 else 0.0,
        "exposure_pct": open_value / equity if equity > 0 else 0.0,
        "pending_orders_count": len(pending_orders),
        "open_positions_count": len(open_positions),
        "closed_trades_count": len(closed_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed_trades) if closed_trades else 0.0,
        "average_win_pct": average([as_float(row.get("pnl_pct")) for row in wins]),
        "average_loss_pct": average([as_float(row.get("pnl_pct")) for row in losses]),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_drawdown_pct": max_drawdown(equity_values),
    }


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def max_drawdown(values: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        if value <= 0:
            continue
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def tag_rows(rows: list[dict[str, Any]], strategy_id: str, strategy_name: str) -> list[dict[str, Any]]:
    for row in rows:
        row.setdefault("strategy", strategy_name)
        row.setdefault("strategy_id", strategy_id)
    return rows


def attach_missing_signal_dates(
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[str]] = {}
    for order in orders:
        symbol = str(order.get("symbol") or "")
        signal_date = str(order.get("signal_date") or "")
        if symbol and signal_date:
            by_symbol.setdefault(symbol, []).append(signal_date)
    for dates in by_symbol.values():
        dates.sort()

    enriched = []
    for trade in trades:
        row = dict(trade)
        if not row.get("signal_date"):
            entry_date = str(row.get("entry_date") or "")
            candidates = [
                value
                for value in by_symbol.get(str(row.get("symbol") or ""), [])
                if value <= entry_date
            ]
            if candidates:
                row["signal_date"] = candidates[-1]
        enriched.append(row)
    return enriched


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_csv_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    return tail_rows(read_csv_rows(path), limit)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [normalize_legacy_scan_row(row) for row in csv.DictReader(handle)]
    except Exception:
        return []
    return rows


def tail_rows(rows: list[Any], limit: int) -> list[Any]:
    if limit <= 0:
        return rows
    return rows[-limit:]


def normalize_legacy_scan_row(row: dict[str | None, Any]) -> dict[str, Any]:
    normalized = {str(key): value for key, value in row.items() if key is not None}
    extras = row.get(None)
    if (
        isinstance(extras, list)
        and len(extras) == 2
        and "target_price" in normalized
        and "move_from_base_high_pct" not in normalized
    ):
        normalized["move_from_base_high_pct"] = normalized.get("target_price")
        normalized["move_from_base_low_pct"] = extras[0]
        normalized["target_price"] = extras[1]
    return normalized


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


def timestamp_text(value: Any) -> str | None:
    timestamp = as_float(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


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


def derive_movement_fields(row: dict[str, Any]) -> dict[str, Any]:
    latest_close = as_float(row.get("latest_close"))
    if latest_close > 0:
        base_high = as_float(row.get("base_high"))
        base_low = as_float(row.get("base_low"))
        reaction_high = as_float(row.get("reaction_high_price"))
        crash_low = as_float(row.get("crash_low_price"))
        higher_low = as_float(row.get("higher_low_price"))
        if base_high > 0:
            row.setdefault("move_from_base_high_pct", latest_close / base_high - 1)
        if base_low > 0:
            row.setdefault("move_from_base_low_pct", latest_close / base_low - 1)
        if reaction_high > 0:
            row.setdefault("move_from_reaction_high_pct", latest_close / reaction_high - 1)
        if crash_low > 0:
            row.setdefault("move_from_crash_low_pct", latest_close / crash_low - 1)
        if higher_low > 0:
            row.setdefault("move_from_higher_low_pct", latest_close / higher_low - 1)
    entry_price = as_float(row.get("entry_price"))
    exit_price = as_float(row.get("exit_price"))
    if entry_price > 0 and exit_price > 0:
        row.setdefault("realized_move_pct", exit_price / entry_price - 1)
    return row


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
