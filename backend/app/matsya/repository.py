from __future__ import annotations

import json
from typing import Any


JsonDict = dict[str, Any]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def upsert_provider(conn: Any, provider_code: str, provider_name: str) -> None:
    conn.execute(
        """
        INSERT INTO matsya.providers (provider_code, provider_name)
        VALUES (%s, %s)
        ON CONFLICT (provider_code) DO UPDATE
        SET provider_name = EXCLUDED.provider_name,
            updated_at = now()
        """,
        (provider_code, provider_name),
    )


def start_import_run(
    conn: Any,
    *,
    provider_code: str,
    import_type: str,
    source_name: str = "",
    source_url: str = "",
    metadata: JsonDict | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO matsya.raw_import_runs (
            provider_code, import_type, source_name, source_url, status, metadata
        )
        VALUES (%s, %s, %s, %s, 'running', %s::jsonb)
        RETURNING id
        """,
        (provider_code, import_type, source_name, source_url, _json(metadata)),
    ).fetchone()
    return int(row[0])


def finish_import_run(conn: Any, run_id: int, *, status: str, counts: dict[str, int] | None = None) -> None:
    resolved = counts or {}
    conn.execute(
        """
        UPDATE matsya.raw_import_runs
        SET status = %s,
            total_rows_seen = %s,
            inserted_rows = %s,
            updated_rows = %s,
            unchanged_rows = %s,
            skipped_rows = %s,
            completed_at = now()
        WHERE id = %s
        """,
        (
            status,
            resolved.get("total_rows_seen", 0),
            resolved.get("inserted_rows", 0),
            resolved.get("updated_rows", 0),
            resolved.get("unchanged_rows", 0),
            resolved.get("skipped_rows", 0),
            run_id,
        ),
    )


def record_import_error(
    conn: Any,
    *,
    provider_code: str,
    error_type: str,
    error_message: str,
    run_id: int | None = None,
    source_ref: str = "",
    raw_payload: JsonDict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO matsya.raw_import_errors (
            run_id, provider_code, source_ref, error_type, error_message, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (run_id, provider_code, source_ref, error_type, error_message, _json(raw_payload)),
    )


def insert_raw_dhan_response(
    conn: Any,
    *,
    endpoint_name: str,
    request_hash: str,
    request_payload: JsonDict,
    response_hash: str = "",
    response_json: JsonDict | None = None,
    response_text_ref: str = "",
    status_code: int | None = None,
    error_message: str = "",
    run_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO matsya.raw_dhan_responses (
            run_id, endpoint_name, request_hash, request_payload, response_hash,
            response_json, response_text_ref, status_code, error_message
        )
        VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)
        """,
        (
            run_id,
            endpoint_name,
            request_hash,
            _json(request_payload),
            response_hash,
            _json(response_json),
            response_text_ref,
            status_code,
            error_message,
        ),
    )


def upsert_instrument(conn: Any, row: JsonDict, *, run_id: int | None = None) -> None:
    conn.execute(
        """
        INSERT INTO matsya.instruments (
            provider_code, natural_key, row_hash, exchange_id, segment, security_id, isin,
            instrument, underlying_security_id, underlying_symbol, symbol_name, display_name,
            instrument_type, series, lot_size, expiry_date, strike_price, option_type,
            tick_size, raw_row, active, last_import_run_id
        )
        VALUES (
            'dhan', %(natural_key)s, %(row_hash)s, %(exchange_id)s, %(segment)s,
            %(security_id)s, %(isin)s, %(instrument)s, %(underlying_security_id)s,
            %(underlying_symbol)s, %(symbol_name)s, %(display_name)s, %(instrument_type)s,
            %(series)s, %(lot_size)s, %(expiry_date)s, %(strike_price)s, %(option_type)s,
            %(tick_size)s, %(raw_row)s::jsonb, true, %(run_id)s
        )
        ON CONFLICT (provider_code, natural_key) DO UPDATE
        SET row_hash = EXCLUDED.row_hash,
            exchange_id = EXCLUDED.exchange_id,
            segment = EXCLUDED.segment,
            security_id = EXCLUDED.security_id,
            isin = EXCLUDED.isin,
            instrument = EXCLUDED.instrument,
            underlying_security_id = EXCLUDED.underlying_security_id,
            underlying_symbol = EXCLUDED.underlying_symbol,
            symbol_name = EXCLUDED.symbol_name,
            display_name = EXCLUDED.display_name,
            instrument_type = EXCLUDED.instrument_type,
            series = EXCLUDED.series,
            lot_size = EXCLUDED.lot_size,
            expiry_date = EXCLUDED.expiry_date,
            strike_price = EXCLUDED.strike_price,
            option_type = EXCLUDED.option_type,
            tick_size = EXCLUDED.tick_size,
            raw_row = EXCLUDED.raw_row,
            active = true,
            last_seen_at = now(),
            updated_at = now(),
            last_import_run_id = EXCLUDED.last_import_run_id
        """,
        {**row, "raw_row": _json(row.get("raw_row")), "run_id": run_id},
    )


def upsert_universe_member(conn: Any, row: JsonDict, *, run_id: int | None = None) -> None:
    conn.execute(
        """
        INSERT INTO matsya.market_universe_members (
            provider_code, universe_name, natural_key, row_hash, company_name,
            industry, symbol, series, isin, raw_row, active, last_import_run_id
        )
        VALUES (
            'nse', %(universe_name)s, %(natural_key)s, %(row_hash)s, %(company_name)s,
            %(industry)s, %(symbol)s, %(series)s, %(isin)s, %(raw_row)s::jsonb, true, %(run_id)s
        )
        ON CONFLICT (universe_name, natural_key) DO UPDATE
        SET row_hash = EXCLUDED.row_hash,
            company_name = EXCLUDED.company_name,
            industry = EXCLUDED.industry,
            symbol = EXCLUDED.symbol,
            series = EXCLUDED.series,
            isin = EXCLUDED.isin,
            raw_row = EXCLUDED.raw_row,
            active = true,
            last_seen_at = now(),
            updated_at = now(),
            last_import_run_id = EXCLUDED.last_import_run_id
        """,
        {**row, "raw_row": _json(row.get("raw_row")), "run_id": run_id},
    )


def upsert_ohlcv_daily(conn: Any, row: JsonDict, *, run_id: int | None = None) -> None:
    conn.execute(
        """
        INSERT INTO matsya.ohlcv_daily (
            provider_code, security_id, exchange_segment, instrument, trading_date,
            source_timestamp, open_price, high_price, low_price, close_price,
            volume, open_interest, raw_candle, last_import_run_id
        )
        VALUES (
            'dhan', %(security_id)s, %(exchange_segment)s, %(instrument)s, %(trading_date)s,
            %(source_timestamp)s, %(open_price)s, %(high_price)s, %(low_price)s,
            %(close_price)s, %(volume)s, %(open_interest)s, %(raw_candle)s::jsonb, %(run_id)s
        )
        ON CONFLICT (provider_code, security_id, trading_date) DO UPDATE
        SET exchange_segment = EXCLUDED.exchange_segment,
            instrument = EXCLUDED.instrument,
            source_timestamp = EXCLUDED.source_timestamp,
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            volume = EXCLUDED.volume,
            open_interest = EXCLUDED.open_interest,
            raw_candle = EXCLUDED.raw_candle,
            updated_at = now(),
            last_import_run_id = EXCLUDED.last_import_run_id
        """,
        {**row, "raw_candle": _json(row.get("raw_candle")), "run_id": run_id},
    )
