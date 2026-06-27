from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import count
from math import isfinite
from typing import Any


STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"

ORDER_BUY = "buy"
ORDER_SELL = "sell"


@dataclass(frozen=True)
class VirtualDemoAccount:
    account_id: str
    starting_cash: float
    cash_balance: float
    created_at: str


@dataclass(frozen=True)
class VirtualDemoPosition:
    position_id: str
    symbol: str
    security_id: str
    quantity: int
    entry_price: float
    entry_order_id: str
    entry_fill_id: str
    opened_at: str
    status: str = STATUS_OPEN
    exit_price: float | None = None
    exit_order_id: str | None = None
    exit_fill_id: str | None = None
    closed_at: str | None = None
    realized_pnl: float = 0.0


@dataclass(frozen=True)
class VirtualDemoOrder:
    order_id: str
    symbol: str
    security_id: str
    side: str
    quantity: int
    price: float
    status: str
    reason: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class VirtualDemoFill:
    fill_id: str
    order_id: str
    symbol: str
    security_id: str
    side: str
    quantity: int
    price: float
    notional: float
    filled_at: str


@dataclass(frozen=True)
class VirtualDemoEvent:
    event_id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class VirtualDemoLedgerSnapshot:
    account: VirtualDemoAccount
    positions: list[VirtualDemoPosition]
    orders: list[VirtualDemoOrder]
    fills: list[VirtualDemoFill]
    events: list[VirtualDemoEvent]
    realized_pnl: float
    unrealized_pnl: float
    total_equity: float


