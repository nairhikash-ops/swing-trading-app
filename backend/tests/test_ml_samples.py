import inspect
import json
import pytest
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.historical_data import HistoricalDataStore
from app.instrument_master import InstrumentMasterStore
from app.main import app, get_ml_sample_service_dep
import app.ml_samples as ml_samples_module
from app.ml_samples import (
    AMBIGUOUS_EXCLUDE_REASON,
    INSUFFICIENT_FUTURE_EXCLUDE_REASON,
    MLSampleService,
    MLSampleStore,
)
from app.store import TokenStore


def make_service(
    tmp_path,
    symbol: str = "RELIANCE",
    fetch_item_status: str = "done",
    seed_quality: bool = True,
) -> tuple[TokenStore, MLSampleStore, MLSampleService, int]:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    instrument_store = InstrumentMasterStore(token_store)
    HistoricalDataStore(token_store)
    sample_store = MLSampleStore(token_store)
    run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "500325",
                "ISIN": "INE002A01018",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": symbol,
                "SYMBOL_NAME": f"{symbol} LTD",
                "DISPLAY_NAME": symbol.title(),
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    instrument_id = int(sample_store.resolve_symbol(symbol)["id"])
    if seed_quality:
        seed_quality_run(token_store, instrument_id, symbol=symbol, fetch_item_status=fetch_item_status)
    return token_store, sample_store, MLSampleService(settings=settings, store=sample_store), instrument_id


def seed_candles(token_store: TokenStore, instrument_id: int, candles: list[dict]) -> None:
    timestamp = "2026-01-01T00:00:00+00:00"
    with token_store._connect() as conn:
        for candle in candles:
            conn.execute(
                """
                INSERT INTO daily_candles (
                    instrument_id, security_id, exchange_segment, instrument, trading_date,
                    source_timestamp, open, high, low, close, volume, open_interest,
                    source, raw_json, fetched_at, updated_at
                )
                VALUES (?, '500325', 'NSE_EQ', 'EQUITY', ?, 1704067200, ?, ?, ?, ?, ?, NULL,
                        'test', ?, ?, ?)
                ON CONFLICT(instrument_id, trading_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    instrument_id,
                    candle["trading_date"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                    candle["volume"],
                    json.dumps(candle, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )


def seed_quality_run(token_store: TokenStore, instrument_id: int, symbol: str, fetch_item_status: str) -> int:
    timestamp = "2026-01-01T00:00:00+00:00"
    with token_store._connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO historical_fetch_runs (
                universe_name, lookback_calendar_days, from_date, to_date_exclusive,
                status, total_symbols, mapped_symbols, skipped_symbols, error,
                started_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("NIFTY_500", 80, "2024-01-01", "2024-03-21", "completed", 1, 1, 0, "", timestamp, timestamp, timestamp),
        )
        run_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO historical_fetch_items (
                run_id, index_constituent_id, instrument_id, company_name, industry,
                symbol, isin, security_id, status, attempts, candles_received, error,
                started_at, finished_at, updated_at,
                request_from_date, request_to_date, archive_status, source_floor_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, 1, instrument_id, f"{symbol} LTD", "TEST_INDUSTRY",
                symbol, "TEST_ISIN", "500325", fetch_item_status, 1, 80, "",
                timestamp, timestamp, timestamp,
                "2024-01-01", "2024-03-20", "older_history_backfill", "dhan_5_year_limit"
            ),
        )

        conn.execute(
            """
            INSERT INTO historical_instrument_archive (
                instrument_id, security_id, symbol, source_provider, interval,
                first_stored_candle_date, latest_stored_candle_date,
                source_floor_reached, source_floor_date, source_floor_reason,
                complete_available_history, last_successful_fetch_at,
                last_no_new_data_at, next_retry_after, last_error,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instrument_id, "500325", symbol, "dhan", "daily",
                "2024-01-01", "2024-03-20",
                1, "2024-01-01", "dhan_5_year_limit",
                1, timestamp,
                None, None, "",
                timestamp, timestamp
            ),
        )
        return run_id


