from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .aggregation import daily_ohlcv
from .validation import MinuteCandle


NORMAL_SESSION_FIELDS = (
    "intraday_open",
    "intraday_high",
    "intraday_low",
    "last_minute_close",
    "normal_session_volume",
)
OFFICIAL_FIELDS = (
    "official_daily_open",
    "official_daily_high",
    "official_daily_low",
    "official_daily_close",
    "official_daily_volume",
)


@dataclass(frozen=True)
class Reconciliation:
    normal_session: dict[str, Decimal]
    official_daily: dict[str, Decimal] | None
    absolute_differences: dict[str, Decimal] | None
    percentage_differences: dict[str, Decimal | None] | None
    open_high_low_match: bool
    close_match: bool
    volume_match: bool
    structural_acceptance_gate_passed: bool
    cross_source_status: str
    explanation: str


def reconcile(candles: Iterable[MinuteCandle], authoritative: tuple[object, ...] | None) -> Reconciliation:
    candle_rows = tuple(candles)
    derived = daily_ohlcv(candle_rows)
    if derived is None:
        raise ValueError("cannot reconcile an empty day")
    normal_session = dict(zip(NORMAL_SESSION_FIELDS, derived, strict=True))
    if authoritative is None:
        return Reconciliation(normal_session, None, None, None, False, False, False, False, "unavailable",
                              "official daily candle unavailable")
    official = {field: Decimal(str(value)) for field, value in zip(OFFICIAL_FIELDS, authoritative, strict=True)}
    pairs = dict(zip(NORMAL_SESSION_FIELDS, OFFICIAL_FIELDS, strict=True))
    absolute = {normal: abs(normal_session[normal] - official[daily]) for normal, daily in pairs.items()}
    percentage = {
        normal: ((absolute[normal] / abs(official[daily])) * 100 if official[daily] else None)
        for normal, daily in pairs.items()
    }
    ohl_match = all(absolute[field] == 0 for field in ("intraday_open", "intraday_high", "intraday_low"))
    close_match = absolute["last_minute_close"] == 0
    volume_match = absolute["normal_session_volume"] == 0
    explanation = (
        "normal-session open/high/low validated; close and volume comparisons are informational"
        if ohl_match else "normal-session open/high/low differs from the official daily candle"
    )
    return Reconciliation(normal_session, official, absolute, percentage, ohl_match, close_match,
                          volume_match, len(candle_rows) == 375, "validated" if ohl_match else "warning",
                          explanation)
