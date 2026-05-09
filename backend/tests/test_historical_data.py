from datetime import date

from app.config import Settings
from app.historical_data import HistoricalDataStore, HistoricalWindow, parse_historical_payload
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
