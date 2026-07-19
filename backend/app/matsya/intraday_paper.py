from __future__ import annotations

import csv
import io
import json
import math
import os
import struct
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from app.matsya.paper_state import atomic_write_json, atomic_write_text, paper_state_lock, read_json
from app.timezone import IST


FRICTION_BASE = 0.0025
FRICTION_HARSH = 0.0050
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
ExecutionLabel = Literal["live", "recovered", "ambiguous", "legacy"]


@dataclass(frozen=True)
class MarketTick:
    security_id: str
    price: float
    traded_at: datetime
    received_at: datetime
    exchange_segment: int = 1

    def __post_init__(self) -> None:
        if self.traded_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("Market tick timestamps must be timezone-aware.")
        if not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("Market tick price must be positive and finite.")


@dataclass(frozen=True)
class SubscriptionTarget:
    symbol: str
    security_id: str
    exchange_segment: str = "NSE_EQ"


@dataclass(frozen=True)
class StrategyPolicy:
    strategy_id: str
    output_dir: Path
    max_holding_bars: int
    stop_field: str
    stop_inclusive: bool


def default_policies() -> tuple[StrategyPolicy, StrategyPolicy]:
    return (
        StrategyPolicy(
            "v8_demo", Path(os.getenv("V8_DEMO_OUTPUT_DIR", "/app/data/v8_demo_trader")), 20, "stop_price", True
        ),
        StrategyPolicy(
            "uptrend_sideways",
            Path(os.getenv("UPTREND_SIDEWAYS_OUTPUT_DIR", "/app/data/uptrend_sideways_paper_trader")),
            40,
            "base_low",
            False,
        ),
    )


class DhanTickerPacketCodec:
    """Parser for DhanHQ v2 little-endian ticker packets (response code 2)."""

    HEADER_SIZE = 8
    TICKER_SIZE = 16

    @classmethod
    def parse(cls, packet: bytes, *, received_at: datetime | None = None) -> MarketTick | None:
        if len(packet) < cls.HEADER_SIZE:
            raise ValueError("Dhan feed packet is shorter than the 8-byte response header.")
        response_code, message_length, exchange_segment, security_id = struct.unpack_from("<BHBI", packet, 0)
        if message_length > len(packet) or message_length < cls.HEADER_SIZE:
            raise ValueError("Dhan feed packet length header is invalid.")
        if response_code != 2:
            return None
        if message_length < cls.TICKER_SIZE or len(packet) < cls.TICKER_SIZE:
            raise ValueError("Dhan ticker packet is incomplete.")
        price, epoch = struct.unpack_from("<fI", packet, cls.HEADER_SIZE)
        return MarketTick(
            security_id=str(security_id),
            price=float(price),
            traded_at=datetime.fromtimestamp(epoch, tz=timezone.utc),
            received_at=received_at or datetime.now(tz=timezone.utc),
            exchange_segment=int(exchange_segment),
        )

    @staticmethod
    def disconnect_reason(packet: bytes) -> int | None:
        if len(packet) < 10 or packet[0] != 50:
            return None
        return int(struct.unpack_from("<H", packet, 8)[0])


def subscription_messages(targets: Iterable[SubscriptionTarget], request_code: int = 15) -> list[str]:
    ordered = sorted({(target.exchange_segment, target.security_id) for target in targets})
    messages = []
    for start in range(0, len(ordered), 100):
        batch = ordered[start : start + 100]
        messages.append(
            json.dumps(
                {
                    "RequestCode": request_code,
                    "InstrumentCount": len(batch),
                    "InstrumentList": [
                        {"ExchangeSegment": segment, "SecurityId": security_id}
                        for segment, security_id in batch
                    ],
                },
                separators=(",", ":"),
            )
        )
    return messages