def make_80_candles(outcome: str, sample_candle_crosses_barriers: bool = False) -> list[dict]:
    start = date(2024, 1, 1)
    candles = []
    for index in range(80):
        trading_date = (start + timedelta(days=index)).isoformat()
        candle = {
            "trading_date": trading_date,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0 + index,
        }
        candles.append(candle)

    if sample_candle_crosses_barriers:
        candles[59]["high"] = 110.0
        candles[59]["low"] = 95.0

    if outcome == "WIN":
        candles[60]["high"] = 107.5
        candles[60]["low"] = 99.0
    elif outcome == "LOSS":
        candles[60]["high"] = 101.0
        candles[60]["low"] = 96.5
    elif outcome == "AMBIGUOUS":
        candles[60]["high"] = 107.5
        candles[60]["low"] = 96.5
    elif outcome == "TIMEOUT":
        for index in range(60, 80):
            candles[index]["high"] = 103.0
            candles[index]["low"] = 98.0
    return candles


def sample_date() -> str:
    return (date(2024, 1, 1) + timedelta(days=59)).isoformat()


def test_generate_one_symbol_win_label(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    summary = service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert summary["samples_created"] == 21
    assert sample["outcome"] == "WIN"
    assert sample["trainable"] is True
    assert sample["barrier_hit_type"] == "target"
    assert sample["days_to_outcome"] == 1
    assert sample["entry_close"] == 100.0
    assert sample["target_price"] == 107.0
    assert sample["stop_price"] == 97.0


def test_generate_one_symbol_loss_label(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("LOSS"))

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert sample["outcome"] == "LOSS"
    assert sample["trainable"] is True
    assert sample["barrier_hit_type"] == "stop"
    assert sample["days_to_outcome"] == 1


def test_generate_one_symbol_timeout_label(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("TIMEOUT"))

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert sample["outcome"] == "TIMEOUT"
    assert sample["trainable"] is True
    assert sample["barrier_hit_date"] is None
    assert sample["days_to_outcome"] == 20


def test_generate_one_symbol_ambiguous_label_is_excluded(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("AMBIGUOUS"))

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert sample["outcome"] == "AMBIGUOUS"
    assert sample["trainable"] is False
    assert sample["exclude_reason"] == AMBIGUOUS_EXCLUDE_REASON
    assert sample["barrier_hit_type"] == "both"


def test_future_scan_starts_after_sample_date(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("TIMEOUT", sample_candle_crosses_barriers=True))

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert sample["outcome"] == "TIMEOUT"
    assert sample["sample_date"] == sample_date()
    assert sample["future_window_start"] == (date(2024, 1, 1) + timedelta(days=60)).isoformat()


def test_requires_sixty_input_candles(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN")[:59])

    summary = service.generate_one("RELIANCE")

    assert summary["candles_available"] == 59
    assert summary["samples_created"] == 0
    assert summary["first_sample_date"] is None


def test_feature_json_has_normalized_sixty_row_window(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())
    feature = sample["feature"]

    assert feature["symbol"] == "RELIANCE"
    assert feature["sample_date"] == sample_date()
    assert feature["entry_close"] == 100.0
    assert feature["input_window_sessions"] == 60
    assert len(feature["candles"]) == 60
    assert set(feature["candles"][0]) == {
        "trading_date",
        "open_rel",
        "high_rel",
        "low_rel",
        "close_rel",
        "volume_rel",
    }
    assert feature["candles"][-1]["close_rel"] == 0.0


def test_insufficient_future_data_is_stored_but_not_trainable(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN")[:70])

    service.generate_one("RELIANCE")
    sample = sample_store.sample_for_date(instrument_id, sample_date())

    assert sample["outcome"] == "INSUFFICIENT_FUTURE_DATA"
    assert sample["trainable"] is False
    assert sample["exclude_reason"] == INSUFFICIENT_FUTURE_EXCLUDE_REASON


def test_generate_one_symbol_is_idempotent(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    first = service.generate_one("RELIANCE")
    second = service.generate_one("RELIANCE")

    assert first["samples_created"] == 21
    assert first["samples_updated"] == 0
    assert second["samples_created"] == 0
    assert second["samples_updated"] == 21
    assert sample_store.sample_count_for_instrument(instrument_id) == 21


def test_generate_one_rejects_missing_quality_report(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path, seed_quality=False)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    with pytest.raises(ValueError) as exc_info:
        service.generate_one("RELIANCE")

    assert "historical_run_id is missing" in str(exc_info.value)
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_one_rejects_warning_quality_symbol_before_writing_samples(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    candles = make_80_candles("WIN")
    candles[10]["volume"] = 0.0
    seed_candles(token_store, instrument_id, candles)

    with pytest.raises(ValueError) as exc_info:
        service.generate_one("RELIANCE")

    assert "failed quality gate" in str(exc_info.value)
    assert "ZERO_VOLUME" in str(exc_info.value)
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_one_rejects_blocked_quality_symbol_before_writing_samples(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path, fetch_item_status="failed")
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    with pytest.raises(ValueError) as exc_info:
        service.generate_one("RELIANCE")

    assert "failed quality gate" in str(exc_info.value)
    assert "FETCH_FAILED" in str(exc_info.value)
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_one_endpoint_returns_summary(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-one?symbol=RELIANCE")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["samples_created"] == 21
    assert data["outcome_counts"]["WIN"] == 1


def test_ml_sample_generator_does_not_import_or_call_dhan():
    source = inspect.getsource(ml_samples_module)

    assert "DhanClient" not in source
    assert "historical_daily" not in source


def test_generate_one_dry_run_writes_zero_samples(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    summary = service.generate_one("RELIANCE", dry_run=True)

    assert summary["samples_created"] == 21
    assert summary["samples_updated"] == 0
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_one_dry_run_reports_would_update_accurately(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    service.generate_one("RELIANCE", dry_run=False)
    assert sample_store.sample_count_for_instrument(instrument_id) == 21

    summary = service.generate_one("RELIANCE", dry_run=True)
    assert summary["samples_created"] == 0
    assert summary["samples_updated"] == 21
    assert sample_store.sample_count_for_instrument(instrument_id) == 21


def test_generate_batch_dry_run_true(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    result = service.generate_batch(["RELIANCE"], dry_run=True)
    assert result["dry_run"] is True
    assert result["symbols_processed"] == 1
    assert result["total_samples_created"] == 21
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_batch_dry_run_false(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    result = service.generate_batch(["RELIANCE"], dry_run=False)
    assert result["dry_run"] is False
    assert result["symbols_processed"] == 1
    assert result["total_samples_created"] == 21
    assert sample_store.sample_count_for_instrument(instrument_id) == 21


def test_generate_batch_captures_blocked_symbols_in_errors(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path, fetch_item_status="failed")
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))

    result = service.generate_batch(["RELIANCE"], dry_run=False)
    assert result["symbols_processed"] == 0
    assert result["symbols_failed"] == 1
    assert len(result["errors"]) == 1
    assert "RELIANCE" in result["errors"][0]["symbol"]
    assert sample_store.sample_count_for_instrument(instrument_id) == 0


def test_generate_batch_rejects_empty_list(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    with pytest.raises(ValueError) as exc:
        service.generate_batch([])
    assert "No symbols provided" in str(exc.value)


def test_generate_batch_rejects_more_than_five_symbols(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    with pytest.raises(ValueError) as exc:
        service.generate_batch(["S1", "S2", "S3", "S4", "S5", "S6"])
    assert "Maximum of 5" in str(exc.value)


def test_generate_batch_rejects_duplicates(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    with pytest.raises(ValueError) as exc:
        service.generate_batch(["RELIANCE", "reliance"])
    assert "Duplicate symbol" in str(exc.value)


def test_generate_batch_endpoint_returns_response(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    seed_candles(token_store, instrument_id, make_80_candles("WIN"))
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-batch", json={"symbols": ["RELIANCE"], "dry_run": True})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbols_requested"] == 1
    assert data["total_samples_created"] == 21
    assert data["dry_run"] is True


def test_generate_batch_rejects_blank_symbols(tmp_path):
    token_store, sample_store, service, instrument_id = make_service(tmp_path)
    with pytest.raises(ValueError) as exc:
        service.generate_batch(["RELIANCE", "   ", "TCS"])
    assert "Blank or whitespace-only" in str(exc.value)


def test_generate_batch_endpoint_validates_max_5(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-batch", json={"symbols": ["A", "B", "C", "D", "E", "F"], "dry_run": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "Maximum of 5" in response.json()["detail"]


def test_generate_batch_endpoint_rejects_empty_list(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-batch", json={"symbols": [], "dry_run": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "No symbols provided" in response.json()["detail"]


def test_generate_batch_endpoint_rejects_duplicate_symbols(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-batch", json={"symbols": ["TCS", "tcs"], "dry_run": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "Duplicate symbol" in response.json()["detail"]


def test_generate_batch_endpoint_rejects_blank_symbols(tmp_path):
    token_store, _sample_store, service, instrument_id = make_service(tmp_path)
    app.dependency_overrides[get_ml_sample_service_dep] = lambda: service
    try:
        client = TestClient(app)
        response = client.post("/api/ml/samples/generate-batch", json={"symbols": ["TCS", "  "], "dry_run": True})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "Blank or whitespace-only" in response.json()["detail"]

