from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from v7b_matsya_forward_paper_logger import (
    FRICTION_BASE,
    FRICTION_HARSH,
    MatsyaClient,
    fetch_universe_candles,
    latest_candle_for_date,
    round_money,
)


DEFAULT_BASE_URL = "http://100.76.218.124:8020"
DEFAULT_OUTPUT_DIR = Path(r"D:\app\data\exports\uptrend_sideways_paper_trader")
DEFAULT_STARTING_EQUITY = 100000.0
DEFAULT_LOOKBACK_DAYS = 180

BASE_DURATIONS = [10, 15, 20, 30]
BASE_RANGES = [0.06, 0.08, 0.10, 0.12, 0.15]
PRE_RETURN_DAYS = 60
UPTREND_RETURN_MIN = 0.10
BREAKOUT_BUFFER = 1.005
MAX_SLOTS = 5
MAX_HOLDING_BARS = 40


@dataclass(frozen=True)
class SidewaysSignal:
    symbol: str
    signal_date: str
    base_duration: int
    base_range_max: float
    base_start_date: str
    base_end_date: str
    base_high: float
    base_low: float
    base_range_pct: float
    pre_structure_return_60d: float
    breakout_close: float
    target_price: float
    target_allocation: float


class BrokerAdapter(Protocol):
    def load(self) -> None:
        ...

    def save(self) -> None:
        ...

    def process_pending_entries(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[str]:
        ...

    def process_exits(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[dict]:
        ...

    def place_entry_orders(self, orders: list[SidewaysSignal]) -> list[str]:
        ...

    def equity(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> tuple[float, float]:
        ...

    def slots_used(self) -> int:
        ...


class PaperBroker:
    def __init__(self, output_dir: Path, starting_equity: float) -> None:
        self.output_dir = output_dir
        self.state_path = output_dir / "paper_broker_state.json"
        self.trade_ledger_path = output_dir / "paper_trade_ledger.csv"
        self.order_ledger_path = output_dir / "paper_order_ledger.csv"
        self.starting_equity = starting_equity
        self.state: dict = {}

    def load(self) -> None:
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return
        self.state = {"cash": float(self.starting_equity), "pending_orders": [], "open_positions": []}

    def save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def slots_used(self) -> int:
        return len(self.state["pending_orders"]) + len(self.state["open_positions"])

    def process_pending_entries(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[str]:
        filled = []
        remaining = []
        for order in self.state["pending_orders"]:
            if order.get("signal_date") == as_of_date:
                remaining.append(order)
                continue
            candle = latest_candle_for_date(candles_by_symbol, order["symbol"], as_of_date)
            if not candle or pd.isna(candle["open"]):
                remaining.append(order)
                continue

            raw_open = float(candle["open"])
            effective_entry = raw_open * (1 + FRICTION_BASE)
            harsh_entry = raw_open * (1 + FRICTION_HARSH)
            shares = int(float(order["target_allocation"]) / effective_entry)
            if shares <= 0 or shares * effective_entry > self.state["cash"]:
                remaining.append(order)
                continue

            invested = shares * effective_entry
            self.state["cash"] -= invested
            self.state["open_positions"].append(
                {
                    "symbol": order["symbol"],
                    "entry_date": as_of_date,
                    "signal_date": order["signal_date"],
                    "shares": shares,
                    "raw_entry_price": raw_open,
                    "entry_price": effective_entry,
                    "harsh_entry_price": harsh_entry,
                    "base_duration": order["base_duration"],
                    "base_range_max": order["base_range_max"],
                    "base_start_date": order["base_start_date"],
                    "base_end_date": order["base_end_date"],
                    "base_high": order["base_high"],
                    "base_low": order["base_low"],
                    "base_range_pct": order["base_range_pct"],
                    "pre_structure_return_60d": order["pre_structure_return_60d"],
                    "target_price": order["target_price"],
                    "bars_held": 0,
                    "invested_value": invested,
                    "broker_mode": "paper",
                }
            )
            filled.append(order["symbol"])

        self.state["pending_orders"] = remaining
        return filled

    def process_exits(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[dict]:
        closed = []
        remaining = []
        for pos in self.state["open_positions"]:
            candle = latest_candle_for_date(candles_by_symbol, pos["symbol"], as_of_date)
            if not candle:
                remaining.append(pos)
                continue

            pos["bars_held"] += 1
            hit_target = float(candle["high"]) >= float(pos["target_price"])
            hit_base_failure = float(candle["low"]) < float(pos["base_low"])
            reason = ""
            raw_exit_price = 0.0
            if hit_target and hit_base_failure:
                reason = "Base Failure (Ambiguous Day)"
                raw_exit_price = float(pos["base_low"])
            elif hit_base_failure:
                reason = "Base Failure"
                raw_exit_price = float(pos["base_low"])
            elif hit_target:
                reason = "Target Hit"
                raw_exit_price = float(pos["target_price"])
            elif int(pos["bars_held"]) >= MAX_HOLDING_BARS:
                reason = "Time Stop"
                raw_exit_price = float(candle["close"])

            if not reason:
                remaining.append(pos)
                continue

            effective_exit = raw_exit_price * (1 - FRICTION_BASE)
            harsh_exit = raw_exit_price * (1 - FRICTION_HARSH)
            shares = int(pos["shares"])
            pnl_value = (effective_exit - float(pos["entry_price"])) * shares
            self.state["cash"] += shares * effective_exit
            trade = {
                "symbol": pos["symbol"],
                "entry_date": pos["entry_date"],
                "exit_date": as_of_date,
                "reason": reason,
                "bars_held": pos["bars_held"],
                "shares": shares,
                "entry_price": pos["entry_price"],
                "exit_price": effective_exit,
                "pnl_value": pnl_value,
                "pnl_pct": (effective_exit / float(pos["entry_price"])) - 1,
                "harsh_pnl_pct": (harsh_exit / float(pos["harsh_entry_price"])) - 1,
                "base_high": pos["base_high"],
                "base_low": pos["base_low"],
                "target_price": pos["target_price"],
                "broker_mode": "paper",
            }
            closed.append(trade)
            append_csv(self.trade_ledger_path, trade)

        self.state["open_positions"] = remaining
        return closed

    def place_entry_orders(self, orders: list[SidewaysSignal]) -> list[str]:
        placed = []
        existing = {o["symbol"] for o in self.state["pending_orders"]} | {
            p["symbol"] for p in self.state["open_positions"]
        }
        for order in orders:
            if order.symbol in existing:
                continue
            row = {
                "symbol": order.symbol,
                "signal_date": order.signal_date,
                "target_allocation": order.target_allocation,
                "base_duration": order.base_duration,
                "base_range_max": order.base_range_max,
                "base_start_date": order.base_start_date,
                "base_end_date": order.base_end_date,
                "base_high": order.base_high,
                "base_low": order.base_low,
                "base_range_pct": order.base_range_pct,
                "pre_structure_return_60d": order.pre_structure_return_60d,
                "breakout_close": order.breakout_close,
                "target_price": order.target_price,
                "broker_mode": "paper",
            }
            self.state["pending_orders"].append(row)
            append_csv(self.order_ledger_path, row)
            placed.append(order.symbol)
        return placed

    def equity(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> tuple[float, float]:
        open_value = 0.0
        for pos in self.state["open_positions"]:
            candle = latest_candle_for_date(candles_by_symbol, pos["symbol"], as_of_date)
            if candle:
                open_value += int(pos["shares"]) * float(candle["close"]) * (1 - FRICTION_BASE)
            else:
                open_value += float(pos.get("invested_value", 0.0))
        return float(self.state["cash"]) + open_value, open_value


class RealBrokerAdapterDisabled:
    def __init__(self, *_args, **_kwargs) -> None:
        raise RuntimeError("Real broker mode is disabled. This runner is paper-only.")


def append_csv(file_path: Path, row_dict: dict) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([row_dict])
    if file_path.exists():
        row.to_csv(file_path, mode="a", header=False, index=False)
    else:
        row.to_csv(file_path, index=False)


def health_gate(status: dict, symbols_loaded: int, fetch_failures: int, strict: bool) -> list[str]:
    errors = []
    if str(status.get("token_state", "")).lower() != "active":
        errors.append(f"token_state={status.get('token_state')}, expected active")
    if symbols_loaded != 500:
        errors.append(f"symbols_loaded={symbols_loaded}, expected 500")
    if fetch_failures != 0:
        errors.append(f"fetch_failures={fetch_failures}, expected 0")
    if strict and errors:
        raise RuntimeError("Health gate failed: " + "; ".join(errors))
    return errors


def find_latest_uptrend_sideways(symbol: str, df_raw: pd.DataFrame, as_of_date: str) -> dict | None:
    df = df_raw.sort_values("trading_date").reset_index(drop=True)
    as_of_ts = pd.to_datetime(as_of_date)
    if df.empty or df.iloc[-1]["trading_date"] != as_of_ts:
        return None

    latest_idx = len(df) - 1
    best: dict | None = None
    for duration in BASE_DURATIONS:
        base_start_idx = latest_idx - duration
        base_end_idx = latest_idx - 1
        pre_start_idx = base_start_idx - PRE_RETURN_DAYS
        pre_end_idx = base_start_idx - 1
        if pre_start_idx < 0 or base_start_idx < 0:
            continue

        base = df.iloc[base_start_idx:latest_idx]
        latest = df.iloc[latest_idx]
        base_high = float(base["high"].max())
        base_low = float(base["low"].min())
        if base_low <= 0:
            continue
        base_range_pct = (base_high - base_low) / base_low

        pre_start_close = float(df.iloc[pre_start_idx]["close"])
        pre_end_close = float(df.iloc[pre_end_idx]["close"])
        if pre_start_close <= 0:
            continue
        pre_return = (pre_end_close / pre_start_close) - 1
        if pre_return < UPTREND_RETURN_MIN:
            continue

        eligible_ranges = [limit for limit in BASE_RANGES if base_range_pct <= limit]
        if not eligible_ranges:
            continue

        broke_up = float(latest["high"]) > base_high
        broke_down = float(latest["low"]) < base_low
        breakout_close_confirmed = float(latest["close"]) >= base_high * BREAKOUT_BUFFER
        near_breakout = float(latest["close"]) >= base_high * 0.98 and not broke_down
        in_base = float(latest["low"]) >= base_low and float(latest["close"]) <= base_high

        status = None
        if broke_up and broke_down:
            status = "same_day_both"
        elif broke_up and breakout_close_confirmed:
            status = "upward_breakout"
        elif near_breakout:
            status = "near_breakout_watch"
        elif in_base:
            status = "in_base_watch"
        if status is None:
            continue

        row = {
            "symbol": symbol,
            "as_of_date": as_of_date,
            "status": status,
            "base_duration": duration,
            "base_range_max": min(eligible_ranges),
            "base_start_date": df.iloc[base_start_idx]["trading_date"].strftime("%Y-%m-%d"),
            "base_end_date": df.iloc[base_end_idx]["trading_date"].strftime("%Y-%m-%d"),
            "base_high": round_money(base_high),
            "base_low": round_money(base_low),
            "base_range_pct": base_range_pct,
            "pre_structure_return_60d": pre_return,
            "latest_close": float(latest["close"]),
            "latest_high": float(latest["high"]),
            "latest_low": float(latest["low"]),
            "target_price": round_money(base_high * 1.10),
        }
        if best is None or (row["status"] == "upward_breakout" and best["status"] != "upward_breakout"):
            best = row

    return best


def run(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    client = MatsyaClient(args.base_url, args.timeout)
    status = client.status()
    as_of_date = args.as_of_date or status.get("latest_candle_date")
    if not as_of_date:
        raise RuntimeError("Matsya did not report latest_candle_date and --as-of-date was not supplied.")

    candles_by_symbol, fetch_meta = fetch_universe_candles(client, args.lookback_days, args.max_workers)
    as_of_ts = pd.to_datetime(as_of_date)
    candles_by_symbol = {
        symbol: df[df["trading_date"] <= as_of_ts].copy().reset_index(drop=True)
        for symbol, df in candles_by_symbol.items()
    }
    candles_by_symbol = {symbol: df for symbol, df in candles_by_symbol.items() if not df.empty}
    fetch_failures = len(fetch_meta["fetch_failures"])
    health_errors = health_gate(status, len(candles_by_symbol), fetch_failures, strict=args.strict_health)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fetch_failures.json").write_text(
        json.dumps(
            {
                "as_of_date": as_of_date,
                "base_url": args.base_url,
                "symbols_requested": fetch_meta["symbols_requested"],
                "symbols_loaded": len(candles_by_symbol),
                "fetch_failures": fetch_meta["fetch_failures"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    watch_rows = []
    breakout_rows = []
    for symbol, df in candles_by_symbol.items():
        row = find_latest_uptrend_sideways(symbol, df, as_of_date)
        if row is None:
            continue
        watch_rows.append(row)
        if row["status"] == "upward_breakout":
            breakout_rows.append(row)

    if watch_rows:
        pd.DataFrame(watch_rows).to_csv(
            output_dir / "watch_candidates.csv",
            mode="a",
            header=not (output_dir / "watch_candidates.csv").exists(),
            index=False,
        )
    if breakout_rows:
        pd.DataFrame(breakout_rows).to_csv(
            output_dir / "signals.csv",
            mode="a",
            header=not (output_dir / "signals.csv").exists(),
            index=False,
        )

    if args.broker != "paper":
        RealBrokerAdapterDisabled()
    broker: BrokerAdapter = PaperBroker(output_dir, args.starting_equity)
    broker.load()
    filled = [] if args.dry_run else broker.process_pending_entries(candles_by_symbol, as_of_date)
    closed = [] if args.dry_run else broker.process_exits(candles_by_symbol, as_of_date)
    equity, open_value = broker.equity(candles_by_symbol, as_of_date)

    placed: list[str] = []
    if not args.dry_run and breakout_rows:
        slots_available = max(0, MAX_SLOTS - broker.slots_used())
        if slots_available > 0:
            target_allocation = equity / MAX_SLOTS
            orders = [
                SidewaysSignal(
                    symbol=row["symbol"],
                    signal_date=as_of_date,
                    base_duration=int(row["base_duration"]),
                    base_range_max=float(row["base_range_max"]),
                    base_start_date=row["base_start_date"],
                    base_end_date=row["base_end_date"],
                    base_high=float(row["base_high"]),
                    base_low=float(row["base_low"]),
                    base_range_pct=float(row["base_range_pct"]),
                    pre_structure_return_60d=float(row["pre_structure_return_60d"]),
                    breakout_close=float(row["latest_close"]),
                    target_price=float(row["target_price"]),
                    target_allocation=target_allocation,
                )
                for row in breakout_rows[:slots_available]
            ]
            placed = broker.place_entry_orders(orders)
        broker.save()

    report = {
        "date": as_of_date,
        "broker": args.broker,
        "dry_run": bool(args.dry_run),
        "equity": round(equity, 2),
        "cash": round(float(getattr(broker, "state", {}).get("cash", 0.0)), 2),
        "open_value": round(open_value, 2),
        "open_positions": len(getattr(broker, "state", {}).get("open_positions", [])),
        "pending_orders": len(getattr(broker, "state", {}).get("pending_orders", [])),
        "filled_today": len(filled),
        "closed_today": len(closed),
        "watch_candidates": len(watch_rows),
        "breakout_signals": len(breakout_rows),
        "orders_placed": len(placed),
        "matsya_latest_candle_date": status.get("latest_candle_date"),
        "matsya_token_state": status.get("token_state"),
        "symbols_loaded": len(candles_by_symbol),
        "fetch_failures": fetch_failures,
        "health_errors": "|".join(health_errors),
    }
    append_csv(output_dir / "daily_report.csv", report)
    print(
        f"[{as_of_date}] watch={len(watch_rows)} breakouts={len(breakout_rows)} "
        f"placed={placed} open={report['open_positions']} pending={report['pending_orders']} "
        f"dry_run={args.dry_run}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper-only uptrend-sideways branch runner.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--starting-equity", type=float, default=DEFAULT_STARTING_EQUITY)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--broker", choices=["paper", "dhan"], default="paper")
    parser.add_argument("--strict-health", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
