from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable

from .validation import MinuteCandle


SUPPORTED_INTERVALS = (5, 15, 30, 60, 1440)


@dataclass(frozen=True)
class AggregatedCandle:
    interval_minutes: int
    bucket_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source_minutes: int


def aggregate(candles: Iterable[MinuteCandle], interval_minutes: int) -> tuple[AggregatedCandle, ...]:
    if interval_minutes not in SUPPORTED_INTERVALS:
        raise ValueError(f"unsupported interval {interval_minutes}")
    ordered = sorted(candles, key=lambda row: row.timestamp)
    if not ordered:
        return ()
    session_start = ordered[0].timestamp.replace(hour=9, minute=15, second=0, microsecond=0)
    groups: dict[datetime, list[MinuteCandle]] = {}
    for row in ordered:
        if interval_minutes == 1440:
            bucket = session_start
        else:
            offset = int((row.timestamp - session_start).total_seconds() // 60)
            bucket = session_start + timedelta(minutes=(offset // interval_minutes) * interval_minutes)
        groups.setdefault(bucket, []).append(row)
    return tuple(
        AggregatedCandle(
            interval_minutes,
            bucket,
            rows[0].open,
            max(row.high for row in rows),
            min(row.low for row in rows),
            rows[-1].close,
            sum((row.volume for row in rows), Decimal("0")),
            len(rows),
        )
        for bucket, rows in sorted(groups.items())
    )


def daily_ohlcv(candles: Iterable[MinuteCandle]) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal] | None:
    rows = aggregate(candles, 1440)
    if not rows:
        return None
    row = rows[0]
    return row.open, row.high, row.low, row.close, row.volume
