from datetime import date

from app.config import Settings
from app.historical_data import HistoricalDataStore, HistoricalWindow, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.move_events import MoveEventService, detect_move_events
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


def candle(trading_date: str, low: float, high: float, close: float):
    return {"trading_date": trading_date, "low": low, "high": high, "close": close}


def historical_candle(trading_date: str, low: float, high: float, close: float):
    return {
        "timestamp": 1714526100,
        "trading_date": trading_date,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000.0,
        "open_interest": None,
    }


def seed_symbol(universe_store, instrument_store, isin: str = "INE000000001", symbol: str = "MOVE"):
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
                "SECURITY_ID": "1",
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


def test_detect_move_events_merges_continuous_smaller_moves():
    events = detect_move_events(
        [
            candle("2026-04-01", 100.0, 102.0, 101.0),
            candle("2026-04-02", 103.0, 112.0, 111.0),
            candle("2026-04-03", 110.0, 125.0, 124.0),
        ],
        threshold_percent=10.0,
        pullback_percent=5.0,
    )

    assert len(events) == 1
    assert events[0]["low_price"] == 100.0
    assert events[0]["high_price"] == 125.0
    assert events[0]["move_percent"] == 25.0


def test_detect_move_events_splits_after_close_pullback():
    events = detect_move_events(
        [
            candle("2026-04-01", 100.0, 102.0, 101.0),
            candle("2026-04-02", 103.0, 112.0, 111.0),
            candle("2026-04-03", 105.0, 108.0, 105.0),
            candle("2026-04-04", 106.0, 118.0, 117.0),
        ],
        threshold_percent=10.0,
        pullback_percent=5.0,
    )

    assert len(events) == 2
    assert events[0]["low_price"] == 100.0
    assert events[0]["high_price"] == 112.0
    assert events[0]["split_pullback_date"] == "2026-04-03"
    assert events[1]["low_price"] == 105.0
    assert events[1]["high_price"] == 118.0


def test_detect_move_events_requires_low_before_high():
    events = detect_move_events(
        [
            candle("2026-04-01", 100.0, 115.0, 112.0),
            candle("2026-04-02", 102.0, 105.0, 104.0),
        ],
        threshold_percent=10.0,
        pullback_percent=5.0,
    )

    assert events == []


def test_refresh_move_events_stores_candidate_events(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run(
        "NIFTY_500",
        45,
        HistoricalWindow(from_date=window.from_date, to_date_exclusive=window.to_date_exclusive),
    )
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [
            historical_candle(window.from_date.isoformat(), 100.0, 102.0, 101.0),
            historical_candle(date.fromordinal(window.from_date.toordinal() + 1).isoformat(), 103.0, 112.0, 111.0),
        ],
        "NSE_EQ",
        "EQUITY",
    )

    report = MoveEventService(settings, token_store).refresh_nifty_500_events(
        threshold_percent=10.0,
        pullback_percent=5.0,
    )

    assert report["event_count"] == 1
    assert report["candidate_symbols"] == 1
    assert report["items"][0]["symbol"] == "MOVE"
    assert report["items"][0]["bucket"] == "10-20"
