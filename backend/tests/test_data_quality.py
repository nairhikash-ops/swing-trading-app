from datetime import date

from app.config import Settings
from app.data_quality import DataQualityService
from app.historical_data import HistoricalDataStore, HistoricalWindow
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


def seed_universe_and_instruments(universe_store, instrument_store):
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": "Healthy Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "HEALTHY",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000001",
            },
            {
                "COMPANY NAME": "Stale Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "STALE",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000002",
            },
            {
                "COMPANY NAME": "Move Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "MOVE",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000003",
            },
            {
                "COMPANY NAME": "Unmapped Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": "UNMAPPED",
                "SERIES": "EQ",
                "ISIN CODE": "INE000000004",
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
                "UNDERLYING_SYMBOL": "HEALTHY",
                "SYMBOL_NAME": "HEALTHY LTD",
                "DISPLAY_NAME": "Healthy",
                "SERIES": "EQ",
            },
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "2",
                "ISIN": "INE000000002",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "STALE",
                "SYMBOL_NAME": "STALE LTD",
                "DISPLAY_NAME": "Stale",
                "SERIES": "EQ",
            },
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": "3",
                "ISIN": "INE000000003",
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": "MOVE",
                "SYMBOL_NAME": "MOVE LTD",
                "DISPLAY_NAME": "Move",
                "SERIES": "EQ",
            },
        ],
        "NSE",
        "E",
    )


def candle(trading_date: str, close: float, volume: float = 1000.0):
    return {
        "timestamp": 1714526100,
        "trading_date": trading_date,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": volume,
        "open_interest": None,
    }


def test_quality_report_summarizes_healthy_blocked_and_warning_rows(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_universe_and_instruments(universe_store, instrument_store)
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 4)),
    )
    items = {item["symbol"]: item for item in historical_store.items(run_id)}
    historical_store.upsert_candles(items["HEALTHY"], [candle("2024-05-01", 100), candle("2024-05-02", 101)], "NSE_EQ", "EQUITY")
    historical_store.upsert_candles(items["STALE"], [candle("2024-05-01", 100)], "NSE_EQ", "EQUITY")
    historical_store.upsert_candles(items["MOVE"], [candle("2024-05-01", 100), candle("2024-05-02", 130)], "NSE_EQ", "EQUITY")

    report = DataQualityService(settings, token_store).report(status_filter="all")
    by_symbol = {item["symbol"]: item for item in report["items"]}

    assert report["expected_session_count"] == 2
    assert report["healthy_count"] == 1
    assert report["warning_count"] == 1
    assert report["blocked_count"] == 2
    assert by_symbol["HEALTHY"]["quality_status"] == "healthy"
    assert by_symbol["STALE"]["quality_status"] == "blocked"
    assert "STALE_LATEST_CANDLE" in by_symbol["STALE"]["issues"]
    assert by_symbol["MOVE"]["quality_status"] == "warning"
    assert "EXTREME_MOVE" in by_symbol["MOVE"]["issues"]
    assert by_symbol["UNMAPPED"]["quality_status"] == "blocked"
    assert "UNMAPPED_INSTRUMENT" in by_symbol["UNMAPPED"]["issues"]


def test_quality_report_defaults_to_exceptions_only(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_universe_and_instruments(universe_store, instrument_store)
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=date(2024, 5, 1), to_date_exclusive=date(2024, 5, 3)),
    )
    items = {item["symbol"]: item for item in historical_store.items(run_id)}
    historical_store.upsert_candles(items["HEALTHY"], [candle("2024-05-01", 100)], "NSE_EQ", "EQUITY")

    report = DataQualityService(settings, token_store).report()

    assert all(item["quality_status"] != "healthy" for item in report["items"])
