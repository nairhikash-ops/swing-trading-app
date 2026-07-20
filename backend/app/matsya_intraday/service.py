from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from app.dhan_client import DhanClient

from .validation import DayValidation, validate_payload


Fetch = Callable[..., Awaitable[dict[str, Any]]]


def calendar_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date precedes start date")
    if (end - start).days > 29:
        raise ValueError("manual intraday ranges are limited to 30 calendar days")
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


async def fetch_and_validate(
    *, token: str, symbol: str, security_id: str, start: date, end: date,
    expected_dates: list[date], client: DhanClient | None = None,
) -> tuple[dict[str, Any], dict[date, DayValidation], str, str]:
    calendar_dates(start, end)
    from_date = start.isoformat()
    to_date = (end + timedelta(days=1)).isoformat()
    payload = await (client or DhanClient()).historical_intraday(
        access_token=token, security_id=security_id, exchange_segment="NSE_EQ",
        instrument="EQUITY", from_date=from_date, to_date=to_date, interval="1",
    )
    return payload, validate_payload(payload, expected_dates), from_date, to_date
