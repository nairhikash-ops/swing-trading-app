from datetime import date

from app.config import Settings
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore
from app.support_resistance import SupportResistanceService, detect_support_resistance


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


def sr_candles(start_date: date):
    closes = [100, 96, 92, 96, 102, 109, 113, 108, 101, 96, 91, 96, 102, 110, 114, 109, 104]
    candles = []
    for index, close in enumerate(closes):
        candles.append(
            {
                "trading_date": date.fromordinal(start_date.toordinal() + index).isoformat(),
                "open": close - 0.5,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    return candles


def historical_candle(candle: dict):
    return {
        "timestamp": 1714526100,
        "trading_date": candle["trading_date"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
        "open_interest": None,
    }


def test_detect_support_resistance_clusters_nearest_levels():
    report = detect_support_resistance(sr_candles(date(2026, 1, 1)))

    assert report["status"] == "ok"
    assert report["nearest_support"]["role"] == "support"
    assert report["nearest_resistance"]["role"] == "resistance"
    assert report["nearest_support"]["price"] < report["latest_close"]
    assert report["nearest_resistance"]["price"] > report["latest_close"]
    assert report["nearest_support"]["touch_count"] >= 2
    assert report["nearest_resistance"]["touch_count"] >= 2


def test_support_resistance_service_reads_symbol_candles(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [historical_candle(candle) for candle in sr_candles(window.from_date)],
        "NSE_EQ",
        "EQUITY",
    )

    report = SupportResistanceService(token_store).report_for_symbol("BEML")

    assert report["symbol"] == "BEML"
    assert report["instrument_id"] == item["instrument_id"]
    assert report["security_id"] == "395"
    assert report["nearest_support"] is not None
    assert report["nearest_resistance"] is not None
