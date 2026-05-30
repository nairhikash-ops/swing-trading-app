from datetime import datetime, date

from app.config import Settings
from app.historical_data import (
    HistoricalDataStore,
    HistoricalWindow,
    historical_window,
    parse_historical_payload,
    reusable_current_window_run,
)
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore


def make_stores(tmp_path):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    return (
        settings,
        token_store,
        IndexUniverseStore(token_store),
        InstrumentMasterStore(token_store),
        HistoricalDataStore(token_store),
    )


def test_parse_historical_payload_returns_ist_trading_dates():
    payload = {
        "timestamp": [1714526100, 1714612500],
        "open": [100, 102],
        "high": [110, 112],
        "low": [99, 101],
        "close": [105, 108],
        "volume": [1000, 1200],
    }

    candles = parse_historical_payload(payload)

    assert candles[0]["trading_date"] == "2024-05-01"
    assert candles[0]["close"] == 105.0
    assert candles[1]["volume"] == 1200.0


def test_historical_window_always_ends_at_previous_calendar_day(tmp_path):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path, historical_lookback_calendar_days=365)
    morning = datetime.fromisoformat("2026-05-30T09:15:00+05:30")
    evening = datetime.fromisoformat("2026-05-30T20:15:00+05:30")

    morning_window = historical_window(settings, as_of=morning)
    evening_window = historical_window(settings, as_of=evening)

    assert morning_window.to_date_exclusive == date(2026, 5, 30)
    assert morning_window.from_date == date(2025, 5, 30)
    assert evening_window == morning_window


def test_reusable_current_window_run_accepts_completed_with_skipped_unmapped_only():
    window = HistoricalWindow(from_date=date(2025, 5, 18), to_date_exclusive=date(2026, 5, 18))
    run = {
        "lookback_calendar_days": 365,
        "from_date": "2025-05-18",
        "to_date_exclusive": "2026-05-18",
        "status": "completed_with_errors",
        "failed_count": 0,
        "skipped_count": 4,
    }

    assert reusable_current_window_run(run, 365, window) is True


def test_reusable_current_window_run_rejects_failed_counts_failed_status_or_different_windows():
    window = HistoricalWindow(from_date=date(2025, 5, 18), to_date_exclusive=date(2026, 5, 18))

    assert reusable_current_window_run(
        {
            "lookback_calendar_days": 365,
            "from_date": "2025-05-18",
            "to_date_exclusive": "2026-05-18",
            "status": "completed_with_errors",
            "failed_count": 1,
        },
        365,
        window,
    ) is False
    assert reusable_current_window_run(
        {
            "lookback_calendar_days": 365,
            "from_date": "2025-05-18",
            "to_date_exclusive": "2026-05-18",
            "status": "failed",
        },
        365,
        window,
    ) is False
    assert reusable_current_window_run(
        {
            "lookback_calendar_days": 365,
            "from_date": "2025-05-17",
            "to_date_exclusive": "2026-05-17",
            "status": "completed",
        },
        365,
        window,
    ) is False


def test_create_run_maps_nifty_500_by_isin_and_skips_unmapped(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "HDFC Bank Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "HDFCBANK",
                "SERIES": "EQ",
                "ISIN CODE": "INE040A01034",
            },
            {
                "COMPANY NAME": "Missing Ltd.",
                "INDUSTRY": "Unknown",
                "SYMBOL": "MISSING",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000000",
            },
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1333",
                "ISIN": "INE040A01034",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "HDFCBANK",
                "SYMBOL_NAME": "HDFC BANK LTD",
                "DISPLAY_NAME": "HDFC Bank",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )

    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 31)),
    )
    status = historical_store.status(run_id)
    items = historical_store.items(run_id)

    assert status["total_symbols"] == 2
    assert status["mapped_symbols"] == 1
    assert status["skipped_count"] == 1
    assert items[0]["security_id"] == "1333"
    assert items[1]["status"] == "skipped_unmapped"


def test_upsert_candles_is_idempotent(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "HDFC Bank Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "HDFCBANK",
                "SERIES": "EQ",
                "ISIN CODE": "INE040A01034",
            }
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1333",
                "ISIN": "INE040A01034",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "HDFCBANK",
                "SYMBOL_NAME": "HDFC BANK LTD",
                "DISPLAY_NAME": "HDFC Bank",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 31)),
    )
    item = historical_store.items(run_id, status="queued")[0]
    candle = {
        "timestamp": 1714526100,
        "trading_date": "2024-05-01",
        "open": 100.0,
        "high": 110.0,
        "low": 99.0,
        "close": 105.0,
        "volume": 1000.0,
        "open_interest": None,
    }

    historical_store.upsert_candles(item, [candle], "NSE_EQ", "EQUITY")
    historical_store.upsert_candles(item, [{**candle, "close": 106.0}], "NSE_EQ", "EQUITY")
    candles = historical_store.candles_for_symbol("HDFCBANK")

    assert len(candles) == 1
    assert candles[0]["close"] == 106.0


def test_prune_candles_before_deletes_only_old_rows(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "HDFC Bank Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "HDFCBANK",
                "SERIES": "EQ",
                "ISIN CODE": "INE040A01034",
            }
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1333",
                "ISIN": "INE040A01034",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "HDFCBANK",
                "SYMBOL_NAME": "HDFC BANK LTD",
                "DISPLAY_NAME": "HDFC Bank",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    run_id = historical_store.create_run(
        "NIFTY_500",
        365,
        HistoricalWindow(from_date=date(2023, 5, 1), to_date_exclusive=date(2024, 5, 1)),
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1682899200,
                "trading_date": "2023-05-01",
                "open": 90.0,
                "high": 95.0,
                "low": 88.0,
                "close": 93.0,
                "volume": 1000.0,
                "open_interest": None,
            },
            {
                "timestamp": 1714521600,
                "trading_date": "2024-05-01",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1200.0,
                "open_interest": None,
            },
        ],
        "NSE_EQ",
        "EQUITY",
    )

    deleted = historical_store.prune_candles_before(date(2024, 1, 1))
    candles = historical_store.candles_for_symbol("HDFCBANK")

    assert deleted == 1
    assert [candle["trading_date"] for candle in candles] == ["2024-05-01"]


