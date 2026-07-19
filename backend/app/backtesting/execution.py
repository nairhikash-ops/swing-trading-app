from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from .intraday import validate_intraday_candles


Side = Literal["long", "short"]


@dataclass(frozen=True)
class IntradayOrder:
    symbol: str
    side: Side
    activation_time: pd.Timestamp
    entry_expiration_time: pd.Timestamp
    expiration_time: pd.Timestamp
    stop_price: float
    final_target_price: float
    trigger_price: float | None = None
    gap_reference_price: float | None = None
    enter_at_activation_open: bool = False
    first_target_r: float = 1.0
    first_exit_fraction: float = 0.5
    move_stop_to_breakeven: bool = True
    trailing_pivot_bars: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.stop_price <= 0 or self.final_target_price <= 0:
            raise ValueError("stop and final target must be positive")
        if self.trigger_price is None and not self.enter_at_activation_open:
            raise ValueError("trigger_price is required unless entering at activation open")
        if not 0 < self.first_exit_fraction < 1:
            raise ValueError("first_exit_fraction must be in (0, 1)")
        if self.first_target_r <= 0 or self.trailing_pivot_bars < 0:
            raise ValueError("target R must be positive and trailing bars cannot be negative")
        if not pd.Timestamp(self.activation_time) <= pd.Timestamp(self.entry_expiration_time) <= pd.Timestamp(self.expiration_time):
            raise ValueError("entry/position expiration times are not ordered")


@dataclass(frozen=True)
class IntradayExecutionConfig:
    slippage_bps: float = 5.0
    round_trip_cost_bps: float = 15.0
    pessimistic_same_bar: bool = True

    def __post_init__(self) -> None:
        if self.slippage_bps < 0 or self.round_trip_cost_bps < 0:
            raise ValueError("costs and slippage cannot be negative")


