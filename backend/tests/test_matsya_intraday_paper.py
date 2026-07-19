from __future__ import annotations

import csv
import json
import struct
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.matsya.intraday_paper import (
    DhanTickerPacketCodec,
    IntradayPaperEngine,
    MarketTick,
    StrategyPolicy,
    SubscriptionTarget,
    subscription_messages,
)
from scripts.matsya_intraday_paper_worker import MatsyaIntradayPaperWorker, parse_intraday_payload

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from v8_demo_trader import PaperBroker as V8PaperBroker  # noqa: E402


def make_engine(tmp_path: Path, strategy_id: str = "v8_demo") -> tuple[IntradayPaperEngine, Path]:
    output_dir = tmp_path / strategy_id
    policy = StrategyPolicy(
        strategy_id,
        output_dir,
        20 if strategy_id == "v8_demo" else 40,
        "stop_price" if strategy_id == "v8_demo" else "base_low",
        strategy_id == "v8_demo",
    )
    return IntradayPaperEngine([policy]), output_dir


def write_state(output_dir: Path, *, pending: list[dict] | None = None, positions: list[dict] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "paper_broker_state.json").write_text(
        json.dumps({"cash": 100_000.0, "pending_orders": pending or [], "open_positions": positions or []}),
        encoding="utf-8",
    )


def tick(price: float, at: datetime, security_id: str = "101") -> MarketTick:
    return MarketTick(security_id, price, at, at + timedelta(milliseconds=20))


def ticker_packet(price: float, at: datetime, security_id: int = 101) -> bytes:
    return struct.pack("<BHBIfI", 2, 16, 1, security_id, price, int(at.timestamp()))


def load_state(output_dir: Path) -> dict:
    return json.loads((output_dir / "paper_broker_state.json").read_text(encoding="utf-8"))


def test_dhan_ticker_codec_and_subscription_batches_are_deterministic() -> None:
    at = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
    parsed = DhanTickerPacketCodec.parse(ticker_packet(123.5, at))
    assert parsed is not None
    assert parsed.security_id == "101"
    assert parsed.price == pytest.approx(123.5)
    assert parsed.traded_at == at

    messages = subscription_messages(SubscriptionTarget(f"S{i}", str(i)) for i in range(205))
    payloads = [json.loads(message) for message in messages]
    assert [payload["InstrumentCount"] for payload in payloads] == [100, 100, 5]
    assert all(payload["RequestCode"] == 15 for payload in payloads)


