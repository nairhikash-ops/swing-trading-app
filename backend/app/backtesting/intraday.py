from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

import pandas as pd


INTRADAY_COLUMNS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
IST = timezone(timedelta(hours=5, minutes=30))


def validate_intraday_candles(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(INTRADAY_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"intraday candle data missing columns: {', '.join(missing)}")
    result = frame.loc[:, INTRADAY_COLUMNS].copy()
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True, errors="raise")
    for column in ["open", "high", "low", "close", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result.empty:
        raise ValueError("intraday candle data is empty")
    if (result["symbol"] == "").any():
        raise ValueError("intraday candle symbol cannot be empty")
    if result.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("duplicate symbol/timestamp candles found")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("intraday OHLC prices must be positive")
    if (result["volume"] < 0).any():
        raise ValueError("intraday volume cannot be negative")
    invalid = (
        (result["high"] < result[["open", "close", "low"]].max(axis=1))
        | (result["low"] > result[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        raise ValueError("invalid intraday OHLC range found")
    return result.sort_values(["timestamp", "symbol"], kind="stable").reset_index(drop=True)


def parse_dhan_intraday_payload(payload: dict[str, Any], *, symbol: str) -> pd.DataFrame:
    keys = ("timestamp", "open", "high", "low", "close")
    arrays = {key: list(payload.get(key) or []) for key in keys}
    count = min((len(values) for values in arrays.values()), default=0)
    volume = list(payload.get("volume") or [])
    rows = []
    for index in range(count):
        rows.append(
            {
                "symbol": symbol,
                "timestamp": datetime.fromtimestamp(int(arrays["timestamp"][index]), tz=timezone.utc),
                "open": arrays["open"][index],
                "high": arrays["high"][index],
                "low": arrays["low"][index],
                "close": arrays["close"][index],
                "volume": volume[index] if index < len(volume) else 0,
            }
        )
    if not rows:
        return pd.DataFrame(columns=INTRADAY_COLUMNS)
    return validate_intraday_candles(pd.DataFrame(rows))


@dataclass(frozen=True)
class FetchWindow:
    symbol: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("fetch window end_date precedes start_date")
        if (self.end_date - self.start_date).days > 89:
            raise ValueError("Dhan intraday fetch windows cannot exceed 90 calendar days")

    @property
    def from_datetime(self) -> str:
        return datetime.combine(self.start_date, time(9, 15)).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def to_datetime(self) -> str:
        # Dhan's upper boundary is exclusive.
        return datetime.combine(self.end_date + timedelta(days=1), time(0, 0)).strftime("%Y-%m-%d %H:%M:%S")


def merge_required_windows(
    requirements: Iterable[tuple[str, date, date]], *, max_calendar_days: int = 90
) -> list[FetchWindow]:
    """Merge overlapping candidate windows without exceeding the provider's request cap."""
    if not 1 <= max_calendar_days <= 90:
        raise ValueError("max_calendar_days must be between 1 and 90")
    grouped: dict[str, list[tuple[date, date]]] = {}
    for symbol, start, end in requirements:
        if end < start:
            raise ValueError("required window end precedes start")
        while (end - start).days >= max_calendar_days:
            chunk_end = start + timedelta(days=max_calendar_days - 1)
            grouped.setdefault(symbol.upper(), []).append((start, chunk_end))
            start = chunk_end + timedelta(days=1)
        grouped.setdefault(symbol.upper(), []).append((start, end))

    result: list[FetchWindow] = []
    for symbol, ranges in sorted(grouped.items()):
        cursor_start: date | None = None
        cursor_end: date | None = None
        for start, end in sorted(ranges):
            if cursor_start is None:
                cursor_start, cursor_end = start, end
                continue
            proposed_end = max(cursor_end, end)
            if start <= cursor_end + timedelta(days=1) and (proposed_end - cursor_start).days < max_calendar_days:
                cursor_end = proposed_end
            else:
                result.append(FetchWindow(symbol, cursor_start, cursor_end))
                cursor_start, cursor_end = start, end
        if cursor_start is not None and cursor_end is not None:
            result.append(FetchWindow(symbol, cursor_start, cursor_end))
    return result


@dataclass(frozen=True)
class MatsyaIntradayDataSource:
    database_url: str
    universe_name: str = "NIFTY_500"
    interval_minutes: int = 15

    def load(
        self, *, start_date: str | None = None, end_date: str | None = None,
        symbols: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        import psycopg

        filters = ["ic.provider_code = 'dhan'", "ic.interval_minutes = %s", "mu.universe_name = %s", "mu.active = true"]
        params: list[Any] = [self.interval_minutes, self.universe_name]
        if start_date:
            filters.append("ic.candle_time >= %s::date")
            params.append(start_date)
        if end_date:
            filters.append("ic.candle_time < (%s::date + interval '1 day')")
            params.append(end_date)
        normalized_symbols = sorted({str(symbol).upper() for symbol in (symbols or [])})
        if normalized_symbols:
            filters.append("upper(mu.symbol) = ANY(%s)")
            params.append(normalized_symbols)
        query = f"""
            SELECT upper(mu.symbol), ic.candle_time, ic.open_price, ic.high_price,
                   ic.low_price, ic.close_price, ic.volume
            FROM matsya.market_universe_members mu
            JOIN matsya.instruments i ON i.id = (
                SELECT candidate.id FROM matsya.instruments candidate
                WHERE candidate.provider_code = 'dhan' AND candidate.active = true
                  AND candidate.exchange_id = 'NSE' AND candidate.segment = 'E'
                  AND candidate.instrument = 'EQUITY'
                  AND ((btrim(candidate.isin) <> '' AND btrim(mu.isin) <> '' AND upper(btrim(candidate.isin)) = upper(btrim(mu.isin)))
                    OR ((btrim(candidate.isin) = '' OR btrim(mu.isin) = '') AND
                        (upper(btrim(candidate.symbol_name)) = upper(btrim(mu.symbol)) OR
                         upper(btrim(candidate.underlying_symbol)) = upper(btrim(mu.symbol)))))
                ORDER BY CASE WHEN btrim(candidate.isin) <> '' AND btrim(mu.isin) <> '' AND upper(btrim(candidate.isin)) = upper(btrim(mu.isin)) THEN 0 ELSE 1 END,
                         CASE WHEN candidate.series = 'EQ' THEN 0 ELSE 1 END, candidate.id LIMIT 1
            )
            JOIN matsya.ohlcv_intraday ic ON ic.security_id = i.security_id
            WHERE {' AND '.join(filters)}
            ORDER BY ic.candle_time, mu.symbol
        """
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        if not rows:
            return pd.DataFrame(columns=INTRADAY_COLUMNS)
        return validate_intraday_candles(pd.DataFrame(rows, columns=INTRADAY_COLUMNS))
