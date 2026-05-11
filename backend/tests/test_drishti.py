from datetime import date

from app.config import Settings
from app.drishti import (
    DRISHTI_SIGNAL_01_ID,
    DrishtiSignalService,
    detect_signal_01_local_low_reversal,
)
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore


def make_stores(tmp_path):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path, historical_lookback_calendar_days=90)
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


def sample_signal_candles(start_date: date):
    candles = []
    for index in range(44):
        candles.append(
            {
                "trading_date": date.fromordinal(start_date.toordinal() + index).isoformat(),
                "open": 150.0 - index * 0.2,
                "high": 152.0 - index * 0.2,
                "low": 110.0 + index,
                "close": 151.0 - index * 0.2,
                "volume": 1000.0,
            }
        )
    candles.extend(
        [
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 44).isoformat(),
                "open": 105.0,
                "high": 106.0,
                "low": 90.0,
                "close": 92.0,
                "volume": 1000.0,
            },
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 45).isoformat(),
                "open": 96.0,
                "high": 115.0,
                "low": 95.0,
                "close": 112.0,
                "volume": 1500.0,
            },
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 46).isoformat(),
                "open": 113.0,
                "high": 130.0,
                "low": 110.0,
                "close": 128.0,
                "volume": 1200.0,
            },
        ]
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


def test_signal_01_detects_volume_confirmed_local_low_reversal():
    candles = sample_signal_candles(date(2026, 1, 1))

    hits = detect_signal_01_local_low_reversal(candles)

    assert len(hits) == 1
    assert hits[0]["anchor_date"] == "2026-02-14"
    assert hits[0]["trigger_date"] == "2026-02-15"
    assert hits[0]["anchor_low"] == 90.0
    assert hits[0]["trigger_close"] == 112.0
    assert hits[0]["future_high"] == 130.0
    assert round(hits[0]["volume_ratio_1d"], 2) == 1.5
    assert round(hits[0]["outcome_from_trigger_percent"], 2) == 16.07


def test_signal_01_rejects_trigger_without_volume_confirmation():
    candles = sample_signal_candles(date(2026, 1, 1))
    candles[45]["volume"] = 1100.0

    hits = detect_signal_01_local_low_reversal(candles)

    assert hits == []


def test_signal_01_requires_full_lookback_before_anchor():
    candles = sample_signal_candles(date(2026, 1, 1))[10:]

    hits = detect_signal_01_local_low_reversal(candles)

    assert hits == []


def test_drishti_refresh_stores_signal_definition_and_hits(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    candles = sample_signal_candles(window.from_date)
    historical_store.upsert_candles(item, [historical_candle(candle) for candle in candles], "NSE_EQ", "EQUITY")

    report = DrishtiSignalService(settings, token_store).refresh_nifty_500_signal_01()

    assert report["signal_id"] == DRISHTI_SIGNAL_01_ID
    assert report["signal_name"] == "Signal 01: Local Low Reversal"
    assert report["hit_count"] == 1
    assert report["outcome_ge_10_count"] == 1
    assert report["items"][0]["symbol"] == "BEML"
    assert report["items"][0]["security_id"] == "395"
