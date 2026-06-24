from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.matsya.ohlcv_service import (
    HistoricalWindow,
    MatsyaOHLCVService,
    dhan_exclusive_to_date,
    historical_window,
    inclusive_request_to_date,
    incremental_request_from_date,
    instrument_matches_universe_member,
    latest_candle_retry_delay,
    latest_returned_candle_date,
    normalized_mapping_symbol,
    parse_historical_payload,
    recent_trading_days,
    reusable_current_window_run,
    returned_candles_are_trailing_stale,
)
from app.matsya.ohlcv_worker import next_daily_eod_run_at, should_run_daily_eod
from app.matsya.settings import MatsyaSettings
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
        "normalized_mapping_symbol",
        "instrument_matches_universe_member",
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
        "MATSYA_OHLCV_LOOP=true",
        "MATSYA_OHLCV_CHECK_INTERVAL_SECONDS=3600",
        "MATSYA_HISTORICAL_LOOKBACK_CALENDAR_DAYS=1825",
        "MATSYA_OHLCV_VALIDATION_TRADING_DAYS=60",
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


def test_matsya_ohlcv_worker_compose_is_restartable_but_not_public() -> None:
    compose = read("deploy/matsya-setup/docker-compose.yml")
    worker_section = compose.split("matsya-ohlcv-worker:", 1)[1].split("\n\nnetworks:", 1)[0]

    assert "restart: unless-stopped" in worker_section
    assert "ports:" not in worker_section
    assert 'command: ["python", "-m", "scripts.matsya_ohlcv_worker"]' in worker_section


def test_matsya_ohlcv_worker_loop_is_daily_eod_after_18_ist() -> None:
    before_eod = datetime(2026, 6, 24, 17, 59, tzinfo=IST)
    at_eod = datetime(2026, 6, 24, 18, 0, tzinfo=IST)
    after_eod = datetime(2026, 6, 24, 20, 30, tzinfo=IST)

    assert should_run_daily_eod(before_eod, 18, None) is False
    assert should_run_daily_eod(at_eod, 18, None) is True
    assert should_run_daily_eod(after_eod, 18, date(2026, 6, 24)) is False
    assert next_daily_eod_run_at(before_eod, 18, None) == datetime(2026, 6, 24, 18, 0, tzinfo=IST)
    assert next_daily_eod_run_at(after_eod, 18, date(2026, 6, 24)) == datetime(2026, 6, 25, 18, 0, tzinfo=IST)


def test_matsya_ohlcv_validation_contract_is_present_and_non_destructive() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")
    worker = read("backend/app/matsya/ohlcv_worker.py")
    status_script = read("backend/scripts/matsya_status.py")

    assert "def validation_report" in service
    assert "missing_recent_symbol_dates" in service
    assert "duplicate_count" in service
    assert "zero_candle_symbols" in service
    assert "stale_symbols" in service
    assert "bad_ohlc_count" in service
    assert "negative_volume_count" in service
    assert "Matsya OHLCV validation" in worker
    assert "matsya.ohlcv_validation:" in status_script
    assert "DROP TABLE" not in service.upper()
    assert "TRUNCATE" not in service.upper()
    assert "DELETE FROM matsya.ohlcv_daily" not in service


def test_recent_trading_days_returns_60_sessions_and_skips_weekends() -> None:
    days = recent_trading_days(date(2026, 6, 24), 60, set())

    assert len(days) == 60
    assert days[-1] == date(2026, 6, 24)
    assert all(day.weekday() < 5 for day in days)
    assert date(2026, 6, 21) not in days


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


def test_incremental_overlap_uses_trading_sessions() -> None:
    window = HistoricalWindow(from_date=date(2026, 6, 1), to_date_exclusive=date(2026, 6, 25))

    assert incremental_request_from_date(date(2026, 6, 24), window, 2, set()) == date(2026, 6, 22)


def test_incremental_overlap_zero_uses_latest_stored_date() -> None:
    window = HistoricalWindow(from_date=date(2026, 6, 1), to_date_exclusive=date(2026, 6, 25))

    assert incremental_request_from_date(date(2026, 6, 24), window, 0, set()) == date(2026, 6, 24)


def test_incremental_overlap_clamps_to_window_from_date() -> None:
    window = HistoricalWindow(from_date=date(2026, 6, 23), to_date_exclusive=date(2026, 6, 25))

    assert incremental_request_from_date(date(2026, 6, 24), window, 3, set()) == date(2026, 6, 23)


def test_fetch_plan_uses_overlap_without_changing_request_to_date() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")
    plan_body = service.split("def fetch_plan_for_instrument", 1)[1].split("def parse_historical_payload", 1)[0]

    assert "incremental_request_from_date(" in plan_body
    assert '"request_to_date": latest_expected.isoformat()' in plan_body


