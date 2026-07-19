from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Literal

from app.matsya.db import connect
from app.matsya.ohlcv_service import INSTRUMENT_LATERAL_JOIN_SQL, recent_trading_days
from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import _token_state
from app.matsya.market_calendar import expected_latest_candle_date
from app.timezone import IST


DEFAULT_LIMIT = 250
MAX_LIMIT = 5000
DEFAULT_LATEST_DAYS = 365
MAX_LATEST_DAYS = 2000


class MatsyaMarketDataStore:
    def __init__(self, settings: MatsyaSettings) -> None:
        self.settings = settings

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        conn = connect(self.settings)
        try:
            yield conn
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        validation = self.validation()
        with self._connect() as conn:
            instruments = _one(conn.execute("SELECT COUNT(*) AS count FROM matsya.instruments WHERE active = true"))
            universe = _one(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM matsya.market_universe_members
                    WHERE universe_name = %s AND active = true
                    """,
                    (self.settings.ohlcv_universe_name,),
                )
            )
            latest_run = _one(
                conn.execute(
                    """
                    SELECT id, status, total_symbols, mapped_symbols, skipped_symbols, error_message,
                           started_at, updated_at, completed_at
                    FROM matsya.ohlcv_fetch_runs
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            )
            token = _one(
                conn.execute(
                    """
                    SELECT expiry_time, profile_json, last_error, last_renew_attempt_at
                    FROM matsya.dhan_token_state
                    WHERE id = 1
                    """
                )
            )
        token_state = "missing"
        if token:
            token_state = _token_state(_TokenStateAdapter(token), self.settings.renew_before_minutes)
        return {
            "total_instruments": int((instruments or {}).get("count") or 0),
            "universe_members": int((universe or {}).get("count") or 0),
            "ohlcv_row_count": validation["total_rows"],
            "first_candle_date": validation["first_stored_candle_date"],
            "latest_candle_date": validation["latest_stored_candle_date"],
            "symbols_with_candles": validation["symbols_with_candles"],
            "duplicate_count": validation["duplicate_count"],
            "null_ohlcv_count": validation["null_ohlcv_count"],
            "bad_ohlc_count": validation["bad_ohlc_count"],
            "negative_volume_count": validation["negative_volume_count"],
            "stale_symbols": validation["stale_symbols"],
            "missing_recent_symbol_dates": validation["missing_recent_symbol_dates"],
            "latest_ohlcv_run": latest_run or {},
            "token_state": token_state,
        }

    def symbols(self, *, universe: str, active: bool, limit: int, offset: int) -> dict[str, Any]:
        resolved_limit = clamp_limit(limit)
        resolved_offset = max(0, offset)
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    f"""
                    WITH mapped AS (
                        SELECT m.symbol, m.company_name, m.active, mi.security_id, i.exchange_id, i.segment,
                               i.instrument, i.symbol_name, i.underlying_symbol
                        FROM matsya.market_universe_members m
                        {INSTRUMENT_LATERAL_JOIN_SQL}
                        JOIN matsya.instruments i ON i.id = mi.id
                        WHERE m.universe_name = %s AND m.active = %s AND mi.id IS NOT NULL
                    ),
                    candle_stats AS (
                        SELECT security_id, MIN(trading_date) AS first_candle_date,
                               MAX(trading_date) AS latest_candle_date, COUNT(*) AS candle_count
                        FROM matsya.ohlcv_daily
                        WHERE provider_code = 'dhan'
                        GROUP BY security_id
                    )
                    SELECT mapped.symbol, mapped.company_name, mapped.exchange_id AS exchange,
                           mapped.segment, mapped.instrument, mapped.security_id,
                           candle_stats.first_candle_date, candle_stats.latest_candle_date,
                           COALESCE(candle_stats.candle_count, 0) AS candle_count
                    FROM mapped
                    LEFT JOIN candle_stats ON candle_stats.security_id = mapped.security_id
                    ORDER BY mapped.symbol
                    LIMIT %s OFFSET %s
                    """,
                    (universe, active, resolved_limit, resolved_offset),
                )
            )
        return {
            "universe": universe,
            "limit": resolved_limit,
            "offset": resolved_offset,
            "symbols": [
                {
                    **row,
                    "first_candle_date": _date_text(row.get("first_candle_date")),
                    "latest_candle_date": _date_text(row.get("latest_candle_date")),
                    "candle_count": int(row.get("candle_count") or 0),
                    "freshness_state": freshness_state(
                        _optional_date_value(row.get("latest_candle_date")),
                        self.expected_latest_date(),
                    ),
                }
                for row in rows
            ],
        }

    def ohlcv(
        self,
        *,
        symbol: str | None,
        security_id: str | None,
        from_date: date | None,
        to_date: date | None,
        limit: int,
        order: Literal["asc", "desc"],
    ) -> dict[str, Any] | None:
        instrument = self.resolve_instrument(symbol=symbol, security_id=security_id)
        if not instrument:
            return None
        resolved_limit = clamp_limit(limit)
        order_sql = "ASC" if order == "asc" else "DESC"
        params: list[Any] = [instrument["security_id"]]
        where = "provider_code = 'dhan' AND security_id = %s"
        if from_date:
            where += " AND trading_date >= %s"
            params.append(from_date)
        if to_date:
            where += " AND trading_date <= %s"
            params.append(to_date)
        params.append(resolved_limit)
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    f"""
                    SELECT trading_date, open_price, high_price, low_price, close_price, volume
                    FROM matsya.ohlcv_daily
                    WHERE {where}
                    ORDER BY trading_date {order_sql}
                    LIMIT %s
                    """,
                    tuple(params),
                )
            )
        return {
            "symbol": instrument["symbol"],
            "security_id": instrument["security_id"],
            "exchange_segment": self.settings.dhan_historical_exchange_segment,
            "instrument": self.settings.dhan_historical_instrument,
            "limit": resolved_limit,
            "order": order,
            "candles": [_candle(row) for row in rows],
        }

    def latest_ohlcv(self, *, symbol: str | None, security_id: str | None, days: int) -> dict[str, Any] | None:
        instrument = self.resolve_instrument(symbol=symbol, security_id=security_id)
        if not instrument:
            return None
        resolved_days = min(max(1, days), MAX_LATEST_DAYS)
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    """
                    SELECT trading_date, open_price, high_price, low_price, close_price, volume
                    FROM (
                        SELECT trading_date, open_price, high_price, low_price, close_price, volume
                        FROM matsya.ohlcv_daily
                        WHERE provider_code = 'dhan' AND security_id = %s
                        ORDER BY trading_date DESC
                        LIMIT %s
                    ) latest
                    ORDER BY trading_date ASC
                    """,
                    (instrument["security_id"], resolved_days),
                )
            )
        return {
            "symbol": instrument["symbol"],
            "security_id": instrument["security_id"],
            "exchange_segment": self.settings.dhan_historical_exchange_segment,
            "instrument": self.settings.dhan_historical_instrument,
            "days": resolved_days,
            "candles": [_candle(row) for row in rows],
        }

    def trading_dates(self, *, from_date: date, to_date: date) -> dict[str, Any]:
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    """
                    SELECT DISTINCT trading_date
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan'
                      AND trading_date >= %s
                      AND trading_date <= %s
                    ORDER BY trading_date ASC
                    """,
                    (from_date, to_date),
                )
            )
        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "trading_dates": [_date_text(row["trading_date"]) for row in rows],
        }

    def validation(self) -> dict[str, Any]:
        expected_latest = self.expected_latest_date()
        recent_dates = recent_trading_days(
            expected_latest,
            self.settings.ohlcv_validation_trading_days,
            self.trading_holidays(),
        )
        validation_start = recent_dates[0] if recent_dates else expected_latest
        date_values_sql = ", ".join(["(%s::date)"] * len(recent_dates)) or "(%s::date)"
        date_params = [day.isoformat() for day in recent_dates] or [expected_latest.isoformat()]
        with self._connect() as conn:
            totals = _one(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total_rows, COUNT(DISTINCT security_id) AS symbols_with_candles,
                           MIN(trading_date) AS first_stored_candle_date,
                           MAX(trading_date) AS latest_stored_candle_date
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan'
                    """
                )
            )
            duplicates = _one(
                conn.execute(
                    """
                    SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_count
                    FROM (
                        SELECT provider_code, security_id, trading_date, COUNT(*) AS cnt
                        FROM matsya.ohlcv_daily
                        GROUP BY provider_code, security_id, trading_date
                        HAVING COUNT(*) > 1
                    ) duplicate_rows
                    """
                )
            )
            bad_rows = _one(
                conn.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE open_price IS NULL OR high_price IS NULL OR low_price IS NULL
                               OR close_price IS NULL OR volume IS NULL
                        ) AS null_ohlcv_count,
                        COUNT(*) FILTER (
                            WHERE high_price < low_price OR close_price < low_price OR close_price > high_price
                        ) AS bad_ohlc_count,
                        COUNT(*) FILTER (WHERE volume < 0) AS negative_volume_count
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan'
                    """
                )
            )
            coverage = _one(
                conn.execute(
                    f"""
                    WITH mapped AS (
                        SELECT m.symbol, mi.security_id
                        FROM matsya.market_universe_members m
                        {INSTRUMENT_LATERAL_JOIN_SQL}
                        WHERE m.universe_name = %s AND m.active = true AND mi.id IS NOT NULL
                    ),
                    latest AS (
                        SELECT mapped.symbol, mapped.security_id, MAX(dc.trading_date) AS latest_stored_candle_date
                        FROM mapped
                        LEFT JOIN matsya.ohlcv_daily dc ON dc.provider_code = 'dhan'
                          AND dc.security_id = mapped.security_id
                        GROUP BY mapped.symbol, mapped.security_id
                    ),
                    expected_dates(trading_date) AS (
                        VALUES {date_values_sql}
                    ),
                    missing_recent AS (
                        SELECT mapped.security_id, expected_dates.trading_date
                        FROM mapped
                        CROSS JOIN expected_dates
                        LEFT JOIN matsya.ohlcv_daily dc ON dc.provider_code = 'dhan'
                          AND dc.security_id = mapped.security_id
                          AND dc.trading_date = expected_dates.trading_date
                        WHERE dc.id IS NULL
                    )
                    SELECT
                        COUNT(*) AS mapped_symbols,
                        COUNT(*) FILTER (WHERE latest_stored_candle_date IS NULL) AS zero_candle_symbols,
                        COUNT(*) FILTER (
                            WHERE latest_stored_candle_date IS NOT NULL AND latest_stored_candle_date < %s::date
                        ) AS stale_symbols,
                        (SELECT COUNT(*) FROM missing_recent) AS missing_recent_symbol_dates
                    FROM latest
                    """,
                    tuple([self.settings.ohlcv_universe_name, *date_params, expected_latest.isoformat()]),
                )
            )
        return {
            "total_rows": int((totals or {}).get("total_rows") or 0),
            "symbols_with_candles": int((totals or {}).get("symbols_with_candles") or 0),
            "first_stored_candle_date": _date_text((totals or {}).get("first_stored_candle_date")),
            "latest_stored_candle_date": _date_text((totals or {}).get("latest_stored_candle_date")),
            "duplicate_count": int((duplicates or {}).get("duplicate_count") or 0),
            "null_ohlcv_count": int((bad_rows or {}).get("null_ohlcv_count") or 0),
            "bad_ohlc_count": int((bad_rows or {}).get("bad_ohlc_count") or 0),
            "negative_volume_count": int((bad_rows or {}).get("negative_volume_count") or 0),
            "zero_candle_symbols": int((coverage or {}).get("zero_candle_symbols") or 0),
            "stale_symbols": int((coverage or {}).get("stale_symbols") or 0),
            "missing_recent_symbol_dates": int((coverage or {}).get("missing_recent_symbol_dates") or 0),
            "expected_latest_candle_date": expected_latest.isoformat(),
            "validation_start_date": validation_start.isoformat(),
        }

    def resolve_instrument(self, *, symbol: str | None, security_id: str | None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if security_id:
                row = _one(
                    conn.execute(
                        """
                        SELECT COALESCE(NULLIF(symbol_name, ''), underlying_symbol) AS symbol, security_id
                        FROM matsya.instruments
                        WHERE provider_code = 'dhan' AND active = true AND exchange_id = 'NSE'
                          AND segment = 'E' AND instrument = 'EQUITY' AND security_id = %s
                        ORDER BY id
                        LIMIT 1
                        """,
                        (security_id,),
                    )
                )
            else:
                row = _one(
                    conn.execute(
                        """
                        SELECT COALESCE(NULLIF(symbol_name, ''), underlying_symbol) AS symbol, security_id
                        FROM matsya.instruments
                        WHERE provider_code = 'dhan' AND active = true AND exchange_id = 'NSE'
                          AND segment = 'E' AND instrument = 'EQUITY'
                          AND (UPPER(symbol_name) = UPPER(%s) OR UPPER(underlying_symbol) = UPPER(%s))
                        ORDER BY CASE WHEN UPPER(symbol_name) = UPPER(%s) THEN 0 ELSE 1 END, id
                        LIMIT 1
                        """,
                        (symbol, symbol, symbol),
                    )
                )
        return row

    def trading_holidays(self) -> set[date]:
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    "SELECT holiday_date FROM matsya.trading_holidays WHERE market_code = %s",
                    (self.settings.market_code,),
                )
            )
        return {_date_value(row["holiday_date"]) for row in rows}

    def expected_latest_date(self) -> date:
        from datetime import datetime

        return expected_latest_candle_date(
            datetime.now(tz=IST),
            self.settings.historical_finalized_after_hour_ist,
            self.trading_holidays(),
        )


class _TokenStateAdapter:
    def __init__(self, row: dict[str, Any]) -> None:
        self.expiry_time = row.get("expiry_time")
        self.last_error = row.get("last_error") or ""
        self.last_renew_attempt_at = row.get("last_renew_attempt_at")
        self.profile = row.get("profile_json") or {}


def clamp_limit(value: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    if value is None:
        return default
    return min(max(1, value), maximum)


def freshness_state(latest_candle_date: date | None, expected_latest: date) -> str:
    if latest_candle_date is None:
        return "NO_OHLCV_DATA"
    if latest_candle_date >= expected_latest:
        return "FRESH"
    return "STALE_OHLCV_DATA"


def _candle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trading_date": _date_text(row["trading_date"]),
        "open": float(row["open_price"]),
        "high": float(row["high_price"]),
        "low": float(row["low_price"]),
        "close": float(row["close_price"]),
        "volume": float(row["volume"]),
    }


def _one(cursor: Any) -> dict[str, Any] | None:
    rows = _all(cursor)
    return rows[0] if rows else None


def _all(cursor: Any) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row, strict=False)) for row in cursor.fetchall()]


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _date_value(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _optional_date_value(value: Any) -> date | None:
    if value is None:
        return None
    return _date_value(value)