def test_v8_first_valid_next_session_tick_is_only_entry_and_rules_are_preserved(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(
        output_dir,
        pending=[{"symbol": "TEST", "signal_date": "2026-07-17", "target_allocation": 20_000, "liquidity_cap": 15_000}],
    )
    signal_day = datetime(2026, 7, 17, 4, 0, tzinfo=timezone.utc)
    assert engine.process_tick("v8_demo", "TEST", tick(100, signal_day))["status"] == "marked"
    assert len(load_state(output_dir)["pending_orders"]) == 1

    entry_at = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
    result = engine.process_tick("v8_demo", "TEST", tick(100, entry_at))
    state = load_state(output_dir)
    position = state["open_positions"][0]
    assert result["status"] == "entered"
    assert position["entry_price"] == pytest.approx(100.25)
    assert position["shares"] == 149
    assert position["target_price"] == 110.0
    assert position["stop_price"] == 95.0
    assert position["execution_label"] == "live"


def test_uptrend_entry_preserves_structural_stop_and_signal_target(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path, "uptrend_sideways")
    write_state(
        output_dir,
        pending=[{
            "symbol": "SIDE", "signal_date": "2026-07-17", "target_allocation": 10_000,
            "base_low": 91.0, "base_high": 100.0, "target_price": 110.0,
        }],
    )
    result = engine.process_tick(
        "uptrend_sideways", "SIDE", tick(103, datetime(2026, 7, 20, 3, 46, tzinfo=timezone.utc))
    )
    position = load_state(output_dir)["open_positions"][0]
    assert result["status"] == "entered"
    assert position["base_low"] == 91.0
    assert position["stop_price"] == 91.0
    assert position["target_price"] == 110.0


def test_duplicate_out_of_order_and_restart_do_not_duplicate_entries(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(output_dir, pending=[{"symbol": "TEST", "signal_date": "2026-07-17", "target_allocation": 10_000, "liquidity_cap": 10_000}])
    at = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
    assert engine.process_tick("v8_demo", "TEST", tick(100, at))["status"] == "entered"
    assert engine.process_tick("v8_demo", "TEST", tick(100, at))["status"] == "duplicate"
    assert engine.process_tick("v8_demo", "TEST", tick(99, at - timedelta(seconds=1)))["status"] == "out_of_order"

    restarted, _ = make_engine(tmp_path)
    assert restarted.process_tick("v8_demo", "TEST", tick(100, at))["status"] == "duplicate"
    state = load_state(output_dir)
    assert len(state["open_positions"]) == 1
    assert len([event for event in state["intraday"]["events"] if event["type"] == "entry"]) == 1


def test_gap_through_stop_uses_first_observed_conservative_price_once(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(output_dir, positions=[{
        "symbol": "TEST", "entry_date": "2026-07-17", "shares": 10, "entry_price": 100.25,
        "harsh_entry_price": 100.5, "invested_value": 1002.5, "target_price": 110.0,
        "stop_price": 95.0, "bars_held": 0, "broker_mode": "paper",
    }])
    at = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
    result = engine.process_tick("v8_demo", "TEST", tick(90, at))
    assert result["status"] == "exited"
    assert result["raw_price"] == 90
    assert result["label"] == "live"
    assert engine.process_tick("v8_demo", "TEST", tick(89, at + timedelta(seconds=1)))["status"] == "marked"
    with (output_dir / "paper_trade_ledger.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert float(rows[0]["exit_price"]) == pytest.approx(90 * 0.9975)


def test_reconciliation_is_chronological_and_same_minute_ambiguity_favors_stop(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(output_dir, positions=[{
        "symbol": "TEST", "entry_date": "2026-07-17", "shares": 10, "entry_price": 100.25,
        "harsh_entry_price": 100.5, "invested_value": 1002.5, "target_price": 110.0,
        "stop_price": 95.0, "bars_held": 0, "broker_mode": "paper",
    }])
    first = int(datetime(2026, 7, 20, 3, 46, tzinfo=timezone.utc).timestamp())
    events = engine.reconcile("v8_demo", date(2026, 7, 20), {"TEST": [
        {"timestamp": first + 60, "open": 100, "high": 111, "low": 94, "close": 105},
        {"timestamp": first, "open": 100, "high": 109, "low": 99, "close": 104},
    ]})
    assert len(events) == 1
    assert events[0]["label"] == "ambiguous"
    assert events[0]["raw_price"] == 95.0
    assert load_state(output_dir)["open_positions"] == []


def test_reconciliation_never_invents_late_entry_and_marks_it_missed(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(output_dir, pending=[{"symbol": "TEST", "signal_date": "2026-07-17", "target_allocation": 10_000, "liquidity_cap": 10_000}])
    events = engine.reconcile("v8_demo", date(2026, 7, 20), {"TEST": []})
    assert events[0]["status"] == "missed_entry"
    assert events[0]["reason"] == "no_valid_live_price_observed"
    state = load_state(output_dir)
    assert state["pending_orders"] == []
    assert state["open_positions"] == []


@pytest.mark.asyncio
async def test_fake_feed_client_packets_drive_paper_engine_only(tmp_path: Path) -> None:
    engine, output_dir = make_engine(tmp_path)
    write_state(output_dir, pending=[{"symbol": "TEST", "signal_date": "2026-07-17", "target_allocation": 10_000, "liquidity_cap": 10_000}])
    at = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)

    class FakeDhanPackets:
        def __aiter__(self):
            self._packets = iter([ticker_packet(100, at), ticker_packet(100, at)])
            return self

        async def __anext__(self):
            try:
                return next(self._packets)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    worker = object.__new__(MatsyaIntradayPaperWorker)
    worker.engine = engine
    worker.targets_by_symbol = {"TEST": SubscriptionTarget("TEST", "101")}
    results = await worker.consume_packets(FakeDhanPackets())
    assert [result["status"] for result in results] == ["entered", "duplicate"]
    assert len(load_state(output_dir)["open_positions"]) == 1


def test_intraday_payload_parser_rejects_invalid_prices_and_order_apis_are_absent() -> None:
    payload = {"timestamp": [2, 1], "open": [10, 0], "high": [11, 1], "low": [9, 1], "close": [10.5, 1]}
    assert parse_intraday_payload(payload) == [{"timestamp": 2, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5}]

    backend = Path(__file__).resolve().parents[1]
    paper_execution_sources = [
        backend / "app" / "matsya" / "intraday_paper.py",
        backend / "scripts" / "matsya_intraday_paper_worker.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paper_execution_sources)
    assert "/orders" not in combined
    assert "place_order" not in combined
    assert "modify_order" not in combined
    assert "cancel_order" not in combined


def test_enabled_eod_save_merges_only_new_pending_orders_with_worker_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATSYA_INTRADAY_PAPER_ENABLED", "true")
    output_dir = tmp_path / "v8"
    old_order = {"symbol": "OLD", "signal_date": "2026-07-17"}
    write_state(output_dir, pending=[old_order])
    broker = V8PaperBroker(output_dir, 100_000)
    broker.load()
    new_order = {"symbol": "NEW", "signal_date": "2026-07-20"}
    broker.state["pending_orders"].append(new_order)

    concurrent_position = {"symbol": "OLD", "shares": 10, "entry_price": 100, "target_price": 110, "stop_price": 95}
    (output_dir / "paper_broker_state.json").write_text(
        json.dumps({"cash": 99_000, "pending_orders": [], "open_positions": [concurrent_position], "intraday": {"events": []}}),
        encoding="utf-8",
    )
    broker.save()

    state = load_state(output_dir)
    assert state["cash"] == 99_000
    assert state["open_positions"] == [concurrent_position]
    assert state["pending_orders"] == [new_order]