def test_coverage_status_reports_up_to_date_without_creating_run(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "HDFC Bank Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "HDFCBANK",
                "SERIES": "EQ",
                "ISIN CODE": "INE040A01034",
            }
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1333",
                "ISIN": "INE040A01034",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "HDFCBANK",
                "SYMBOL_NAME": "HDFC BANK LTD",
                "DISPLAY_NAME": "HDFC Bank",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 31)),
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1714526100,
                "trading_date": "2024-05-01",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000.0,
                "open_interest": None,
            },
            {
                "timestamp": 1716422400,
                "trading_date": "2024-05-23",
                "open": 108.0,
                "high": 112.0,
                "low": 104.0,
                "close": 110.0,
                "volume": 1200.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    stale = historical_store.coverage_status(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 31)),
    )

    assert stale["status"] == "missing_data"

    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1716854400,
                "trading_date": "2024-05-28",
                "open": 109.0,
                "high": 113.0,
                "low": 105.0,
                "close": 111.0,
                "volume": 1300.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    status = historical_store.coverage_status(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 31)),
    )

    assert status["status"] == "up_to_date"
    assert status["id"] == 0
    assert status["done_count"] == 1
    assert status["stored_candle_count"] == 3


def test_coverage_status_requires_full_lookback_span(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "HDFC Bank Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "HDFCBANK",
                "SERIES": "EQ",
                "ISIN CODE": "INE040A01034",
            }
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1333",
                "ISIN": "INE040A01034",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "HDFCBANK",
                "SYMBOL_NAME": "HDFC BANK LTD",
                "DISPLAY_NAME": "HDFC Bank",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    run_id = historical_store.create_run(
        "NIFTY_500",
        120,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2024, 5, 1)),
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1714348800,
                "trading_date": "2024-04-29",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    partial = historical_store.coverage_status(
        "NIFTY_500",
        120,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2024, 5, 1)),
    )

    assert partial["status"] == "missing_data"

    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1704326400,
                "trading_date": "2024-01-04",
                "open": 90.0,
                "high": 95.0,
                "low": 88.0,
                "close": 93.0,
                "volume": 1000.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    complete = historical_store.coverage_status(
        "NIFTY_500",
        120,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2024, 5, 1)),
    )

    assert complete["status"] == "up_to_date"


def test_create_run_for_constituent_ids_only_queues_selected_symbols(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "First Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "FIRST",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000001",
            },
            {
                "COMPANY NAME": "Second Ltd.",
                "INDUSTRY": "Financial Services",
                "SYMBOL": "SECOND",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000002",
            },
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1",
                "ISIN": "INE000000001",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "FIRST",
                "SYMBOL_NAME": "FIRST LTD",
                "DISPLAY_NAME": "First",
                "SERIES": "EQ",
            },
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "2",
                "ISIN": "INE000000002",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "SECOND",
                "SYMBOL_NAME": "SECOND LTD",
                "DISPLAY_NAME": "Second",
                "SERIES": "EQ",
            },
        ],
        "NSE",
        "E",
    )
    selected = [item for item in universe_store.list_constituents("NIFTY_500") if item["symbol"] == "SECOND"][0]

    run_id = historical_store.create_run_for_constituent_ids(
        "NIFTY_500_UPWARD_MOVERS_GE_50",
        365,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2025, 1, 1)),
        [selected["id"]],
    )
    status = historical_store.status(run_id)
    items = historical_store.items(run_id)

    assert status["universe_name"] == "NIFTY_500_UPWARD_MOVERS_GE_50"
    assert status["total_symbols"] == 1
    assert status["mapped_symbols"] == 1
    assert [item["symbol"] for item in items] == ["SECOND"]


def test_constituent_coverage_requires_full_lookback_span(tmp_path):
    _, _, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "Mover Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "MOVER",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000001",
            }
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "1",
                "ISIN": "INE000000001",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "MOVER",
                "SYMBOL_NAME": "MOVER LTD",
                "DISPLAY_NAME": "Mover",
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )
    constituent_id = universe_store.list_constituents("NIFTY_500")[0]["id"]
    run_id = historical_store.create_run_for_constituent_ids(
        "NIFTY_500_UPWARD_MOVERS_GE_50",
        365,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2025, 1, 1)),
        [constituent_id],
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1735516800,
                "trading_date": "2024-12-30",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    partial = historical_store.coverage_status_for_constituent_ids(
        "NIFTY_500_UPWARD_MOVERS_GE_50",
        365,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2025, 1, 1)),
        [constituent_id],
    )

    assert partial["status"] == "missing_data"

    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1704326400,
                "trading_date": "2024-01-04",
                "open": 90.0,
                "high": 95.0,
                "low": 88.0,
                "close": 93.0,
                "volume": 1000.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )

    complete = historical_store.coverage_status_for_constituent_ids(
        "NIFTY_500_UPWARD_MOVERS_GE_50",
        365,
        HistoricalWindow(from_date=date(2024, 1, 1), to_date_exclusive=date(2025, 1, 1)),
        [constituent_id],
    )

    assert complete["status"] == "up_to_date"
