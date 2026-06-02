from datetime import date

from app.candlesticks import CandlestickService, classify_candles
from app.config import Settings
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore


def make_stores(tmp_path):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path, historical_lookback_calendar_days=120)
    token_store = TokenStore(settings.database_path)
    return (
        settings,
        token_store,
        IndexUniverseStore(token_store),
        InstrumentMasterStore(token_store),
        HistoricalDataStore(token_store),
    )


def seed_symbol(universe_store, instrument_store, isin: str = "INE000000001", symbol: str = "BEML"):
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": f"{symbol} Ltd.",
                "INDUSTRY": "Capital Goods",
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
                "SECURITY_ID": "395",
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


def candle(day: int, open_price: float, high: float, low: float, close: float):
    return {
        "trading_date": date.fromordinal(date(2026, 1, 1).toordinal() + day).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000 + day,
    }


def historical_candle(item: dict):
    return {
        "timestamp": 1714526100,
        "trading_date": item["trading_date"],
        "open": item["open"],
        "high": item["high"],
        "low": item["low"],
        "close": item["close"],
        "volume": item["volume"],
        "open_interest": None,
    }


def test_classifies_textbook_indecision_single_candles():
    items = classify_candles(
        [
            candle(0, 100, 110, 90, 100.5),
            candle(1, 100, 102, 90, 100.4),
            candle(2, 100, 110, 99, 100.4),
        ]
    )

    assert "long_legged_doji" in items[0]["patterns"]
    assert "dragonfly_doji" in items[1]["patterns"]
    assert "gravestone_doji" in items[2]["patterns"]
    assert items[0]["indecision_score"] > 0


def test_classifies_indecision_combination_candles():
    items = classify_candles(
        [
            candle(0, 110, 112, 95, 96),
            candle(1, 101, 104, 99, 101.2),
            candle(2, 101.5, 103, 100, 101.6),
        ]
    )

    assert "harami" in items[1]["patterns"]
    assert "harami_cross" in items[1]["patterns"]
    assert "inside_bar" in items[2]["patterns"]


def test_candlestick_service_reads_symbol_candles(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    candles = [
        candle(0, 100, 110, 90, 100.5),
        candle(1, 100, 102, 90, 100.4),
        candle(2, 100, 110, 99, 100.4),
        candle(3, 103, 104, 102, 103.1),
        candle(4, 103, 104, 102, 103.05),
    ]
    historical_store.upsert_candles(
        item,
        [historical_candle(candle_item) for candle_item in candles],
        "NSE_EQ",
        "EQUITY",
    )

    report = CandlestickService(token_store).report_for_symbol("BEML")

    assert report["symbol"] == "BEML"
    assert report["security_id"] == "395"
    assert report["candle_count"] == 5
    assert report["pattern_counts"]["doji"] >= 3