class IntradayPaperEngine:
    def __init__(self, policies: Iterable[StrategyPolicy] | None = None) -> None:
        self.policies = {policy.strategy_id: policy for policy in (policies or default_policies())}

    def desired_symbols(self) -> set[str]:
        symbols: set[str] = set()
        for strategy_id in self.policies:
            symbols.update(self.desired_symbols_for(strategy_id))
        return {symbol for symbol in symbols if symbol}

    def desired_symbols_for(self, strategy_id: str) -> set[str]:
        policy = self.policies[strategy_id]
        with paper_state_lock(policy.output_dir):
            state = self._load_state(policy)
            symbols = {str(row.get("symbol") or "") for row in state["pending_orders"]}
            symbols.update(str(row.get("symbol") or "") for row in state["open_positions"])
        return {symbol for symbol in symbols if symbol}

    def process_tick(self, strategy_id: str, symbol: str, tick: MarketTick) -> dict[str, Any]:
        policy = self.policies[strategy_id]
        with paper_state_lock(policy.output_dir):
            state = self._load_state(policy)
            intraday = self._intraday(state)
            tick_epoch = int(tick.traded_at.timestamp())
            last_tick = dict((intraday.get("last_ticks") or {}).get(symbol) or {})
            last_epoch = int(last_tick.get("epoch") or 0)
            last_price = float(last_tick.get("price") or 0.0)
            if tick_epoch < last_epoch:
                intraday["out_of_order_packets"] = int(intraday.get("out_of_order_packets") or 0) + 1
                self._save_state(policy, state)
                return {"status": "out_of_order", "symbol": symbol}
            if tick_epoch == last_epoch and math.isclose(last_price, tick.price, rel_tol=0.0, abs_tol=1e-8):
                intraday["duplicate_packets"] = int(intraday.get("duplicate_packets") or 0) + 1
                self._save_state(policy, state)
                return {"status": "duplicate", "symbol": symbol}

            if last_tick:
                intraday.setdefault("previous_ticks", {})[symbol] = last_tick
            intraday.setdefault("last_ticks", {})[symbol] = {
                "epoch": tick_epoch,
                "price": tick.price,
                "traded_at": tick.traded_at.isoformat(),
                "received_at": tick.received_at.isoformat(),
            }
            intraday["last_packet_at"] = tick.received_at.isoformat()
            intraday["packets_seen"] = int(intraday.get("packets_seen") or 0) + 1

            event = self._fill_pending(policy, state, symbol, tick)
            if event is None:
                event = self._process_live_exit(policy, state, symbol, tick)
            self._save_state(policy, state)
            self._sync_trade_ledger(policy, state)
            return event or {"status": "marked", "symbol": symbol}

    def reconcile(self, strategy_id: str, session_date: date, candles_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        policy = self.policies[strategy_id]
        produced: list[dict[str, Any]] = []
        with paper_state_lock(policy.output_dir):
            state = self._load_state(policy)
            for position in list(state["open_positions"]):
                symbol = str(position.get("symbol") or "")
                candles = sorted(candles_by_symbol.get(symbol, []), key=lambda row: int(row.get("timestamp") or 0))
                if candles and position.get("last_reconciled_date") != session_date.isoformat():
                    position["bars_held"] = int(position.get("bars_held") or 0) + 1
                    position["last_reconciled_date"] = session_date.isoformat()
                event = self._recover_exit(policy, state, position, candles, session_date)
                if event:
                    produced.append(event)
                    continue
                if candles:
                    if int(position["bars_held"]) >= policy.max_holding_bars:
                        close_price = float(candles[-1]["close"])
                        produced.append(
                            self._close_position(
                                policy,
                                state,
                                position,
                                raw_exit_price=close_price,
                                event_at=_epoch_datetime(int(candles[-1]["timestamp"])),
                                reason="Time Stop",
                                label="recovered",
                            )
                        )

            self._mark_missed_entries(policy, state, session_date, produced)
            intraday = self._intraday(state)
            intraday["last_reconciliation_at"] = datetime.now(tz=timezone.utc).isoformat()
            intraday["last_reconciliation_date"] = session_date.isoformat()
            intraday["recovery_status"] = "complete"
            self._save_state(policy, state)
            self._sync_trade_ledger(policy, state)
        return produced

    def update_feed_health(
        self,
        *,
        status: str,
        subscribed_symbols: Iterable[str],
        detail: str = "",
        reconnects: int | None = None,
    ) -> None:
        symbols = sorted(set(subscribed_symbols))
        for policy in self.policies.values():
            with paper_state_lock(policy.output_dir):
                state = self._load_state(policy)
                intraday = self._intraday(state)
                intraday["enabled"] = status != "disabled"
                intraday["feed_status"] = status
                intraday["feed_detail"] = detail
                intraday["subscriptions"] = symbols
                intraday["subscription_count"] = len(symbols)
                intraday["feed_updated_at"] = datetime.now(tz=timezone.utc).isoformat()
                if reconnects is not None:
                    intraday["reconnects"] = reconnects
                self._save_state(policy, state)

    def sync_all_ledgers(self) -> None:
        for policy in self.policies.values():
            with paper_state_lock(policy.output_dir):
                state = self._load_state(policy)
                self._sync_trade_ledger(policy, state)

    def _fill_pending(
        self,
        policy: StrategyPolicy,
        state: dict[str, Any],
        symbol: str,
        tick: MarketTick,
    ) -> dict[str, Any] | None:
        pending = next((row for row in state["pending_orders"] if str(row.get("symbol")) == symbol), None)
        if pending is None:
            return None
        traded_ist = tick.traded_at.astimezone(IST)
        if not _inside_market_session(traded_ist) or traded_ist.date().isoformat() <= str(pending.get("signal_date") or ""):
            return None
        event_id = f"{policy.strategy_id}:entry:{symbol}:{pending.get('signal_date')}"
        if self._event_exists(state, event_id):
            return {"status": "duplicate_event", "event_id": event_id}

        effective_entry = tick.price * (1 + FRICTION_BASE)
        harsh_entry = tick.price * (1 + FRICTION_HARSH)
        allocation = float(pending.get("target_allocation") or 0.0)
        if policy.strategy_id == "v8_demo":
            allocation = min(allocation, float(pending.get("liquidity_cap") or allocation))
        shares = int(allocation / effective_entry) if effective_entry > 0 else 0
        if shares <= 0 or shares * effective_entry > float(state.get("cash") or 0.0):
            self._record_event(
                state,
                {"event_id": event_id, "type": "missed_entry", "symbol": symbol, "label": "live", "reason": "insufficient_cash_or_zero_shares", "event_at": tick.traded_at.isoformat()},
            )
            state["pending_orders"] = [row for row in state["pending_orders"] if row is not pending]
            return {"status": "missed_entry", "event_id": event_id}

        invested = shares * effective_entry
        position = dict(pending)
        position.update(
            {
                "entry_date": traded_ist.date().isoformat(),
                "shares": shares,
                "raw_entry_price": tick.price,
                "entry_price": effective_entry,
                "harsh_entry_price": harsh_entry,
                "bars_held": 0,
                "invested_value": invested,
                "broker_mode": "paper",
                "execution_label": "live",
                "entry_event_id": event_id,
                "entry_tick_at": tick.traded_at.isoformat(),
            }
        )
        if policy.strategy_id == "v8_demo":
            position["target_price"] = _round_money(tick.price * 1.10)
            position["stop_price"] = _round_money(tick.price * 0.95)
        else:
            position["stop_price"] = float(position["base_low"])
        state["cash"] = float(state.get("cash") or 0.0) - invested
        state["pending_orders"] = [row for row in state["pending_orders"] if row is not pending]
        state["open_positions"].append(position)
        event = {
            "event_id": event_id,
            "type": "entry",
            "symbol": symbol,
            "label": "live",
            "event_at": tick.traded_at.isoformat(),
            "raw_price": tick.price,
            "effective_price": effective_entry,
            "shares": shares,
        }
        self._record_event(state, event)
        return {"status": "entered", **event}

    def _process_live_exit(
        self,
        policy: StrategyPolicy,
        state: dict[str, Any],
        symbol: str,
        tick: MarketTick,
    ) -> dict[str, Any] | None:
        position = next((row for row in state["open_positions"] if str(row.get("symbol")) == symbol), None)
        if position is None:
            return None
        if not _inside_market_session(tick.traded_at):
            return None
        stop = float(position.get(policy.stop_field) or 0.0)
        target = float(position.get("target_price") or 0.0)
        stop_hit = tick.price <= stop if policy.stop_inclusive else tick.price < stop
        target_hit = target > 0 and tick.price >= target
        if not stop_hit and not target_hit:
            return None
        if stop_hit:
            # A discrete feed cannot prove a fill at an unobserved stop price.
            # Use the worse of the configured stop and the first observed price.
            raw_exit = min(tick.price, stop)
            reason = "Stop Loss" if policy.strategy_id == "v8_demo" else "Base Failure"
        else:
            raw_exit = target
            reason = "Target Hit"
        return self._close_position(policy, state, position, raw_exit, tick.traded_at, reason, "live")

    def _recover_exit(
        self,
        policy: StrategyPolicy,
        state: dict[str, Any],
        position: dict[str, Any],
        candles: list[dict[str, Any]],
        session_date: date,
    ) -> dict[str, Any] | None:
        stop = float(position.get(policy.stop_field) or 0.0)
        target = float(position.get("target_price") or 0.0)
        entry_epoch = _iso_epoch(position.get("entry_tick_at"))
        for candle in candles:
            epoch = int(candle.get("timestamp") or 0)
            if epoch <= entry_epoch or _epoch_datetime(epoch).astimezone(IST).date() != session_date:
                continue
            open_price = float(candle["open"])
            low = float(candle["low"])
            high = float(candle["high"])
            stop_hit = low <= stop if policy.stop_inclusive else low < stop
            target_hit = target > 0 and high >= target
            if not stop_hit and not target_hit:
                continue
            label: ExecutionLabel = "ambiguous" if stop_hit and target_hit else "recovered"
            if stop_hit:
                raw_exit = open_price if open_price <= stop else stop
                reason = "Stop (Ambiguous Minute)" if target_hit else ("Stop Loss" if policy.strategy_id == "v8_demo" else "Base Failure")
            else:
                raw_exit = target
                reason = "Target Hit"
            return self._close_position(policy, state, position, raw_exit, _epoch_datetime(epoch), reason, label)
        return None

    def _close_position(
        self,
        policy: StrategyPolicy,
        state: dict[str, Any],
        position: dict[str, Any],
        raw_exit_price: float,
        event_at: datetime,
        reason: str,
        label: ExecutionLabel,
    ) -> dict[str, Any]:
        symbol = str(position["symbol"])
        entry_key = str(position.get("entry_event_id") or position.get("entry_date") or "legacy")
        event_id = f"{policy.strategy_id}:exit:{symbol}:{entry_key}"
        if self._event_exists(state, event_id):
            return {"status": "duplicate_event", "event_id": event_id}
        shares = int(position["shares"])
        effective_exit = raw_exit_price * (1 - FRICTION_BASE)
        harsh_exit = raw_exit_price * (1 - FRICTION_HARSH)
        entry_price = float(position["entry_price"])
        harsh_entry = float(position.get("harsh_entry_price") or entry_price)
        pnl_value = (effective_exit - entry_price) * shares
        state["cash"] = float(state.get("cash") or 0.0) + shares * effective_exit
        state["open_positions"] = [row for row in state["open_positions"] if row is not position]
        ledger_row = {
            "event_id": event_id,
            "symbol": symbol,
            "entry_date": position.get("entry_date"),
            "exit_date": event_at.astimezone(IST).date().isoformat(),
            "reason": reason,
            "bars_held": int(position.get("bars_held") or 0),
            "shares": shares,
            "entry_price": entry_price,
            "exit_price": effective_exit,
            "pnl_value": pnl_value,
            "pnl_pct": (effective_exit / entry_price) - 1,
            "harsh_pnl_pct": (harsh_exit / harsh_entry) - 1,
            "broker_mode": "paper",
            "execution_label": label,
            "event_at": event_at.isoformat(),
        }
        for key in ("base_high", "base_low", "target_price"):
            if key in position:
                ledger_row[key] = position[key]
        event = {
            "event_id": event_id,
            "type": "exit",
            "symbol": symbol,
            "label": label,
            "reason": reason,
            "event_at": event_at.isoformat(),
            "raw_price": raw_exit_price,
            "effective_price": effective_exit,
            "ledger_row": ledger_row,
        }
        self._record_event(state, event)
        return {"status": "exited", **event}

    def _mark_missed_entries(
        self,
        policy: StrategyPolicy,
        state: dict[str, Any],
        session_date: date,
        produced: list[dict[str, Any]],
    ) -> None:
        remaining = []
        for order in state["pending_orders"]:
            signal_date = str(order.get("signal_date") or "")
            if signal_date and signal_date < session_date.isoformat():
                symbol = str(order.get("symbol") or "")
                event_id = f"{policy.strategy_id}:missed:{symbol}:{signal_date}"
                if not self._event_exists(state, event_id):
                    event = {
                        "event_id": event_id,
                        "type": "missed_entry",
                        "symbol": symbol,
                        "label": "recovered",
                        "reason": "no_valid_live_price_observed",
                        "event_at": datetime.combine(session_date, MARKET_CLOSE, tzinfo=IST).isoformat(),
                    }
                    self._record_event(state, event)
                    produced.append({"status": "missed_entry", **event})
                continue
            remaining.append(order)
        state["pending_orders"] = remaining

    def _load_state(self, policy: StrategyPolicy) -> dict[str, Any]:
        state = read_json(
            policy.output_dir / "paper_broker_state.json",
            {"cash": 100000.0, "pending_orders": [], "open_positions": []},
        )
        state.setdefault("cash", 100000.0)
        state.setdefault("pending_orders", [])
        state.setdefault("open_positions", [])
        for position in state["open_positions"]:
            position.setdefault("execution_label", "legacy")
            if policy.strategy_id == "uptrend_sideways" and "stop_price" not in position and position.get("base_low") is not None:
                position["stop_price"] = position["base_low"]
        self._intraday(state)
        return state

    @staticmethod
    def _intraday(state: dict[str, Any]) -> dict[str, Any]:
        intraday = state.setdefault("intraday", {})
        intraday.setdefault("version", 1)
        intraday.setdefault("enabled", True)
        intraday.setdefault("feed_status", "starting")
        intraday.setdefault("events", [])
        intraday.setdefault("event_ids", [])
        intraday.setdefault("last_ticks", {})
        intraday.setdefault("previous_ticks", {})
        intraday.setdefault("duplicate_packets", 0)
        intraday.setdefault("out_of_order_packets", 0)
        intraday.setdefault("packets_seen", 0)
        return intraday

    def _save_state(self, policy: StrategyPolicy, state: dict[str, Any]) -> None:
        intraday = self._intraday(state)
        intraday["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        atomic_write_json(policy.output_dir / "paper_broker_state.json", state)

    def _record_event(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        intraday = self._intraday(state)
        if event["event_id"] in set(intraday["event_ids"]):
            return
        intraday["event_ids"].append(event["event_id"])
        intraday["events"].append(event)

    def _event_exists(self, state: dict[str, Any], event_id: str) -> bool:
        return event_id in set(self._intraday(state).get("event_ids") or [])

    def _sync_trade_ledger(self, policy: StrategyPolicy, state: dict[str, Any]) -> None:
        path = policy.output_dir / "paper_trade_ledger.csv"
        rows: list[dict[str, Any]] = []
        if path.exists():
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        existing_ids = {str(row.get("event_id") or "") for row in rows}
        for event in self._intraday(state).get("events") or []:
            ledger_row = event.get("ledger_row")
            if ledger_row and event["event_id"] not in existing_ids:
                rows.append(dict(ledger_row))
                existing_ids.add(event["event_id"])
        if not rows:
            return
        columns: list[str] = []
        for row in rows:
            for column in row:
                if column not in columns:
                    columns.append(column)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        atomic_write_text(path, buffer.getvalue())


def intraday_dashboard_state(state: dict[str, Any]) -> dict[str, Any]:
    intraday = dict(state.get("intraday") or {})
    events = list(intraday.pop("events", []) or [])
    intraday.pop("event_ids", None)
    intraday.pop("last_ticks", None)
    intraday.pop("previous_ticks", None)
    intraday["recent_events"] = events[-30:]
    intraday["missed_entries"] = [event for event in events if event.get("type") == "missed_entry"][-30:]
    intraday["live_entries"] = sum(1 for event in events if event.get("type") == "entry" and event.get("label") == "live")
    intraday["exits"] = sum(1 for event in events if event.get("type") == "exit")
    intraday["pending_entries"] = len(state.get("pending_orders") or [])
    intraday["open_positions"] = len(state.get("open_positions") or [])
    intraday["stops"] = [
        {"symbol": row.get("symbol"), "price": row.get("stop_price") or row.get("base_low")}
        for row in state.get("open_positions") or []
    ]
    intraday["targets"] = [
        {"symbol": row.get("symbol"), "price": row.get("target_price")}
        for row in state.get("open_positions") or []
    ]
    return intraday


def _inside_market_session(value: datetime) -> bool:
    resolved = value.astimezone(IST)
    return resolved.weekday() < 5 and MARKET_OPEN <= resolved.time().replace(tzinfo=None) <= MARKET_CLOSE


def _round_money(value: float) -> float:
    return round(float(value) + 1e-12, 2)


def _epoch_datetime(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _iso_epoch(value: Any) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value)).timestamp())
    except ValueError:
        return 0
