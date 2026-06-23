from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.matsya.ohlcv_service import parse_historical_payload


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_ohlcv_service_is_meaningful_and_not_blank() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")
    market_calendar = read("backend/app/matsya/market_calendar.py")

    assert len(service.strip().splitlines()) > 200
    assert len(market_calendar.strip().splitlines()) > 30
    assert "class MatsyaOHLCVStore:" in service
    assert "class MatsyaOHLCVService:" in service
    assert "def parse_historical_payload" in service
    assert "def expected_latest_candle_date" in market_calendar
    assert "DhanClient" in service


def test_ohlcv_worker_exists_and_is_meaningful() -> None:
    worker = read("backend/app/matsya/ohlcv_worker.py")

    assert len(worker.strip().splitlines()) > 40
    assert "class MatsyaOHLCVWorker:" in worker
    assert "await self.service.run_once()" in worker


def test_ohlcv_path_does_not_use_sqlite_or_legacy_token_store() -> None:
    source = "\n".join(
        [
            read("backend/app/matsya/ohlcv_service.py"),
            read("backend/app/matsya/ohlcv_worker.py"),
            read("backend/scripts/matsya_ohlcv_worker.py"),
        ]
    )

    assert "sqlite3" not in source
    assert "PRAGMA" not in source
    assert ("Token" + "Store") not in source


def test_ohlcv_path_does_not_use_raw_token_env_or_secret_logging() -> None:
    source = "\n".join(
        [
            read("backend/app/matsya/ohlcv_service.py"),
            read("backend/app/matsya/ohlcv_worker.py"),
            read("backend/scripts/matsya_ohlcv_worker.py"),
        ]
    )

    assert ("DHAN" + "_ACCESS_TOKEN") not in source
    assert "print(os.environ" not in source
    assert "cat .env" not in source
    assert not re.search(r"docker exec.*env", source)
    assert not re.search(r"access_token.*print", source)
    assert not re.search(r"logger\..*access_token", source)
    assert not re.search(r"database_url.*print", source)


def test_ohlcv_historical_helpers_and_statuses_exist() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")

    assert "START_COVERAGE_GRACE_DAYS = 10" in service
    assert "END_FRESHNESS_GRACE_DAYS = 3" in service

    for helper in (
        "historical_window",
        "dhan_earliest_supported_date",
        "clamp_window_to_dhan_floor",
        "reusable_current_window_run",
        "fetch_plan_for_instrument",
        "is_retryable_error",
        "is_no_data_error",
        "is_fatal_error",
        "readable_error",
    ):
        assert f"def {helper}" in service

    for status in (
        "queued",
        "fetching",
        "done",
        "failed",
        "skipped_unmapped",
        "skipped_up_to_date",
        "skipped_no_new_data",
        "skipped_retry_later",
        "initial_capture",
        "incremental_update",
        "older_history_backfill",
        "up_to_date",
        "waiting_for_next_session",
    ):
        assert status in service


def test_prediction_freshness_gate_is_separate_from_ingestion_grace() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")

    assert "def latest_stored_candle_date_for_symbol" in service
    assert "def prediction_freshness_status" in service
    assert "def is_prediction_data_fresh" in service
    assert "expected_latest_candle_date" in service
    assert "FRESH" in service
    assert "STALE_OHLCV_DATA" in service
    assert "NO_OHLCV_DATA" in service
    assert "WAITING_FOR_DHAN_DATA" in service
    assert "NON_TRADING_DAY_USING_PREVIOUS_TRADING_DAY" in service

    gate_body = service.split("def prediction_freshness_status", 1)[1].split("async def _run_fetch", 1)[0]
    assert "START_COVERAGE_GRACE_DAYS" not in gate_body
    assert "END_FRESHNESS_GRACE_DAYS" not in gate_body


def test_matsya_ohlcv_schema_and_compose_are_safe() -> None:
    schema = read("backend/app/matsya/schema.sql")
    compose = read("deploy/matsya-setup/docker-compose.yml")
    env_example = read("deploy/matsya-setup/.env.example")

    assert "CREATE TABLE IF NOT EXISTS matsya.ohlcv_fetch_runs" in schema
    assert "CREATE TABLE IF NOT EXISTS matsya.ohlcv_fetch_items" in schema
    assert "CREATE TABLE IF NOT EXISTS matsya.ohlcv_instrument_archive" in schema
    assert "CREATE TABLE IF NOT EXISTS matsya.ohlcv_daily" in schema
    assert "CREATE TABLE IF NOT EXISTS matsya.trading_holidays" in schema
    assert "DROP TABLE" not in schema.upper()
    assert "sqlite" not in schema.lower()
    assert "PRAGMA" not in schema
    assert "UNIQUE (provider_code, security_id, trading_date)" in schema

    assert "matsya-ohlcv-worker:" in compose
    worker_section = compose.split("matsya-ohlcv-worker:", 1)[1].split("\n\nnetworks:", 1)[0]
    assert "ports:" not in worker_section
    assert "env_file:\n      - .env" in worker_section
    assert "- matsya-db" in worker_section
    assert "postgres:" not in compose

    for key in (
        "MATSYA_OHLCV_WORKER_ENABLED=true",
        "MATSYA_OHLCV_LOOP=false",
        "MATSYA_OHLCV_CHECK_INTERVAL_SECONDS=3600",
        "MATSYA_HISTORICAL_LOOKBACK_CALENDAR_DAYS=1825",
        "MATSYA_DHAN_HISTORICAL_DAILY_SUPPORTED_YEARS=5",
        "MATSYA_DHAN_HISTORICAL_RPS=2",
        "MATSYA_DHAN_HISTORICAL_MAX_RETRIES=3",
        "MATSYA_DHAN_HISTORICAL_EXCHANGE_SEGMENT=NSE_EQ",
        "MATSYA_DHAN_HISTORICAL_INSTRUMENT=EQUITY",
        "MATSYA_OHLCV_UNIVERSE_NAME=NIFTY_500",
        "MATSYA_HISTORICAL_FINALIZED_AFTER_HOUR_IST=18",
        "MATSYA_MARKET_CODE=NSE",
    ):
        assert key in env_example


def test_old_root_compose_not_modified_for_matsya_ohlcv_worker() -> None:
    old_compose = read("docker-compose.yml")

    assert "matsya-ohlcv-worker" not in old_compose


def test_parse_historical_payload_converts_dhan_arrays() -> None:
    payload = {
        "timestamp": [1767225600, 1767312000000],
        "open": [100, 101],
        "high": [110, 111],
        "low": [99, 100],
        "close": [108, 109],
        "volume": [10000, 11000],
        "open_interest": [0, 1],
    }

    candles = parse_historical_payload(payload)

    assert candles[0]["trading_date"] == "2026-01-01"
    assert candles[0]["open"] == 100.0
    assert candles[1]["trading_date"] == "2026-01-02"
    assert candles[1]["open_interest"] == 1.0


def test_parse_historical_payload_rejects_mismatched_arrays() -> None:
    payload = {
        "timestamp": [1767225600],
        "open": [100],
        "high": [110, 111],
        "low": [99],
        "close": [108],
        "volume": [10000],
    }

    with pytest.raises(ValueError, match="mismatched lengths"):
        parse_historical_payload(payload)
