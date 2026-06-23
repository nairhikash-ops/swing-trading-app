from __future__ import annotations

from datetime import date, datetime, timedelta

from app.timezone import IST


def is_weekend(trading_date: date) -> bool:
    return trading_date.weekday() >= 5


def is_trading_day(trading_date: date, holidays: set[date] | None = None) -> bool:
    if is_weekend(trading_date):
        return False
    return trading_date not in (holidays or set())


def previous_trading_day(from_date: date, holidays: set[date] | None = None) -> date:
    candidate = from_date - timedelta(days=1)
    while not is_trading_day(candidate, holidays):
        candidate -= timedelta(days=1)
    return candidate


def latest_completed_trading_day(
    now_ist: datetime,
    finalized_after_hour_ist: int,
    holidays: set[date] | None = None,
) -> date:
    resolved_now = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    today = resolved_now.date()
    if not is_trading_day(today, holidays):
        return previous_trading_day(today, holidays)
    if resolved_now.hour < finalized_after_hour_ist:
        return previous_trading_day(today, holidays)
    return today


def expected_latest_candle_date(
    now_ist: datetime,
    finalized_after_hour_ist: int,
    holidays: set[date] | None = None,
) -> date:
    return latest_completed_trading_day(now_ist, finalized_after_hour_ist, holidays)