@dataclass
class VirtualDemoLedger:
    account: VirtualDemoAccount
    positions: dict[str, VirtualDemoPosition] = field(default_factory=dict)
    orders: list[VirtualDemoOrder] = field(default_factory=list)
    fills: list[VirtualDemoFill] = field(default_factory=list)
    events: list[VirtualDemoEvent] = field(default_factory=list)
    brokerage_per_order: float = 0.0
    _order_sequence: Any = field(default_factory=lambda: count(1), init=False, repr=False)
    _fill_sequence: Any = field(default_factory=lambda: count(1), init=False, repr=False)
    _position_sequence: Any = field(default_factory=lambda: count(1), init=False, repr=False)
    _event_sequence: Any = field(default_factory=lambda: count(1), init=False, repr=False)

    @classmethod
    def create_account(
        cls,
        *,
        account_id: str,
        starting_cash: float,
        brokerage_per_order: float = 0.0,
        created_at: str | None = None,
    ) -> "VirtualDemoLedger":
        _validate_money(starting_cash, "starting_cash")
        _validate_non_negative_money(brokerage_per_order, "brokerage_per_order")
        timestamp = created_at or _utc_now()
        account = VirtualDemoAccount(
            account_id=account_id,
            starting_cash=round(float(starting_cash), 6),
            cash_balance=round(float(starting_cash), 6),
            created_at=timestamp,
        )
        ledger = cls(account=account, brokerage_per_order=round(float(brokerage_per_order), 6))
        ledger._record_event("account_created", asdict(account))
        return ledger

    def open_long_position(
        self,
        *,
        symbol: str,
        security_id: str,
        quantity: int,
        entry_price: float,
        timestamp: str | None = None,
    ) -> VirtualDemoOrder:
        _validate_symbol(symbol)
        _validate_security_id(security_id)
        _validate_quantity(quantity)
        _validate_money(entry_price, "entry_price")
        created_at = timestamp or _utc_now()
        order = VirtualDemoOrder(
            order_id=self._next_id("vdo", self._order_sequence),
            symbol=symbol,
            security_id=security_id,
            side=ORDER_BUY,
            quantity=quantity,
            price=round(float(entry_price), 6),
            status=STATUS_OPEN,
            created_at=created_at,
        )
        required_cash = round(quantity * float(entry_price) + self.brokerage_per_order, 6)
        if required_cash > self.account.cash_balance:
            rejected = VirtualDemoOrder(
                **{
                    **asdict(order),
                    "status": STATUS_REJECTED,
                    "reason": "insufficient_cash",
                }
            )
            self.orders.append(rejected)
            self._record_event("order_rejected", asdict(rejected))
            return rejected

        fill = VirtualDemoFill(
            fill_id=self._next_id("vdf", self._fill_sequence),
            order_id=order.order_id,
            symbol=symbol,
            security_id=security_id,
            side=ORDER_BUY,
            quantity=quantity,
            price=round(float(entry_price), 6),
            notional=round(quantity * float(entry_price), 6),
            filled_at=created_at,
        )
        position = VirtualDemoPosition(
            position_id=self._next_id("vdp", self._position_sequence),
            symbol=symbol,
            security_id=security_id,
            quantity=quantity,
            entry_price=round(float(entry_price), 6),
            entry_order_id=order.order_id,
            entry_fill_id=fill.fill_id,
            opened_at=created_at,
        )
        filled_order = VirtualDemoOrder(**{**asdict(order), "status": STATUS_CLOSED})
        self.account = VirtualDemoAccount(
            **{
                **asdict(self.account),
                "cash_balance": round(self.account.cash_balance - required_cash, 6),
            }
        )
        self.orders.append(filled_order)
        self.fills.append(fill)
        self.positions[position.position_id] = position
        self._record_event("order_filled", asdict(filled_order))
        self._record_event("position_opened", asdict(position))
        return filled_order

    def close_position(
        self,
        *,
        position_id: str,
        exit_price: float,
        timestamp: str | None = None,
    ) -> VirtualDemoOrder:
        _validate_money(exit_price, "exit_price")
        position = self.positions.get(position_id)
        if position is None:
            raise ValueError(f"Unknown virtual position: {position_id}")
        if position.status != STATUS_OPEN:
            raise ValueError(f"Virtual position is not open: {position_id}")

        created_at = timestamp or _utc_now()
        order = VirtualDemoOrder(
            order_id=self._next_id("vdo", self._order_sequence),
            symbol=position.symbol,
            security_id=position.security_id,
            side=ORDER_SELL,
            quantity=position.quantity,
            price=round(float(exit_price), 6),
            status=STATUS_CLOSED,
            created_at=created_at,
        )
        fill = VirtualDemoFill(
            fill_id=self._next_id("vdf", self._fill_sequence),
            order_id=order.order_id,
            symbol=position.symbol,
            security_id=position.security_id,
            side=ORDER_SELL,
            quantity=position.quantity,
            price=round(float(exit_price), 6),
            notional=round(position.quantity * float(exit_price), 6),
            filled_at=created_at,
        )
        realized_pnl = round((float(exit_price) - position.entry_price) * position.quantity, 6)
        closed_position = VirtualDemoPosition(
            **{
                **asdict(position),
                "status": STATUS_CLOSED,
                "exit_price": round(float(exit_price), 6),
                "exit_order_id": order.order_id,
                "exit_fill_id": fill.fill_id,
                "closed_at": created_at,
                "realized_pnl": realized_pnl,
            }
        )
        cash_received = round(fill.notional - self.brokerage_per_order, 6)
        self.account = VirtualDemoAccount(
            **{
                **asdict(self.account),
                "cash_balance": round(self.account.cash_balance + cash_received, 6),
            }
        )
        self.orders.append(order)
        self.fills.append(fill)
        self.positions[position_id] = closed_position
        self._record_event("order_filled", asdict(order))
        self._record_event("position_closed", asdict(closed_position))
        return order

    def open_positions(self) -> list[VirtualDemoPosition]:
        return [position for position in self.positions.values() if position.status == STATUS_OPEN]

    def closed_positions(self) -> list[VirtualDemoPosition]:
        return [position for position in self.positions.values() if position.status == STATUS_CLOSED]

    def realized_pnl(self) -> float:
        return round(sum(position.realized_pnl for position in self.closed_positions()), 6)

    def unrealized_pnl(self, latest_prices: dict[str, float]) -> float:
        total = 0.0
        for position in self.open_positions():
            if position.symbol not in latest_prices:
                continue
            latest_price = latest_prices[position.symbol]
            _validate_money(latest_price, f"latest_prices[{position.symbol}]")
            total += (float(latest_price) - position.entry_price) * position.quantity
        return round(total, 6)

    def market_value(self, latest_prices: dict[str, float]) -> float:
        total = 0.0
        for position in self.open_positions():
            if position.symbol not in latest_prices:
                continue
            latest_price = latest_prices[position.symbol]
            _validate_money(latest_price, f"latest_prices[{position.symbol}]")
            total += float(latest_price) * position.quantity
        return round(total, 6)

    def total_equity(self, latest_prices: dict[str, float] | None = None) -> float:
        prices = latest_prices or {}
        return round(self.account.cash_balance + self.market_value(prices), 6)

    def snapshot(self, latest_prices: dict[str, float] | None = None) -> VirtualDemoLedgerSnapshot:
        prices = latest_prices or {}
        return VirtualDemoLedgerSnapshot(
            account=self.account,
            positions=list(self.positions.values()),
            orders=list(self.orders),
            fills=list(self.fills),
            events=list(self.events),
            realized_pnl=self.realized_pnl(),
            unrealized_pnl=self.unrealized_pnl(prices),
            total_equity=self.total_equity(prices),
        )

    def summary(self, latest_prices: dict[str, float] | None = None) -> dict[str, Any]:
        snapshot = self.snapshot(latest_prices)
        return {
            "account": asdict(snapshot.account),
            "cash_balance": snapshot.account.cash_balance,
            "open_position_count": len([p for p in snapshot.positions if p.status == STATUS_OPEN]),
            "closed_position_count": len([p for p in snapshot.positions if p.status == STATUS_CLOSED]),
            "order_count": len(snapshot.orders),
            "fill_count": len(snapshot.fills),
            "event_count": len(snapshot.events),
            "realized_pnl": snapshot.realized_pnl,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "total_equity": snapshot.total_equity,
            "positions": [asdict(position) for position in snapshot.positions],
            "orders": [asdict(order) for order in snapshot.orders],
            "fills": [asdict(fill) for fill in snapshot.fills],
            "events": [asdict(event) for event in snapshot.events],
        }

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append(
            VirtualDemoEvent(
                event_id=self._next_id("vde", self._event_sequence),
                event_type=event_type,
                created_at=_utc_now(),
                payload=dict(payload),
            )
        )

    @staticmethod
    def _next_id(prefix: str, sequence: Any) -> str:
        return f"{prefix}_{next(sequence):06d}"


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _validate_symbol(value: str) -> None:
    if not value or not value.strip():
        raise ValueError("symbol is required")


def _validate_security_id(value: str) -> None:
    if not value or not value.strip():
        raise ValueError("security_id is required")


def _validate_quantity(value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError("quantity must be a positive integer")


def _validate_money(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{field_name} must be a finite positive number")


def _validate_non_negative_money(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
