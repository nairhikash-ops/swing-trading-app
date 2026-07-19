from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


CANONICAL_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]


def validate_candles(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(CANONICAL_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"candle data missing columns: {', '.join(missing)}")
    result = frame.loc[:, CANONICAL_COLUMNS].copy()
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    for column in ["open", "high", "low", "close", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result.empty:
        raise ValueError("candle data is empty")
    if (result["symbol"] == "").any():
        raise ValueError("candle symbol cannot be empty")
    if result.duplicated(["symbol", "date"]).any():
        raise ValueError("duplicate symbol/date candles found")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (result["volume"] < 0).any():
        raise ValueError("volume cannot be negative")
    invalid_range = (
        (result["high"] < result[["open", "close", "low"]].max(axis=1))
        | (result["low"] > result[["open", "close", "high"]].min(axis=1))
    )
    if invalid_range.any():
        raise ValueError("invalid OHLC range found")
    return result.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)


class CandleDataSource(Protocol):
    def load(self, *, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame: ...


@dataclass(frozen=True)
class CsvDataSource:
    path: Path

    def load(self, *, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        frame = validate_candles(pd.read_csv(self.path))
        if start_date:
            frame = frame[frame["date"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        return validate_candles(frame)


@dataclass(frozen=True)
class MatsyaPostgresDataSource:
    database_url: str
    universe_name: str = "NIFTY_500"

    def load(self, *, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        import psycopg

        filters = ["dc.provider_code = 'dhan'", "mu.universe_name = %s", "mu.active = true"]
        params: list[str] = [self.universe_name]
        if start_date:
            filters.append("dc.trading_date >= %s")
            params.append(start_date)
        if end_date:
            filters.append("dc.trading_date <= %s")
            params.append(end_date)
        query = f"""
            SELECT upper(mu.symbol) AS symbol, dc.trading_date AS date,
                   dc.open_price AS open, dc.high_price AS high,
                   dc.low_price AS low, dc.close_price AS close, dc.volume
            FROM matsya.market_universe_members mu
            JOIN LATERAL (
                SELECT candidate.security_id
                FROM matsya.instruments candidate
                WHERE candidate.provider_code = 'dhan'
                  AND candidate.active = true
                  AND candidate.exchange_id = 'NSE'
                  AND candidate.segment = 'E'
                  AND candidate.instrument = 'EQUITY'
                  AND (
                    (btrim(candidate.isin) <> '' AND btrim(mu.isin) <> '' AND upper(btrim(candidate.isin)) = upper(btrim(mu.isin)))
                    OR ((btrim(candidate.isin) = '' OR btrim(mu.isin) = '') AND
                        (upper(btrim(candidate.symbol_name)) = upper(btrim(mu.symbol)) OR
                         upper(btrim(candidate.underlying_symbol)) = upper(btrim(mu.symbol))))
                  )
                ORDER BY
                  CASE WHEN btrim(candidate.isin) <> '' AND btrim(mu.isin) <> '' AND upper(btrim(candidate.isin)) = upper(btrim(mu.isin)) THEN 0 ELSE 1 END,
                  CASE WHEN candidate.series = 'EQ' THEN 0 ELSE 1 END,
                  CASE WHEN upper(btrim(candidate.symbol_name)) = upper(btrim(mu.symbol)) THEN 0 ELSE 1 END,
                  candidate.id
                LIMIT 1
            ) i ON true
            JOIN matsya.ohlcv_daily dc
              ON dc.provider_code = 'dhan' AND dc.security_id = i.security_id
            WHERE {' AND '.join(filters)}
            ORDER BY dc.trading_date, mu.symbol
        """
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                columns = [item.name for item in cursor.description or []]
        return validate_candles(pd.DataFrame(rows, columns=columns))


def load_or_create_cache(
    source: CandleDataSource,
    cache_path: Path | None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    refresh: bool = False,
) -> tuple[pd.DataFrame, bool]:
    """Use a portable gzip CSV cache to avoid repeated database/network reads."""
    if cache_path and cache_path.exists() and not refresh:
        cached = CsvDataSource(cache_path).load()
        if start_date and pd.Timestamp(start_date) < cached["date"].min():
            raise ValueError("cache does not cover requested start_date; use --refresh-cache")
        if end_date and pd.Timestamp(end_date) > cached["date"].max():
            raise ValueError("cache does not cover requested end_date; use --refresh-cache")
        if start_date:
            cached = cached[cached["date"] >= pd.Timestamp(start_date)]
        if end_date:
            cached = cached[cached["date"] <= pd.Timestamp(end_date)]
        return validate_candles(cached), True
    frame = source.load(start_date=start_date, end_date=end_date)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.assign(date=frame["date"].dt.strftime("%Y-%m-%d")).to_csv(
            cache_path, index=False, compression="gzip"
        )
    return frame, False
