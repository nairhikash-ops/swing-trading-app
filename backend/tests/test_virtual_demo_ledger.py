from __future__ import annotations

from pathlib import Path

import pytest

from app.matsya.virtual_demo_ledger import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_REJECTED,
    VirtualDemoLedger,
)


def test_account_creation_records_cash_and_audit_event() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=10000.0)

    assert ledger.account.account_id == "demo"
    assert ledger.account.cash_balance == 10000.0
    assert ledger.account.starting_cash == 10000.0
    assert ledger.events[0].event_type == "account_created"


def test_open_long_position_reduces_cash_and_records_fill() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=10000.0)

    order = ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=10, entry_price=100.0)

    assert order.status == STATUS_CLOSED
    assert ledger.account.cash_balance == 9000.0
    assert len(ledger.open_positions()) == 1
    assert ledger.open_positions()[0].status == STATUS_OPEN
    assert ledger.fills[0].notional == 1000.0
    assert [event.event_type for event in ledger.events] == [
        "account_created",
        "order_filled",
        "position_opened",
    ]


def test_insufficient_cash_rejects_order_without_position_or_fill() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=100.0)

    order = ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=2, entry_price=100.0)

    assert order.status == STATUS_REJECTED
    assert order.reason == "insufficient_cash"
    assert ledger.account.cash_balance == 100.0
    assert ledger.open_positions() == []
    assert ledger.fills == []
    assert ledger.events[-1].event_type == "order_rejected"


def test_closing_position_updates_cash_and_realized_pnl() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=10000.0)
    ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=10, entry_price=100.0)
    position_id = ledger.open_positions()[0].position_id

    order = ledger.close_position(position_id=position_id, exit_price=112.5)

    assert order.status == STATUS_CLOSED
    assert ledger.open_positions() == []
    closed = ledger.closed_positions()[0]
    assert closed.realized_pnl == 125.0
    assert ledger.realized_pnl() == 125.0
    assert ledger.account.cash_balance == 10125.0
    assert ledger.events[-1].event_type == "position_closed"


def test_unrealized_pnl_and_total_equity_use_supplied_prices() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=10000.0)
    ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=10, entry_price=100.0)
    ledger.open_long_position(symbol="BETA", security_id="1002", quantity=5, entry_price=200.0)

    prices = {"ALPHA": 110.0, "BETA": 190.0}

    assert ledger.unrealized_pnl(prices) == 50.0
    assert ledger.market_value(prices) == 2050.0
    assert ledger.total_equity(prices) == 10050.0


def test_brokerage_is_explicit_and_affects_cash_not_pnl_formula() -> None:
    ledger = VirtualDemoLedger.create_account(
        account_id="demo",
        starting_cash=10000.0,
        brokerage_per_order=5.0,
    )
    ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=10, entry_price=100.0)
    position_id = ledger.open_positions()[0].position_id
    ledger.close_position(position_id=position_id, exit_price=110.0)

    assert ledger.realized_pnl() == 100.0
    assert ledger.account.cash_balance == 10090.0


def test_invalid_short_or_zero_quantity_is_rejected() -> None:
    ledger = VirtualDemoLedger.create_account(account_id="demo", starting_cash=10000.0)

    with pytest.raises(ValueError, match="quantity"):
        ledger.open_long_position(symbol="ALPHA", security_id="1001", quantity=0, entry_price=100.0)


def test_new_ledger_files_do_not_import_dhan_db_or_prediction_paths() -> None:
    source = Path("app/matsya/virtual_demo_ledger.py").read_text(encoding="utf-8").lower()

    assert "dhan" not in source
    assert "connect(" not in source
    assert "insert " not in source
    assert "update " not in source
    assert "delete " not in source
    assert "predict(" not in source
    assert "predict_proba" not in source