class IntradayExecutionEngine:
    """Deterministic long/short executor with scale-out and confirmed-pivot trailing."""

    def __init__(self, config: IntradayExecutionConfig | None = None) -> None:
        self.config = config or IntradayExecutionConfig()

    def run(self, candles: pd.DataFrame, orders: list[IntradayOrder]) -> pd.DataFrame:
        data = validate_intraday_candles(candles)
        rows = []
        indexed = {symbol: group.reset_index(drop=True) for symbol, group in data.groupby("symbol", sort=False)}
        for order in sorted(orders, key=lambda item: (pd.Timestamp(item.activation_time), item.symbol)):
            bars = indexed.get(order.symbol.upper())
            if bars is None:
                rows.append(self._unfilled(order, "missing_intraday_data"))
                continue
            rows.append(self._execute_one(bars, order))
        return pd.DataFrame(rows)

    def _execute_one(self, bars: pd.DataFrame, order: IntradayOrder) -> dict[str, Any]:
        activation = pd.Timestamp(order.activation_time)
        expiration = pd.Timestamp(order.expiration_time)
        entry_expiration = pd.Timestamp(order.entry_expiration_time)
        if activation.tzinfo is None:
            activation = activation.tz_localize("Asia/Kolkata").tz_convert("UTC")
        else:
            activation = activation.tz_convert("UTC")
        if expiration.tzinfo is None:
            expiration = expiration.tz_localize("Asia/Kolkata").tz_convert("UTC")
        else:
            expiration = expiration.tz_convert("UTC")
        if entry_expiration.tzinfo is None:
            entry_expiration = entry_expiration.tz_localize("Asia/Kolkata").tz_convert("UTC")
        else:
            entry_expiration = entry_expiration.tz_convert("UTC")
        eligible = bars[(bars["timestamp"] >= activation) & (bars["timestamp"] <= expiration)].copy()
        if eligible.empty:
            return self._unfilled(order, "missing_required_window")

        entry_index: int | None = None
        if order.enter_at_activation_open:
            entry_index = int(eligible.index[0])
        else:
            for idx in eligible.index:
                close = float(bars.at[idx, "close"])
                triggered = close > float(order.trigger_price) if order.side == "long" else close < float(order.trigger_price)
                if pd.Timestamp(bars.at[idx, "timestamp"]) > entry_expiration:
                    break
                if triggered and idx + 1 in bars.index and pd.Timestamp(bars.at[idx + 1, "timestamp"]) <= entry_expiration:
                    entry_index = int(idx + 1)
                    break
        if entry_index is None:
            return self._unfilled(order, "structure_shift_not_triggered")

        raw_entry = float(bars.at[entry_index, "open"])
        slip = self.config.slippage_bps / 10_000
        entry = raw_entry * (1 + slip if order.side == "long" else 1 - slip)
        initial_risk = entry - order.stop_price if order.side == "long" else order.stop_price - entry
        target_distance = order.final_target_price - entry if order.side == "long" else entry - order.final_target_price
        if initial_risk <= 0:
            return self._unfilled(order, "gap_beyond_stop", entry=entry)
        if target_distance < initial_risk:
            return self._unfilled(order, "final_target_below_1r", entry=entry)

        reference = float(order.gap_reference_price or order.trigger_price or entry)
        reference_risk = reference - order.stop_price if order.side == "long" else order.stop_price - reference
        reference_t1 = reference + reference_risk * order.first_target_r * (1 if order.side == "long" else -1)
        # A gap that already travelled 1R from the planned structure entry leaves no defensible new entry.
        if reference_risk > 0 and ((order.side == "long" and raw_entry >= reference_t1) or (order.side == "short" and raw_entry <= reference_t1)):
            return self._unfilled(order, "opening_gap_consumed_t1", entry=entry)
        first_target = entry + initial_risk * order.first_target_r * (1 if order.side == "long" else -1)

        stop = float(order.stop_price)
        remaining = 1.0
        realized_r = 0.0
        t1_time: pd.Timestamp | None = None
        exit_time: pd.Timestamp | None = None
        exit_price: float | None = None
        exit_reason = "window_expired"
        pivot_width = order.trailing_pivot_bars

        for idx in range(entry_index, int(eligible.index[-1]) + 1):
            bar = bars.loc[idx]
            opened, high, low, close = (float(bar[key]) for key in ("open", "high", "low", "close"))
            timestamp = pd.Timestamp(bar["timestamp"])

            stop_hit = low <= stop if order.side == "long" else high >= stop
            t1_hit = t1_time is None and (high >= first_target if order.side == "long" else low <= first_target)
            final_hit = high >= order.final_target_price if order.side == "long" else low <= order.final_target_price

            if stop_hit and (self.config.pessimistic_same_bar or not (t1_hit or final_hit)):
                raw_exit = opened if (opened <= stop if order.side == "long" else opened >= stop) else stop
                exit_price = self._exit_with_slippage(raw_exit, order.side)
                realized_r += remaining * self._r_multiple(entry, exit_price, initial_risk, order.side)
                exit_time, exit_reason, remaining = timestamp, "stop", 0.0
                break
            if final_hit:
                exit_price = self._exit_with_slippage(float(order.final_target_price), order.side)
                if t1_time is None:
                    t1_price = self._exit_with_slippage(first_target, order.side)
                    realized_r += order.first_exit_fraction * self._r_multiple(entry, t1_price, initial_risk, order.side)
                    remaining -= order.first_exit_fraction
                    t1_time = timestamp
                realized_r += remaining * self._r_multiple(entry, exit_price, initial_risk, order.side)
                exit_time, exit_reason, remaining = timestamp, "final_target", 0.0
                break
            if t1_hit:
                t1_price = self._exit_with_slippage(first_target, order.side)
                realized_r += order.first_exit_fraction * self._r_multiple(entry, t1_price, initial_risk, order.side)
                remaining -= order.first_exit_fraction
                t1_time = timestamp
                if order.move_stop_to_breakeven:
                    stop = max(stop, entry) if order.side == "long" else min(stop, entry)

            if t1_time is not None and pivot_width and idx >= entry_index + pivot_width * 2:
                center = idx - pivot_width
                window = bars.loc[center - pivot_width : center + pivot_width]
                if len(window) == pivot_width * 2 + 1:
                    if order.side == "long" and float(bars.at[center, "low"]) == float(window["low"].min()):
                        candidate = float(bars.at[center, "low"])
                        if close > candidate:
                            stop = max(stop, candidate)
                    elif order.side == "short" and float(bars.at[center, "high"]) == float(window["high"].max()):
                        candidate = float(bars.at[center, "high"])
                        if close < candidate:
                            stop = min(stop, candidate)

        if remaining:
            last = eligible.iloc[-1]
            exit_time = pd.Timestamp(last["timestamp"])
            exit_price = self._exit_with_slippage(float(last["close"]), order.side)
            realized_r += remaining * self._r_multiple(entry, exit_price, initial_risk, order.side)

        cost_r = (entry * self.config.round_trip_cost_bps / 10_000) / initial_risk
        return {
            "symbol": order.symbol.upper(), "side": order.side, "status": "filled",
            "activation_time": activation.isoformat(), "entry_time": pd.Timestamp(bars.at[entry_index, "timestamp"]).isoformat(),
            "entry_price": round(entry, 6), "initial_stop": order.stop_price,
            "first_target": round(first_target, 6), "first_target_time": None if t1_time is None else t1_time.isoformat(),
            "final_target": order.final_target_price, "exit_time": None if exit_time is None else exit_time.isoformat(),
            "exit_price": None if exit_price is None else round(exit_price, 6), "exit_reason": exit_reason,
            "gross_r": round(realized_r, 6), "net_r": round(realized_r - cost_r, 6),
            "metadata": json.dumps(order.metadata, sort_keys=True),
        }

    @staticmethod
    def _r_multiple(entry: float, exit_price: float, risk: float, side: Side) -> float:
        return (exit_price - entry) / risk if side == "long" else (entry - exit_price) / risk

    def _exit_with_slippage(self, price: float, side: Side) -> float:
        slip = self.config.slippage_bps / 10_000
        return price * (1 - slip if side == "long" else 1 + slip)

    @staticmethod
    def _unfilled(order: IntradayOrder, reason: str, *, entry: float | None = None) -> dict[str, Any]:
        return {
            "symbol": order.symbol.upper(), "side": order.side, "status": "rejected",
            "activation_time": pd.Timestamp(order.activation_time).isoformat(), "entry_time": None,
            "entry_price": entry, "initial_stop": order.stop_price, "first_target": None,
            "first_target_time": None, "final_target": order.final_target_price, "exit_time": None,
            "exit_price": None, "exit_reason": reason, "gross_r": None, "net_r": None,
            "metadata": json.dumps(order.metadata, sort_keys=True),
        }
