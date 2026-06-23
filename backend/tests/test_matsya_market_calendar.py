from __future__ import annotations

from datetime import date, datetime

from app.matsya.market_calendar import expected_latest_candle_date
from app.timezone import IST


def ist_at(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=IST)


def test_saturday_uses_previous_friday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 27, 12), 18) == date(2026, 6, 26)


def test_sunday_uses_previous_friday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 28, 12), 18) == date(2026, 6, 26)


def test_wednesday_before_finalization_uses_tuesday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 24, 17), 18) == date(2026, 6, 23)


def test_wednesday_after_finalization_uses_wednesday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 24, 18), 18) == date(2026, 6, 24)


def test_holiday_wednesday_uses_previous_trading_day() -> None:
    holidays = {date(2026, 6, 24)}

    assert expected_latest_candle_date(ist_at(2026, 6, 24, 18), 18, holidays) == date(2026, 6, 23)


def test_monday_before_finalization_uses_friday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 29, 9), 18) == date(2026, 6, 26)


def test_monday_after_finalization_uses_monday() -> None:
    assert expected_latest_candle_date(ist_at(2026, 6, 29, 18), 18) == date(2026, 6, 29)