def test_latest_candle_retry_delay_clamps_and_defaults_to_three_hours() -> None:
    settings = MatsyaSettings(database_url="postgresql://example")

    assert settings.dhan_latest_candle_retry_hours == 3
    assert latest_candle_retry_delay(settings.dhan_latest_candle_retry_hours) == timedelta(hours=3)
    assert latest_candle_retry_delay(0) == timedelta(hours=1)


def test_inclusive_request_to_uses_item_date_when_present() -> None:
    assert inclusive_request_to_date("2026-06-23", "2026-06-24") == date(2026, 6, 23)


def test_inclusive_request_to_converts_run_exclusive_fallback() -> None:
    assert inclusive_request_to_date(None, "2026-06-24") == date(2026, 6, 23)


def test_dhan_historical_run_fallback_does_not_double_add_exclusive_to_date() -> None:
    request_to = inclusive_request_to_date(None, "2026-06-24")

    assert dhan_exclusive_to_date(request_to) == date(2026, 6, 24)


def test_historical_window_uses_eod_finalized_trading_day() -> None:
    settings = MatsyaSettings(database_url="postgresql://example", historical_lookback_calendar_days=5)

    before_eod = historical_window(settings, as_of=datetime(2026, 6, 24, 17, 59, tzinfo=IST), holidays=set())
    after_eod = historical_window(settings, as_of=datetime(2026, 6, 24, 18, 0, tzinfo=IST), holidays=set())

    assert before_eod.to_date_exclusive == date(2026, 6, 24)
    assert after_eod.to_date_exclusive == date(2026, 6, 25)
    assert after_eod.from_date == date(2026, 6, 20)


def test_dhan_historical_request_uses_exclusive_to_date_helper() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")
    fetch_body = service.split("async def _run_fetch", 1)[1].split("def _access_token", 1)[0]

    assert "inclusive_request_to_date(" in fetch_body
    assert "dhan_to_date_text = dhan_exclusive_to_date(request_to).isoformat()" in fetch_body
    assert "to_date=dhan_to_date_text" in fetch_body
    assert "to_date=request_to_text" not in fetch_body
    assert "timedelta(hours=12)" not in service


def test_nifty_mapping_prefers_isin_then_exact_symbol_fallback_only_for_equity() -> None:
    service = read("backend/app/matsya/ohlcv_service.py")

    assert "LEFT JOIN LATERAL" in service
    assert "BTRIM(i.isin) <> ''" in service
    assert "UPPER(BTRIM(i.isin)) = UPPER(BTRIM(m.isin))" in service
    assert "UPPER(BTRIM(i.symbol_name)) = UPPER(BTRIM(m.symbol))" in service
    assert "UPPER(BTRIM(i.underlying_symbol)) = UPPER(BTRIM(m.symbol))" in service
    assert "i.exchange_id = 'NSE'" in service
    assert "i.segment = 'E'" in service
    assert "i.instrument = 'EQUITY'" in service
    assert "LIMIT 1" in service
    assert "UPPER(BTRIM(i.display_name)) = UPPER(BTRIM(m.symbol))" not in service
    assert "No active Dhan NSE equity instrument matched this Nifty 500 ISIN or symbol." in service


def test_normalized_mapping_symbol_is_exact_and_preserves_special_characters() -> None:
    assert normalized_mapping_symbol(" bajaj-auto ") == "BAJAJ-AUTO"
    assert normalized_mapping_symbol("m&m") == "M&M"
    assert normalized_mapping_symbol("ARE&M") == "ARE&M"
    assert normalized_mapping_symbol("") == ""
    assert normalized_mapping_symbol(None) == ""


def test_instrument_mapping_rule_keeps_isin_primary_and_symbol_fallback_safe() -> None:
    base = {
        "provider_code": "dhan",
        "active": True,
        "exchange_id": "NSE",
        "segment": "E",
        "instrument": "EQUITY",
        "isin": "",
        "symbol_name": "BAJAJ-AUTO",
        "underlying_symbol": "BAJAJ-AUTO",
    }

    assert instrument_matches_universe_member(
        {**base, "isin": "INE000000001", "symbol_name": "WRONG"},
        member_symbol="BAJAJ-AUTO",
        member_isin="INE000000001",
    )
    assert not instrument_matches_universe_member(
        {**base, "isin": "INE000000002", "symbol_name": "BAJAJ-AUTO"},
        member_symbol="BAJAJ-AUTO",
        member_isin="INE000000001",
    )
    assert instrument_matches_universe_member(base, member_symbol="bajaj-auto", member_isin="INE000000001")
    assert instrument_matches_universe_member(
        {**base, "symbol_name": "M&M", "underlying_symbol": "M&M"},
        member_symbol="m&m",
        member_isin="INE000000003",
    )
    assert not instrument_matches_universe_member(
        {**base, "exchange_id": "BSE"},
        member_symbol="BAJAJ-AUTO",
        member_isin="INE000000001",
    )
    assert not instrument_matches_universe_member(
        {**base, "segment": "D", "instrument": "FUTSTK"},
        member_symbol="BAJAJ-AUTO",
        member_isin="INE000000001",
    )


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
