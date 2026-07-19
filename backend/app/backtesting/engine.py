from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .data import validate_candles
from .metrics import calculate_metrics
from .models import BacktestConfig, Signal
from .strategy import Strategy


@dataclass
class BacktestResult:
    summary: dict[str, Any]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    signals: pd.DataFrame
    manifest: dict[str, Any]

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=False)
        self.trades.to_csv(output_dir / "trades.csv", index=False)
        self.equity_curve.assign(date=self.equity_curve["date"].dt.strftime("%Y-%m-%d")).to_csv(
            output_dir / "equity_curve.csv", index=False
        )
        self.signals.to_csv(output_dir / "signals.csv", index=False)
        (output_dir / "summary.json").write_text(json.dumps(self.summary, indent=2), encoding="utf-8")
        (output_dir / "run_manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    @property
    def _cost_rate(self) -> float:
        return (self.config.commission_bps + self.config.taxes_bps) / 10_000.0

    @property
    def _slippage_rate(self) -> float:
        return self.config.slippage_bps / 10_000.0

    def run(self, candles: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        data = validate_candles(candles)
        prepared = strategy.prepare(data.copy())
        signals = strategy.generate_signals(prepared)
        self._validate_signals(signals, data)
        signal_rows = [self._signal_row(signal) for signal in signals]
        signal_frame = pd.DataFrame(signal_rows)
        if not signal_frame.empty:
            signal_frame["signal_date"] = pd.to_datetime(signal_frame["signal_date"]).dt.normalize()
            signal_frame = signal_frame.sort_values(["signal_date", "score", "symbol"], ascending=[True, False, True])

        cash = float(self.config.initial_cash)
        positions: dict[str, dict[str, Any]] = {}
        pending: dict[str, dict[str, Any]] = {}
        trades: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []
        signal_dates = {} if signal_frame.empty else {
            date: group.to_dict("records") for date, group in signal_frame.groupby("signal_date", sort=False)
        }

        for session_index, (date, day) in enumerate(data.groupby("date", sort=True)):
            bars = day.set_index("symbol").to_dict("index")
            for symbol in sorted(list(pending), key=lambda item: (-float(pending[item]["score"]), item)):
                order = pending[symbol]
                if session_index - int(order["submitted_session_index"]) > int(order["entry_valid_bars"]):
                    pending.pop(symbol)
                    continue
                if symbol in positions or symbol not in bars or len(positions) >= self.config.max_positions:
                    continue
                order = pending.pop(symbol)
                bar = bars[symbol]
                entry = float(bar["open"]) * (1 + self._slippage_rate)
                stop = float(order["stop_price"])
                target = float(order["target_price"])
                if not stop < entry < target:
                    continue
                marked_equity = cash + sum(
                    pos["quantity"] * float(bars.get(sym, {}).get("close", pos["last_close"]))
                    for sym, pos in positions.items()
                )
                allocation_qty = int(marked_equity * self.config.max_allocation_pct / entry)
                risk_qty = int(marked_equity * self.config.risk_per_trade_pct / (entry - stop))
                affordable_qty = int(cash / (entry * (1 + self._cost_rate)))
                quantity = min(allocation_qty, risk_qty, affordable_qty)
                if quantity <= 0:
                    continue
                entry_notional = quantity * entry
                entry_costs = entry_notional * self._cost_rate
                cash -= entry_notional + entry_costs
                positions[symbol] = {
                    **order,
                    "entry_date": date,
                    "entry_price": entry,
                    "quantity": quantity,
                    "entry_costs": entry_costs,
                    "bars_held": 0,
                    "last_close": entry,
                }

            for symbol in sorted(list(positions)):
                if symbol not in bars:
                    continue
                pos = positions[symbol]
                bar = bars[symbol]
                pos["bars_held"] += 1
                pos["last_close"] = float(bar["close"])
                reason, raw_exit = self._exit_for_bar(pos, bar)
                if reason:
                    cash += self._close_position(pos, symbol, date, raw_exit, reason, trades)
                    del positions[symbol]

            for row in signal_dates.get(date, []):
                symbol = str(row["symbol"])
                if symbol not in positions:
                    row["submitted_session_index"] = session_index
                    current = pending.get(symbol)
                    if current is None or float(row["score"]) > float(current["score"]):
                        pending[symbol] = row

            market_value = sum(
                pos["quantity"] * float(bars.get(symbol, {}).get("close", pos["last_close"]))
                for symbol, pos in positions.items()
            )
            equity_rows.append({"date": date, "cash": cash, "market_value": market_value, "equity": cash + market_value, "open_positions": len(positions)})

        if positions and self.config.force_liquidation:
            final_date = data["date"].max()
            for symbol in sorted(list(positions)):
                pos = positions.pop(symbol)
                cash += self._close_position(pos, symbol, final_date, float(pos["last_close"]), "End Of Test", trades)
            equity_rows[-1].update({"cash": cash, "market_value": 0.0, "equity": cash, "open_positions": 0})

        equity = pd.DataFrame(equity_rows)
        trade_frame = pd.DataFrame(trades)
        summary = calculate_metrics(equity, trade_frame, self.config.initial_cash)
        summary.update({"strategy": strategy.name, "symbols": int(data["symbol"].nunique()), "candle_rows": int(len(data)), "signal_count": len(signals), "start_date": str(data["date"].min().date()), "end_date": str(data["date"].max().date())})
        fingerprint_source = pd.util.hash_pandas_object(data, index=False).values.tobytes()
        fingerprint_source += "|".join(data.columns).encode("utf-8")
        manifest = {
            "engine_version": "1.0.0",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy.name,
            "strategy_parameters": strategy.parameters(),
            "config": self.config.to_dict(),
            "data_sha256": hashlib.sha256(fingerprint_source).hexdigest(),
            "data_rows": len(data),
            "data_symbols": int(data["symbol"].nunique()),
            "date_range": [summary["start_date"], summary["end_date"]],
        }
        return BacktestResult(summary, trade_frame, equity, signal_frame, manifest)

    def _exit_for_bar(self, pos: dict[str, Any], bar: dict[str, Any]) -> tuple[str | None, float | None]:
        stop = float(pos["stop_price"])
        target = float(pos["target_price"])
        opened = float(bar["open"])
        if opened <= stop:
            return "Stop Gap", opened
        hit_stop = float(bar["low"]) <= stop
        hit_target = float(bar["high"]) >= target
        if hit_stop and hit_target:
            if self.config.ambiguous_fill_policy == "stop_first":
                return "Stop (Ambiguous Bar)", stop
            return "Target (Ambiguous Bar)", target
        if hit_stop:
            return "Stop", stop
        if hit_target:
            return "Target", target
        if int(pos["bars_held"]) >= int(pos["max_holding_bars"]):
            return "Time Stop", float(bar["close"])
        return None, None

    def _close_position(self, pos: dict[str, Any], symbol: str, date: pd.Timestamp, raw_exit: float, reason: str, trades: list[dict[str, Any]]) -> float:
        exit_price = raw_exit * (1 - self._slippage_rate)
        exit_notional = int(pos["quantity"]) * exit_price
        exit_costs = exit_notional * self._cost_rate
        gross_pnl = (exit_price - float(pos["entry_price"])) * int(pos["quantity"])
        net_pnl = gross_pnl - float(pos["entry_costs"]) - exit_costs
        trades.append({
            "symbol": symbol, "signal_date": pd.Timestamp(pos["signal_date"]).date().isoformat(),
            "entry_date": pd.Timestamp(pos["entry_date"]).date().isoformat(), "exit_date": date.date().isoformat(),
            "entry_price": round(float(pos["entry_price"]), 6), "exit_price": round(exit_price, 6),
            "stop_price": float(pos["stop_price"]), "target_price": float(pos["target_price"]),
            "quantity": int(pos["quantity"]), "bars_held": int(pos["bars_held"]), "exit_reason": reason,
            "gross_pnl": round(gross_pnl, 2), "costs": round(float(pos["entry_costs"]) + exit_costs, 2),
            "net_pnl": round(net_pnl, 2), "return_pct": round(net_pnl / (float(pos["entry_price"]) * int(pos["quantity"])) * 100, 4),
            "metadata": pos.get("metadata", "{}"),
        })
        return exit_notional - exit_costs

    @staticmethod
    def _signal_row(signal: Signal) -> dict[str, Any]:
        row = asdict(signal)
        row["symbol"] = signal.symbol.upper()
        row["metadata"] = json.dumps(signal.metadata, sort_keys=True)
        return row

    @staticmethod
    def _validate_signals(signals: list[Signal], data: pd.DataFrame) -> None:
        symbols = set(data["symbol"])
        min_date, max_date = data["date"].min(), data["date"].max()
        seen: set[tuple[str, str]] = set()
        for signal in signals:
            key = (signal.symbol.upper(), str(pd.Timestamp(signal.signal_date).date()))
            if key in seen:
                raise ValueError(f"duplicate signal for {key[0]} on {key[1]}")
            seen.add(key)
            if key[0] not in symbols:
                raise ValueError(f"signal symbol not in candle data: {key[0]}")
            date = pd.Timestamp(signal.signal_date).normalize()
            if not min_date <= date <= max_date:
                raise ValueError(f"signal date outside candle range: {key[1]}")
