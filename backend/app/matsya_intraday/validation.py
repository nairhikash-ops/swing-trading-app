from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


IST = timezone(timedelta(hours=5, minutes=30))
ARRAY_FIELDS = ("open", "high", "low", "close", "volume", "timestamp")


@dataclass(frozen=True)
class MinuteCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class DayValidation:
    trading_date: date
    status: str
    candles: tuple[MinuteCandle, ...]
    defects: tuple[str, ...]
    missing_minutes: tuple[str, ...]
    zero_volume_minutes: int


def expected_session_times(trading_date: date) -> tuple[datetime, ...]:
    start = datetime.combine(trading_date, time(9, 15), tzinfo=IST)
    return tuple(start + timedelta(minutes=index) for index in range(375))


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"non-numeric value {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite value {value!r}")
    return result


def validate_payload(payload: Any, requested_dates: list[date]) -> dict[date, DayValidation]:
    if not isinstance(payload, dict):
        return {day: DayValidation(day, "rejected", (), ("payload_not_object",), (), 0) for day in requested_dates}
    arrays: dict[str, list[Any]] = {}
    malformed: list[str] = []
    for field in ARRAY_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list):
            malformed.append(f"{field}_not_array")
            arrays[field] = []
        else:
            arrays[field] = value
    lengths = {field: len(values) for field, values in arrays.items()}
    if len(set(lengths.values())) > 1:
        malformed.append("array_length_mismatch:" + ",".join(f"{key}={lengths[key]}" for key in ARRAY_FIELDS))
    if malformed:
        return {day: DayValidation(day, "rejected", (), tuple(malformed), (), 0) for day in requested_dates}

    by_date: dict[date, list[MinuteCandle]] = {}
    parse_defects: dict[date, list[str]] = {day: [] for day in requested_dates}
    unexpected_dates: set[date] = set()
    for index in range(lengths["timestamp"]):
        try:
            stamp = datetime.fromtimestamp(int(arrays["timestamp"][index]), tz=timezone.utc).astimezone(IST)
            candle = MinuteCandle(
                stamp,
                _decimal(arrays["open"][index]),
                _decimal(arrays["high"][index]),
                _decimal(arrays["low"][index]),
                _decimal(arrays["close"][index]),
                _decimal(arrays["volume"][index]),
            )
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            for day in requested_dates:
                parse_defects[day].append(f"malformed_candle[{index}]:{exc}")
            continue
        if stamp.date() not in requested_dates:
            unexpected_dates.add(stamp.date())
        by_date.setdefault(stamp.date(), []).append(candle)

    results: dict[date, DayValidation] = {}
    for day in requested_dates:
        candles = sorted(by_date.get(day, []), key=lambda row: row.timestamp)
        if not candles and not parse_defects[day]:
            results[day] = DayValidation(day, "unavailable", (), ("no_candles",), (), 0)
            continue
        defects = list(parse_defects[day])
        stamps = [row.timestamp for row in candles]
        if len(stamps) != len(set(stamps)):
            defects.append("duplicate_timestamps")
        if any(right <= left for left, right in zip(stamps, stamps[1:])):
            defects.append("timestamps_not_strictly_increasing")
        expected = set(expected_session_times(day))
        actual = set(stamps)
        outside = sorted(actual - expected)
        if outside:
            defects.append("out_of_session:" + ",".join(value.strftime("%H:%M") for value in outside[:10]))
        if unexpected_dates:
            defects.append("wrong_dates:" + ",".join(sorted(value.isoformat() for value in unexpected_dates)))
        for index, row in enumerate(candles):
            if min(row.open, row.high, row.low, row.close) <= 0:
                defects.append(f"non_positive_price[{index}]")
            if row.high < max(row.open, row.low, row.close) or row.low > min(row.open, row.high, row.close):
                defects.append(f"invalid_ohlc[{index}]")
            if row.volume < 0:
                defects.append(f"negative_volume[{index}]")
        missing = tuple(value.strftime("%H:%M") for value in sorted(expected - actual))
        zero_volume = sum(row.volume == 0 for row in candles)
        fatal = bool(defects)
        status = "rejected" if fatal else ("warning" if missing else "accepted")
        # Zero is valid volume (especially for illiquid symbols); retain the count as quality metadata.
        warning_defects = [f"missing_session_minutes:{len(missing)}"] if missing else []
        results[day] = DayValidation(day, status, tuple(candles), tuple(defects + warning_defects), missing, zero_volume)
    return results
