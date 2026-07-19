from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AmbiguousFillPolicy = Literal["stop_first", "target_first"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    max_positions: int = 5
    max_allocation_pct: float = 0.20
    risk_per_trade_pct: float = 0.01
    commission_bps: float = 3.0
    slippage_bps: float = 5.0
    taxes_bps: float = 12.0
    ambiguous_fill_policy: AmbiguousFillPolicy = "stop_first"
    force_liquidation: bool = True

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        for name in ("max_allocation_pct", "risk_per_trade_pct"):
            value = float(getattr(self, name))
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in ("commission_bps", "slippage_bps", "taxes_bps"):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.ambiguous_fill_policy not in {"stop_first", "target_first"}:
            raise ValueError("unsupported ambiguous_fill_policy")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Signal:
    symbol: str
    signal_date: str
    stop_price: float
    target_price: float
    score: float = 0.0
    max_holding_bars: int = 20
    entry_valid_bars: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("signal symbol is required")
        if self.stop_price <= 0 or self.target_price <= 0:
            raise ValueError("signal stop and target must be positive")
        if self.max_holding_bars <= 0:
            raise ValueError("max_holding_bars must be positive")
        if self.entry_valid_bars <= 0:
            raise ValueError("entry_valid_bars must be positive")
