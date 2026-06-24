from __future__ import annotations

from pathlib import Path

from app.matsya.ingest import (
    candles_from_dhan_payload,
    canonical_json,
    instrument_record,
    sha256_payload,
    token_hash,
    universe_record,
)
from app.matsya.settings import MatsyaSettings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCHEMA_SQL = BACKEND_ROOT / "app" / "matsya" / "schema.sql"
COMPOSE_YML = REPO_ROOT / "deploy" / "matsya-db" / "docker-compose.yml"


def test_matsya_schema_is_additive_and_idempotent() -> None:
    schema = SCHEMA_SQL.read_text(encoding="utf-8").lower()

    assert "create schema if not exists matsya" in schema
    assert "create table if not exists matsya.raw_import_runs" in schema
    assert "create table if not exists matsya.raw_import_errors" in schema
    assert "create table if not exists matsya.raw_dhan_responses" in schema
    assert "create table if not exists matsya.dhan_profile_snapshots" in schema
    assert "create table if not exists matsya.dhan_token_state" in schema
    assert "create table if not exists matsya.dhan_token_renewal_runs" in schema
    assert "create table if not exists matsya.instruments" in schema
    assert "create table if not exists matsya.market_universe_members" in schema
    assert "create table if not exists matsya.ohlcv_daily" in schema
    assert "jsonb" in schema
    assert "drop table" not in schema
    assert "drop schema" not in schema


def test_ohlcv_daily_uses_provider_security_date_uniqueness() -> None:
    schema = SCHEMA_SQL.read_text(encoding="utf-8").lower()

    assert "unique (provider_code, security_id, trading_date)" in schema
    assert "on conflict (provider_code, security_id, trading_date)" in (
        BACKEND_ROOT / "app" / "matsya" / "repository.py"
    ).read_text(encoding="utf-8").lower()


def test_matsya_compose_is_isolated_and_not_public() -> None:
    compose = COMPOSE_YML.read_text(encoding="utf-8")

    assert "postgres:16-alpine" in compose
    assert "latest" not in compose
    assert "127.0.0.1:5432:5432" in compose
    assert "matsya-postgres-data" in compose
    assert "frontend" not in compose
    assert "backend" not in compose


def test_settings_masks_database_password() -> None:
    settings = MatsyaSettings(database_url="postgresql://matsya_user:secret-value@127.0.0.1:5432/matsya")

    safe_url = settings.safe_database_url()

    assert "secret-value" not in safe_url
    assert safe_url == "postgresql://matsya_user:***@127.0.0.1:5432/matsya"


def test_ingest_helpers_preserve_raw_payload_and_hash_tokens() -> None:
    raw_instrument = {
        "EXCH_ID": "NSE",
        "SEGMENT": "E",
        "SECURITY_ID": "1333",
        "INSTRUMENT": "EQUITY",
        "ISIN": "INE002A01018",
        "SYMBOL_NAME": "RELIANCE",
        "DISPLAY_NAME": "RELIANCE",
        "LOT_SIZE": "1",
        "STRIKE_PRICE": "",
        "TICK_SIZE": "0.05",
    }
    record = instrument_record(raw_instrument)

    assert record["security_id"] == "1333"
    assert record["lot_size"] == 1.0
    assert record["strike_price"] is None
    assert record["raw_row"] == raw_instrument
    assert token_hash("plain-token") != "plain-token"


def test_instrument_record_accepts_current_dhan_sem_columns() -> None:
    raw_instrument = {
        "SEM_EXM_EXCH_ID": "NSE",
        "SEM_SEGMENT": "E",
        "SEM_SMST_SECURITY_ID": "100",
        "SEM_INSTRUMENT_NAME": "EQUITY",
        "SEM_TRADING_SYMBOL": "ARE&M",
        "SEM_LOT_UNITS": "1.0",
        "SEM_CUSTOM_SYMBOL": "Amara Raja Energy & Mobility",
        "SEM_EXPIRY_DATE": "",
        "SEM_STRIKE_PRICE": "",
        "SEM_OPTION_TYPE": "",
        "SEM_TICK_SIZE": "5.0000",
        "SEM_EXPIRY_FLAG": "NA",
        "SEM_EXCH_INSTRUMENT_TYPE": "ES",
        "SEM_SERIES": "EQ",
        "SM_SYMBOL_NAME": "AMARA RAJA ENERGY MOB LTD",
    }

    record = instrument_record(raw_instrument)

    assert record["exchange_id"] == "NSE"
    assert record["segment"] == "E"
    assert record["security_id"] == "100"
    assert record["instrument"] == "EQUITY"
    assert record["symbol_name"] == "ARE&M"
    assert record["display_name"] == "AMARA RAJA ENERGY MOB LTD"
    assert record["instrument_type"] == "ES"
    assert record["series"] == "EQ"
    assert record["lot_size"] == 1.0
    assert record["isin"] == ""
    assert record["raw_row"] == raw_instrument


def test_universe_and_candle_helpers_are_deterministic() -> None:
    raw_universe = {
        "Company Name": "Reliance Industries Ltd.",
        "Industry": "Energy",
        "Symbol": "RELIANCE",
        "Series": "EQ",
        "ISIN Code": "INE002A01018",
    }
    normalized_raw_universe = {
        "COMPANY NAME": "Reliance Industries Ltd.",
        "INDUSTRY": "Energy",
        "SYMBOL": "RELIANCE",
        "SERIES": "EQ",
        "ISIN CODE": "INE002A01018",
    }
    universe = universe_record("NIFTY_500", normalized_raw_universe)
    payload = {
        "timestamp": [1767225600],
        "open": [100.0],
        "high": [110.0],
        "low": [99.5],
        "close": [108.5],
        "volume": [10000],
    }
    candles = candles_from_dhan_payload(payload, security_id="1333", exchange_segment="NSE_EQ", instrument="EQUITY")

    assert universe["symbol"] == raw_universe["Symbol"]
    assert universe["raw_row"] == normalized_raw_universe
    assert candles[0]["security_id"] == "1333"
    assert candles[0]["open_price"] == 100.0
    assert sha256_payload(payload) == sha256_payload(payload)
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
