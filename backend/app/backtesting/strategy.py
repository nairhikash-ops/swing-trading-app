from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

from .models import Signal


@runtime_checkable
class Strategy(Protocol):
    """Small plug-in contract; strategies never execute or account for trades."""

    @property
    def name(self) -> str: ...

    def parameters(self) -> dict[str, Any]: ...

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        """Return candles plus any indicators, using past/current bars only."""
        ...

    def generate_signals(self, prepared: pd.DataFrame) -> list[Signal]:
        """Return close-known signals. The engine fills them on a later open."""
        ...
