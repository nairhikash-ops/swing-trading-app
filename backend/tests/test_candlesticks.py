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


def test_classifies_bullish_reversal_candles_after_downtrend():
    items = classify_candles(
        [
            candle(0, 122, 123, 119, 120),
            candle(1, 119, 120, 115, 116),
            candle(2, 115, 116, 111, 112),
            candle(3, 111, 112, 107, 108),
            candle(4, 107, 108, 103, 104),
            candle(5, 104, 105, 98, 100),
            candle(6, 99, 108, 98, 106),
            candle(7, 106, 107, 96, 106.5),
        ]
    )

    assert "bullish_engulfing" in items[6]["reversal_patterns"]
    assert items[6]["reversal_bias"] == "bullish"
    assert items[6]["reversal_score"] > 0
    assert "hammer" in items[7]["reversal_patterns"]


def test_classifies_morning_and_evening_star_reversals():
    bullish_items = classify_candles(
        [
            candle(0, 132, 133, 129, 130),
            candle(1, 129, 130, 125, 126),
            candle(2, 125, 126, 121, 122),
            candle(3, 121, 122, 117, 118),
            candle(4, 117, 118, 113, 114),
            candle(5, 114, 115, 100, 102),
            candle(6, 101, 103, 99, 101.2),
            candle(7, 103, 111, 102, 110),
        ]
    )
    bearish_items = classify_candles(
        [
            candle(0, 100, 103, 99, 102),
            candle(1, 102, 107, 101, 106),
            candle(2, 106, 111, 105, 110),
            candle(3, 110, 115, 109, 114),
            candle(4, 114, 119, 113, 118),
            candle(5, 118, 130, 117, 129),
            candle(6, 129, 131, 127, 128.8),
            candle(7, 127, 128, 119, 121),
        ]
    )

    assert "morning_star" in bullish_items[7]["reversal_patterns"]
    assert bullish_items[7]["reversal_bias"] == "bullish"
    assert "evening_star" in bearish_items[7]["reversal_patterns"]
    assert bearish_items[7]["reversal_bias"] == "bearish"


def test_classifies_bearish_reversal_candles_after_uptrend():
    items = classify_candles(
        [
            candle(0, 100, 103, 99, 102),
            candle(1, 102, 107, 101, 106),
            candle(2, 106, 111, 105, 110),
            candle(3, 110, 115, 109, 114),
            candle(4, 114, 119, 113, 118),
            candle(5, 118, 124, 117, 123),
            candle(6, 124, 125, 113, 115),
            candle(7, 121, 130, 120, 120.5),
        ]
    )

    assert "bearish_engulfing" in items[6]["reversal_patterns"]
    assert items[6]["reversal_bias"] == "bearish"
    assert "shooting_star" in items[7]["reversal_patterns"]


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
    assert "latest_reversal_patterns" in report
