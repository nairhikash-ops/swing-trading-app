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
    MAX_SLOTS,
    MatsyaClient,
    build_market_returns,
    fetch_universe_candles,
    generate_signals,
    latest_candle_for_date,
    round_money,
)


DEFAULT_BASE_URL = "http://100.76.218.124:8020"
DEFAULT_OUTPUT_DIR = Path(r"D:\app\data\exports\v8_demo_trader")
DEFAULT_STARTING_EQUITY = 100000.0
DEFAULT_LOOKBACK_DAYS = 420


@dataclass(frozen=True)
class DemoOrder:
    symbol: str
    signal_date: str
    target_allocation: float
    liquidity_cap: float
    down_market_capture_60d: float


class BrokerAdapter(Protocol):
    def load(self) -> None:
        ...

    def save(self) -> None:
        ...

    def process_pending_entries(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[str]:
        ...

    def process_exits(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[dict]:
        ...

    def place_entry_orders(self, orders: list[DemoOrder]) -> list[str]:
        ...

    def equity(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> tuple[float, float]:
        ...

    def slots_used(self) -> int:
        ...


class PaperBroker:
    def __init__(self, output_dir: Path, starting_equity: float) -> None:
        self.output_dir = output_dir
        self.state_path = output_dir / "paper_broker_state.json"
        self.ledger_path = output_dir / "paper_trade_ledger.csv"
        self.orders_path = output_dir / "paper_order_ledger.csv"
        self.starting_equity = starting_equity
        self.state: dict = {}

    def load(self) -> None:
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return
        self.state = {
            "cash": float(self.starting_equity),
            "pending_orders": [],
            "open_positions": [],
        }

    def save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def slots_used(self) -> int:
        return len(self.state["pending_orders"]) + len(self.state["open_positions"])

    def process_pending_entries(self, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[str]:
        filled = []
        remaining = []
        for order in self.state["pending_orders"]:
            candle = latest_candle_for_date(candles_by_symbol, order["symbol"], as_of_date)
            if not candle or pd.isna(candle["open"]):
                remaining.append(order)
                continue

            raw_open = float(candle["open"])
            effective_entry = raw_open * (1 + FRICTION_BASE)
            harsh_entry = raw_open * (1 + FRICTION_HARSH)
            position_value = min(float(order["target_allocation"]), float(order["liquidity_cap"]))
            shares = int(position_value / effective_entry)
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
                    "target_price": round_money(raw_open * 1.10),
                    "stop_price": round_money(raw_open * 0.95),
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
            hit_stop = float(candle["low"]) <= float(pos["stop_price"])
            reason = ""
            raw_exit_price = 0.0
            if hit_stop and hit_target:
                reason = "Stop (Ambiguous Day)"
                raw_exit_price = float(pos["stop_price"])
            elif hit_stop:
                reason = "Stop Loss"
                raw_exit_price = float(pos["stop_price"])
            elif hit_target:
                reason = "Target Hit"
                raw_exit_price = float(pos["target_price"])
            elif pos["bars_held"] >= 20:
                reason = "Time Stop"
                raw_exit_price = float(candle["close"])

            if not reason:
                remaining.append(pos)
                continue

            effective_exit = raw_exit_price * (1 - FRICTION_BASE)
            harsh_exit = raw_exit_price * (1 - FRICTION_HARSH)
            pnl_value = (effective_exit - float(pos["entry_price"])) * int(pos["shares"])
            self.state["cash"] += int(pos["shares"]) * effective_exit
            trade = {
                "symbol": pos["symbol"],
                "entry_date": pos["entry_date"],
                "exit_date": as_of_date,
                "reason": reason,
                "bars_held": pos["bars_held"],
                "shares": pos["shares"],
                "entry_price": pos["entry_price"],
                "exit_price": effective_exit,
                "pnl_value": pnl_value,
                "pnl_pct": (effective_exit / float(pos["entry_price"])) - 1,
                "harsh_pnl_pct": (harsh_exit / float(pos["harsh_entry_price"])) - 1,
                "broker_mode": "paper",
            }
            closed.append(trade)
            append_csv(self.ledger_path, trade)

        self.state["open_positions"] = remaining
        return closed

    def place_entry_orders(self, orders: list[DemoOrder]) -> list[str]:
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
                "liquidity_cap": order.liquidity_cap,
                "down_market_capture_60d": order.down_market_capture_60d,
                "broker_mode": "paper",
            }
            self.state["pending_orders"].append(row)
            append_csv(self.orders_path, row)
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
        raise RuntimeError(
            "Real broker mode is intentionally disabled. Implement a BrokerAdapter for Dhan only after "
            "the paper-trading promotion gate is explicitly approved."
        )


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


def run_demo(args: argparse.Namespace) -> None:
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

    fetch_failure_path = output_dir / "fetch_failures.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    fetch_failure_path.write_text(
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

    if args.broker != "paper":
        RealBrokerAdapterDisabled()
    broker: BrokerAdapter = PaperBroker(output_dir, args.starting_equity)
    broker.load()

    filled = broker.process_pending_entries(candles_by_symbol, as_of_date)
    closed = broker.process_exits(candles_by_symbol, as_of_date)
    equity, open_value = broker.equity(candles_by_symbol, as_of_date)

    market_df = build_market_returns(candles_by_symbol)
    signals = generate_signals(candles_by_symbol, market_df, as_of_date)
    placed: list[str] = []
    if not signals.empty:
        slots_available = max(0, MAX_SLOTS - broker.slots_used())
        if slots_available > 0:
            target_allocation = equity / MAX_SLOTS
            selected = signals.head(slots_available)
            orders = [
                DemoOrder(
                    symbol=str(row["symbol"]),
                    signal_date=as_of_date,
                    target_allocation=target_allocation,
                    liquidity_cap=float(row["liquidity_cap"]),
                    down_market_capture_60d=float(row["down_market_capture_60d"]),
                )
                for _, row in selected.iterrows()
            ]
            placed = broker.place_entry_orders(orders)
        signal_out = signals.copy()
        signal_out["as_of_date"] = as_of_date
        signal_out.to_csv(output_dir / "signals.csv", mode="a", header=not (output_dir / "signals.csv").exists(), index=False)

    broker.save()

    report = {
        "date": as_of_date,
        "broker": args.broker,
        "equity": round(equity, 2),
        "cash": round(float(getattr(broker, "state", {}).get("cash", 0.0)), 2),
        "open_value": round(open_value, 2),
        "open_positions": len(getattr(broker, "state", {}).get("open_positions", [])),
        "pending_orders": len(getattr(broker, "state", {}).get("pending_orders", [])),
        "filled_today": len(filled),
        "closed_today": len(closed),
        "eligible_signals": 0 if signals.empty else len(signals),
        "orders_placed": len(placed),
        "matsya_latest_candle_date": status.get("latest_candle_date"),
        "matsya_token_state": status.get("token_state"),
        "symbols_loaded": len(candles_by_symbol),
        "fetch_failures": fetch_failures,
        "health_errors": "|".join(health_errors),
    }
    append_csv(output_dir / "daily_report.csv", report)

    print(
        f"[{as_of_date}] broker={args.broker} equity={equity:.2f} open={report['open_positions']} "
        f"pending={report['pending_orders']} closed={len(closed)} signals={report['eligible_signals']} "
        f"placed={placed}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="V8 demo trader with broker-adapter boundary.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--starting-equity", type=float, default=DEFAULT_STARTING_EQUITY)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--broker", choices=["paper", "dhan"], default="paper")
    parser.add_argument("--strict-health", action="store_true")
    args = parser.parse_args()
    run_demo(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
