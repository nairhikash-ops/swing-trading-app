from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest

from app.matsya.ohlcv_service import (
    HistoricalWindow,
    MatsyaOHLCVService,
    dhan_exclusive_to_date,
    latest_returned_candle_date,
    parse_historical_payload,
    reusable_current_window_run,
    returned_candles_are_trailing_stale,
)
from app.timezone import IST


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
    assert "mark_item_waiting_for_latest_candle" in service
    assert "waiting_for_dhan_latest_candle" in service
    assert "dhan_exclusive_to_date" in service
    assert "expected_latest_candle_date" in service
    assert "FRESH" in service
    assert "STALE_OHLCV_DATA" in service
    assert "NO_OHLCV_DATA" in service
    assert "WAITING_FOR_DHAN_DATA" in service
    assert "NON_TRADING_DAY_USING_PREVIOUS_TRADING_DAY" in service

    gate_body = service.split("def prediction_freshness_status", 1)[1].split("async def _run_fetch", 1)[0]
    assert "START_COVERAGE_GRACE_DAYS" not in gate_body
    assert "END_FRESHNESS_GRACE_DAYS" not in gate_body


def test_latest_stored_lookup_avoids_untyped_optional_null_sql() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")

    lookup_body = service.split("def latest_stored_candle_date_for_symbol", 1)[1].split("def _touch_run", 1)[0]
    assert "%s IS NULL OR" not in lookup_body
    assert "params.append(instrument)" in lookup_body


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


def test_trailing_stale_detection_uses_latest_returned_candle_date() -> None:
    candles = [
        {"trading_date": "2026-06-18"},
        {"trading_date": "2026-06-19"},
    ]

    assert latest_returned_candle_date(candles) == date(2026, 6, 19)
    assert returned_candles_are_trailing_stale(candles, date(2026, 6, 22)) is True
    assert returned_candles_are_trailing_stale(candles, date(2026, 6, 19)) is False
    assert returned_candles_are_trailing_stale([], date(2026, 6, 22)) is False


def test_dhan_historical_to_date_is_exclusive() -> None:
    assert dhan_exclusive_to_date(date(2026, 6, 23)) == date(2026, 6, 24)


def test_dhan_historical_request_uses_exclusive_to_date_helper() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")
    fetch_body = service.split("async def _run_fetch", 1)[1].split("def _access_token", 1)[0]

    assert "dhan_to_date_text = dhan_exclusive_to_date(request_to).isoformat()" in fetch_body
    assert "to_date=dhan_to_date_text" in fetch_body
    assert "to_date=request_to_text" not in fetch_body


def test_completed_stale_run_is_not_reusable_but_fresh_run_is() -> None:
    window = HistoricalWindow(from_date=date(2021, 6, 24), to_date_exclusive=date(2026, 6, 23))
    base_run = {
        "status": "completed",
        "failed_count": 0,
        "lookback_calendar_days": 1825,
        "from_date": "2021-06-24",
        "to_date_exclusive": "2026-06-23",
        "next_retry_after": None,
    }

    stale_run = {**base_run, "latest_stored_candle_date": "2026-06-19"}
    fresh_run = {**base_run, "latest_stored_candle_date": "2026-06-22"}
    retry_wait_run = {**fresh_run, "next_retry_after": datetime(2026, 6, 23, tzinfo=IST)}

    assert reusable_current_window_run(stale_run, 1825, window) is False
    assert reusable_current_window_run(retry_wait_run, 1825, window) is False
    assert reusable_current_window_run(fresh_run, 1825, window) is True


def test_prediction_freshness_waiting_and_stale_states_are_not_fresh() -> None:
    class Settings:
        market_code = "NSE"
        historical_finalized_after_hour_ist = 18

    class Store:
        def trading_holidays(self, market_code: str) -> set[date]:
            return set()

    service = MatsyaOHLCVService.__new__(MatsyaOHLCVService)
    service.settings = Settings()
    service.store = Store()

    service.latest_stored_candle_date_for_symbol = lambda **_: date(2026, 6, 23)  # type: ignore[method-assign]
    waiting = service.prediction_freshness_status(
        symbol="RELIANCE",
        instrument="EQUITY",
        now_ist=datetime(2026, 6, 24, 18, 0, tzinfo=IST),
    )

    service.latest_stored_candle_date_for_symbol = lambda **_: date(2026, 6, 22)  # type: ignore[method-assign]
    stale = service.prediction_freshness_status(
        symbol="RELIANCE",
        instrument="EQUITY",
        now_ist=datetime(2026, 6, 24, 18, 0, tzinfo=IST),
    )

    assert waiting["fresh"] is False
    assert waiting["state"] == "WAITING_FOR_DHAN_DATA"
    assert stale["fresh"] is False
    assert stale["state"] == "STALE_OHLCV_DATA"
