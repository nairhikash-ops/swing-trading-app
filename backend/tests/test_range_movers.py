from datetime import date

from app.config import Settings
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.range_movers import RangeMoverService
from app.store import TokenStore


def make_stores(tmp_path):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    return (
        token_store,
        IndexUniverseStore(token_store),
        InstrumentMasterStore(token_store),
        HistoricalDataStore(token_store),
    )


def seed_symbol(universe_store, instrument_store, isin: str, symbol: str, security_id: str):
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": f"{symbol} Ltd.",
                "INDUSTRY": "Technology",
                "SYMBOL": symbol,
                "SERIES": "EQ",
                "ISIN CODE": isin,
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
                "SECURITY_ID": security_id,
                "ISIN": isin,
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": symbol,
                "SYMBOL_NAME": f"{symbol} LTD",
                "DISPLAY_NAME": symbol,
                "SERIES": "EQ",
            }
        ],
        "NSE",
        "E",
    )


def test_range_movers_returns_stocks_above_threshold(tmp_path):
    token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store, "INE000000001", "MOVE", "1")
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    window = historical_window(settings)
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        window,
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1714526100,
                "trading_date": window.from_date.isoformat(),
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1000.0,
                "open_interest": None,
            },
            {
                "timestamp": 1714612500,
                "trading_date": date.fromordinal(window.from_date.toordinal() + 1).isoformat(),
                "open": 104.0,
                "high": 106.0,
                "low": 102.0,
                "close": 105.0,
                "volume": 1000.0,
                "open_interest": None,
            },
        ],
        "NSE_EQ",
        "EQUITY",
    )
    historical_store.mark_item_done(item["id"], 2)
    historical_store.finish_run_if_complete(run_id)

    report = RangeMoverService(settings, token_store).nifty_500_range_movers(threshold_percent=5.0)

    assert report["match_count"] == 1
    assert report["from_date"] == window.from_date.isoformat()
    assert report["to_date_exclusive"] == window.to_date_exclusive.isoformat()
    assert report["historical_run_id"] == run_id
    assert report["items"][0]["symbol"] == "MOVE"
    assert report["items"][0]["lowest_low"] == 100.0
    assert report["items"][0]["highest_high"] == 106.0
    assert report["items"][0]["move_percent"] == 6.0


def test_range_movers_excludes_stocks_below_threshold(tmp_path):
    token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store, "INE000000001", "FLAT", "1")
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    window = historical_window(settings)
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        window,
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            {
                "timestamp": 1714526100,
                "trading_date": window.from_date.isoformat(),
                "open": 100.0,
                "high": 104.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1000.0,
                "open_interest": None,
            }
        ],
        "NSE_EQ",
        "EQUITY",
    )
    historical_store.mark_item_done(item["id"], 1)
    historical_store.finish_run_if_complete(run_id)

    report = RangeMoverService(settings, token_store).nifty_500_range_movers(threshold_percent=5.0)

    assert report["match_count"] == 0
