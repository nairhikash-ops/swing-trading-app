from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from app.index_universe import build_natural_key as universe_natural_key
from app.index_universe import build_row_hash as universe_row_hash
from app.index_universe import normalize_constituent
from app.instrument_master import build_natural_key as instrument_natural_key
from app.instrument_master import build_row_hash as instrument_row_hash
from app.instrument_master import normalize_row as normalize_instrument_master_row
from app.instrument_master import number_or_none


def canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_payload(value: Any) -> str:
    return sha256_text(canonical_json(value))


def token_hash(access_token: str) -> str:
    return sha256_text(access_token)


def instrument_record(raw_row: dict[str, str]) -> dict[str, Any]:
    normalized = normalize_instrument_master_row(raw_row)
    return {
        "natural_key": instrument_natural_key(normalized),
        "row_hash": instrument_row_hash(normalized),
        "exchange_id": normalized.get("EXCH_ID", ""),
        "segment": normalized.get("SEGMENT", ""),
        "security_id": normalized.get("SECURITY_ID", ""),
        "isin": normalized.get("ISIN", ""),
        "instrument": normalized.get("INSTRUMENT", ""),
        "underlying_security_id": normalized.get("UNDERLYING_SECURITY_ID", ""),
        "underlying_symbol": normalized.get("UNDERLYING_SYMBOL", ""),
        "symbol_name": normalized.get("SYMBOL_NAME", ""),
        "display_name": normalized.get("DISPLAY_NAME", ""),
        "instrument_type": normalized.get("INSTRUMENT_TYPE", ""),
        "series": normalized.get("SERIES", ""),
        "lot_size": number_or_none(normalized.get("LOT_SIZE", "")),
        "expiry_date": normalized.get("SM_EXPIRY_DATE", ""),
        "strike_price": number_or_none(normalized.get("STRIKE_PRICE", "")),
        "option_type": normalized.get("OPTION_TYPE", ""),
        "tick_size": number_or_none(normalized.get("TICK_SIZE", "")),
        "raw_row": raw_row,
    }


def universe_record(index_name: str, raw_row: dict[str, str]) -> dict[str, Any]:
    normalized = normalize_constituent(raw_row)
    return {
        "universe_name": index_name,
        "natural_key": universe_natural_key(index_name, normalized),
        "row_hash": universe_row_hash(raw_row),
        "company_name": normalized["company_name"],
        "industry": normalized["industry"],
        "symbol": normalized["symbol"],
        "series": normalized["series"],
        "isin": normalized["isin"],
        "raw_row": raw_row,
    }


def candles_from_dhan_payload(
    payload: dict[str, Any],
    *,
    security_id: str,
    exchange_segment: str,
    instrument: str,
) -> list[dict[str, Any]]:
    timestamps = payload.get("timestamp") or payload.get("timestamps") or []
    opens = payload.get("open") or []
    highs = payload.get("high") or []
    lows = payload.get("low") or []
    closes = payload.get("close") or []
    volumes = payload.get("volume") or []
    open_interest = payload.get("open_interest") or payload.get("openInterest") or []
    records: list[dict[str, Any]] = []
    for index, source_timestamp in enumerate(timestamps):
        candle_date = _date_from_timestamp(source_timestamp)
        raw_candle = {
            "timestamp": source_timestamp,
            "open": _value_at(opens, index),
            "high": _value_at(highs, index),
            "low": _value_at(lows, index),
            "close": _value_at(closes, index),
            "volume": _value_at(volumes, index),
            "open_interest": _value_at(open_interest, index),
        }
        records.append(
            {
                "security_id": security_id,
                "exchange_segment": exchange_segment,
                "instrument": instrument,
                "trading_date": candle_date,
                "source_timestamp": source_timestamp,
                "open_price": raw_candle["open"],
                "high_price": raw_candle["high"],
                "low_price": raw_candle["low"],
                "close_price": raw_candle["close"],
                "volume": raw_candle["volume"],
                "open_interest": raw_candle["open_interest"],
                "raw_candle": raw_candle,
            }
        )
    return records


def _value_at(values: Any, index: int) -> Any:
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _date_from_timestamp(source_timestamp: Any) -> date:
    if isinstance(source_timestamp, str) and len(source_timestamp) >= 10:
        return date.fromisoformat(source_timestamp[:10])
    return datetime.fromtimestamp(int(source_timestamp), tz=UTC).date()
