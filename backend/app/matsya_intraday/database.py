from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from .aggregation import aggregate
from .settings import IntradaySettings
from .validation import DayValidation


MIGRATIONS = Path(__file__).with_name("migrations")


def connect_intraday(settings: IntradaySettings) -> psycopg.Connection[Any]:
    conn = psycopg.connect(settings.database_url, autocommit=False)
    intraday_identity = conn.execute(
        "SELECT current_database(),coalesce(inet_server_addr()::text,''),inet_server_port()"
    ).fetchone()
    conn.rollback()
    with psycopg.connect(settings.daily_database_url, autocommit=False) as daily:
        daily.execute("SET TRANSACTION READ ONLY")
        daily_identity = daily.execute(
            "SELECT current_database(),coalesce(inet_server_addr()::text,''),inet_server_port()"
        ).fetchone()
        daily.rollback()
    if tuple(intraday_identity) == tuple(daily_identity):
        conn.close()
        raise ValueError("intraday and daily connections resolve to the same PostgreSQL database")
    return conn


def migrate(conn: Any) -> list[str]:
    applied: list[str] = []
    conn.execute("CREATE SCHEMA IF NOT EXISTS matsya_intraday")
    conn.execute("CREATE TABLE IF NOT EXISTS matsya_intraday.schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    known = {row[0] for row in conn.execute("SELECT version FROM matsya_intraday.schema_migrations").fetchall()}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in known:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO matsya_intraday.schema_migrations(version) VALUES (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied


def payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def store_day(
    conn: Any, *, run_id: int, symbol: str, security_id: str, validation: DayValidation,
    request_from: str, request_to: str, payload: dict[str, Any],
) -> int:
    digest = payload_hash(payload)
    row = conn.execute(
        """
        INSERT INTO matsya_intraday.symbol_days
          (run_id,symbol,security_id,trading_date,status,candle_count,missing_minutes,
           zero_volume_minutes,defects,request_from,request_to,response_sha256)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
        ON CONFLICT (provider_code,security_id,trading_date) DO UPDATE SET
          run_id=EXCLUDED.run_id,symbol=EXCLUDED.symbol,status=EXCLUDED.status,
          candle_count=EXCLUDED.candle_count,missing_minutes=EXCLUDED.missing_minutes,
          zero_volume_minutes=EXCLUDED.zero_volume_minutes,defects=EXCLUDED.defects,
          request_from=EXCLUDED.request_from,request_to=EXCLUDED.request_to,
          response_sha256=EXCLUDED.response_sha256,updated_at=now()
        RETURNING id
        """,
        (run_id,symbol,security_id,validation.trading_date,validation.status,len(validation.candles),
         len(validation.missing_minutes),validation.zero_volume_minutes,json.dumps(validation.defects),
         request_from,request_to,digest),
    ).fetchone()
    day_id = int(row[0])
    conn.execute("DELETE FROM matsya_intraday.minute_candles WHERE source_day_id=%s", (day_id,))
    conn.execute("DELETE FROM matsya_intraday.derived_candles WHERE source_day_id=%s", (day_id,))
    if validation.status in {"accepted", "warning"}:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO matsya_intraday.minute_candles
                  (security_id,symbol,candle_time,trading_date,open_price,high_price,low_price,close_price,volume,source_day_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (provider_code,security_id,candle_time) DO UPDATE SET
                  symbol=EXCLUDED.symbol,open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,
                  low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,volume=EXCLUDED.volume,
                  source_day_id=EXCLUDED.source_day_id
                """,
                [(security_id,symbol,c.timestamp,validation.trading_date,c.open,c.high,c.low,c.close,c.volume,day_id) for c in validation.candles],
            )
    if validation.status == "rejected":
        conn.execute(
            """INSERT INTO matsya_intraday.quarantine
                 (run_id,symbol,security_id,trading_date,reasons,response_sha256,raw_response)
               VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)
               ON CONFLICT (security_id,trading_date,response_sha256) DO NOTHING""",
            (run_id,symbol,security_id,validation.trading_date,json.dumps(validation.defects),digest,json.dumps(payload)),
        )
    conn.commit()
    return day_id


def load_stored_day(conn: Any, symbol: str, security_id: str, trading_date: str) -> tuple[int, DayValidation]:
    day = conn.execute(
        """SELECT id,status,defects,missing_minutes,zero_volume_minutes
           FROM matsya_intraday.symbol_days WHERE provider_code='dhan' AND security_id=%s AND trading_date=%s""",
        (security_id,trading_date),
    ).fetchone()
    if not day:
        raise ValueError(f"stored symbol-day not found: {symbol} {trading_date}")
    rows = conn.execute(
        """SELECT candle_time,open_price,high_price,low_price,close_price,volume
           FROM matsya_intraday.minute_candles WHERE source_day_id=%s ORDER BY candle_time""",
        (day[0],),
    ).fetchall()
    from .validation import MinuteCandle
    candles = tuple(MinuteCandle(*row) for row in rows)
    defects = tuple(day[2] if isinstance(day[2], list) else json.loads(day[2]))
    return int(day[0]), DayValidation(
        trading_date=date.fromisoformat(trading_date), status=day[1], candles=candles,
        defects=defects, missing_minutes=tuple("unknown" for _ in range(day[3])), zero_volume_minutes=day[4],
    )


def store_reconciliation(conn: Any, *, day_id: int, symbol: str, security_id: str, trading_date: str, result: Any) -> None:
    def encoded(value: Any) -> str | None:
        return json.dumps(value, sort_keys=True, default=str) if value is not None else None
    normal = result.normal_session
    official = result.official_daily or {}
    conn.execute(
        """INSERT INTO matsya_intraday.daily_reconciliation
          (symbol_day_id,symbol,security_id,trading_date,intraday_open,intraday_high,intraday_low,
           last_minute_close,normal_session_volume,official_daily_open,official_daily_high,
           official_daily_low,official_daily_close,official_daily_volume,absolute_differences,
           percentage_differences,open_high_low_match,close_match,volume_match,
           structural_acceptance_gate_passed,cross_source_status,explanation)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s)
          ON CONFLICT (symbol_day_id) DO UPDATE SET intraday_open=EXCLUDED.intraday_open,
           intraday_high=EXCLUDED.intraday_high,intraday_low=EXCLUDED.intraday_low,
           last_minute_close=EXCLUDED.last_minute_close,normal_session_volume=EXCLUDED.normal_session_volume,
           official_daily_open=EXCLUDED.official_daily_open,official_daily_high=EXCLUDED.official_daily_high,
           official_daily_low=EXCLUDED.official_daily_low,official_daily_close=EXCLUDED.official_daily_close,
           official_daily_volume=EXCLUDED.official_daily_volume,
           absolute_differences=EXCLUDED.absolute_differences,percentage_differences=EXCLUDED.percentage_differences,
           open_high_low_match=EXCLUDED.open_high_low_match,close_match=EXCLUDED.close_match,
           volume_match=EXCLUDED.volume_match,
           structural_acceptance_gate_passed=EXCLUDED.structural_acceptance_gate_passed,
           cross_source_status=EXCLUDED.cross_source_status,explanation=EXCLUDED.explanation,reconciled_at=now()""",
        (day_id,symbol,security_id,trading_date,normal["intraday_open"],normal["intraday_high"],
         normal["intraday_low"],normal["last_minute_close"],normal["normal_session_volume"],
         official.get("official_daily_open"),official.get("official_daily_high"),
         official.get("official_daily_low"),official.get("official_daily_close"),
         official.get("official_daily_volume"),encoded(result.absolute_differences),
         encoded(result.percentage_differences),result.open_high_low_match,result.close_match,
         result.volume_match,result.structural_acceptance_gate_passed,result.cross_source_status,
         result.explanation),
    )
    conn.commit()


def derive_day(conn: Any, *, day_id: int, symbol: str, security_id: str, validation: DayValidation) -> int:
    if validation.status != "accepted":
        raise ValueError("only accepted symbol-days may produce trusted derived candles")
    gate = conn.execute(
        "SELECT structural_acceptance_gate_passed FROM matsya_intraday.daily_reconciliation WHERE symbol_day_id=%s",
        (day_id,),
    ).fetchone()
    if not gate or not gate[0]:
        raise ValueError("structural acceptance and daily reconciliation must complete before trusted derivation")
    rows = [row for interval in (5,15,30,60,1440) for row in aggregate(validation.candles, interval)]
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO matsya_intraday.derived_candles
              (security_id,symbol,interval_minutes,bucket_time,trading_date,open_price,high_price,low_price,close_price,volume,source_minutes,source_day_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT (provider_code,security_id,interval_minutes,bucket_time) DO UPDATE SET
                open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,low_price=EXCLUDED.low_price,
                close_price=EXCLUDED.close_price,volume=EXCLUDED.volume,source_minutes=EXCLUDED.source_minutes,
                source_day_id=EXCLUDED.source_day_id,generated_at=now()""",
            [(security_id,symbol,row.interval_minutes,row.bucket_time,validation.trading_date,row.open,row.high,row.low,row.close,row.volume,row.source_minutes,day_id) for row in rows],
        )
    conn.commit()
    return len(rows)


def load_authoritative_daily(settings: IntradaySettings, security_id: str, trading_date: str) -> tuple[Any, ...] | None:
    """Read one authoritative daily candle with a transaction-level read-only guard."""
    with psycopg.connect(settings.daily_database_url, autocommit=False) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        row = conn.execute(
            """SELECT open_price,high_price,low_price,close_price,volume
               FROM matsya.ohlcv_daily WHERE provider_code='dhan' AND security_id=%s AND trading_date=%s""",
            (security_id,trading_date),
        ).fetchone()
        conn.rollback()
        return tuple(row) if row else None
