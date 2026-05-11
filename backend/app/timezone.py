from datetime import datetime
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=IST).astimezone(UTC)
    return value.astimezone(UTC)


def parse_dhan_datetime(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return to_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return to_utc(datetime.fromisoformat(text))
