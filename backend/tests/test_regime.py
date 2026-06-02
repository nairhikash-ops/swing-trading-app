from datetime import date

from app.config import Settings
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.regime import StockRegimeService, classify_regime_series
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


def regime_candles(start_date: date, kind: str):
    candles = []
    for index in range(75):
        if kind == "up":
            close = 100.0 + index
        elif kind == "down":
            close = 200.0 - index
        else:
            close = 100.0 + (1.0 if index % 2 == 0 else -1.0)
        candles.append(
            {
                "trading_date": date.fromordinal(start_date.toordinal() + index).isoformat(),
                "open": close - 0.25,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000.0,
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


def seed_regime_history(tmp_path, kind: str):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [historical_candle(candle) for candle in regime_candles(window.from_date, kind)],
        "NSE_EQ",
        "EQUITY",
    )
    return settings, token_store


def test_classifies_uptrend_from_sma_slope_and_range_position():
    rows = classify_regime_series(regime_candles(date(2026, 1, 1), "up"))

    assert rows[-1]["regime"] == "UPTREND"
    assert rows[-1]["sma_50_slope_10d_percent"] > 1
    assert rows[-1]["range_position"] > 0.55


def test_classifies_downtrend_from_sma_slope_and_range_position():
    rows = classify_regime_series(regime_candles(date(2026, 1, 1), "down"))

    assert rows[-1]["regime"] == "DOWNTREND"
    assert rows[-1]["sma_50_slope_10d_percent"] < -1
    assert rows[-1]["range_position"] < 0.45


def test_classifies_sideways_when_slope_and_range_are_mixed():
    rows = classify_regime_series(regime_candles(date(2026, 1, 1), "sideways"))

    assert rows[-1]["regime"] == "SIDEWAYS"


def test_regime_refresh_persists_history_and_latest_report(tmp_path):
    settings, token_store = seed_regime_history(tmp_path, "up")

    report = StockRegimeService(token_store).refresh_nifty_500_regimes()
    history = StockRegimeService(token_store).history_for_symbol("BEML")

    assert report["status"] == "completed"
    assert report["total_symbols"] == 1
    assert report["uptrend_count"] == 1
    assert report["items"][0]["symbol"] == "BEML"
    assert report["items"][0]["regime"] == "UPTREND"
    assert report["items"][0]["confidence"] > 0
    assert len(history) == report["classified_count"]
