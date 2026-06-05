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


def seed_symbol(
    universe_store,
    instrument_store,
    isin: str = "INE000000001",
    symbol: str = "BEML",
    security_id: str = "395",
):
    seed_symbols(
        universe_store,
        instrument_store,
        [
            {
                "isin": isin,
                "symbol": symbol,
                "security_id": security_id,
            }
        ],
    )


def seed_symbols(universe_store, instrument_store, symbols: list[dict[str, str]]):
    universe_run_id = universe_store.start_import("NIFTY_500", "source.csv", ["Company Name"])
    universe_store.upsert_constituents(
        universe_run_id,
        "NIFTY_500",
        [
            {
                "COMPANY NAME": f"{item['symbol']} Ltd.",
                "INDUSTRY": "Capital Goods",
                "SYMBOL": item["symbol"],
                "SERIES": "EQ",
                "ISIN CODE": item["isin"],
            }
            for item in symbols
        ],
    )
    instrument_run_id = instrument_store.start_import("dhan.csv", "NSE", "E", ["EXCH_ID"])
    instrument_store.upsert_rows(
        instrument_run_id,
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "E",
                "SECURITY_ID": item["security_id"],
                "ISIN": item["isin"],
                "INSTRUMENT": "EQUITY",
                "UNDERLYING_SYMBOL": item["symbol"],
                "SYMBOL_NAME": f"{item['symbol']} LTD",
                "DISPLAY_NAME": item["symbol"],
                "SERIES": "EQ",
            }
            for item in symbols
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


def near_support_reclaim_candles(start_date: date):
    candles = sr_candles(start_date)
    candles[-1].update(
        {
            "open": 90,
            "high": 94,
            "low": 84,
            "close": 92,
            "volume": 2500,
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
    assert report["nearest_support"]["zone_low"] < report["nearest_support"]["zone_high"]
    assert report["nearest_resistance"]["zone_low"] < report["nearest_resistance"]["zone_high"]
    assert report["nearest_support"]["mid_price"] < report["latest_close"]
    assert report["nearest_resistance"]["mid_price"] > report["latest_close"]
    assert report["nearest_support"]["touch_count"] >= 2
    assert report["nearest_resistance"]["touch_count"] >= 2
    assert report["atr_14"] > 0
    assert report["zone_percent"] == 1.5
    assert report["zone_atr_multiplier"] == 0.5
    assert report["near_support"] is False
    assert report["inside_support_zone"] is False
    assert report["support_distance_percent"] is not None
    assert report["support_zone_state"] == "above_support"
    assert report["support_reclaim"] is False


def test_support_state_fields_mark_near_zone_and_reclaim():
    report = detect_support_resistance(near_support_reclaim_candles(date(2026, 1, 1)))

    assert report["nearest_support"] is not None
    assert report["inside_support_zone"] is True
    assert report["near_support"] is True
    assert report["support_zone_state"] == "inside_support_zone"
    assert report["support_distance_percent"] == 0
    assert report["broke_below_support_recently"] is True
    assert report["reclaimed_support_on_latest_close"] is True
    assert report["support_reclaim"] is True


def test_support_resistance_pivot_touches_include_confirmation_metadata():
    report = detect_support_resistance(sr_candles(date(2026, 1, 1)))

    touch = report["nearest_support"]["touches"][0]
    assert "confirmed_index" in touch
    assert "confirmed_date" in touch
    if touch["source"].startswith("swing_"):
        assert touch["confirmed_index"] == touch["index"] + report["pivot_right"]


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
    assert "zone_low" in report["nearest_support"]
    assert "near_support" in report


def test_nifty_500_near_support_bulk_scan_returns_expected_symbols(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbols(
        universe_store,
        instrument_store,
        [
            {"isin": "INE000000001", "symbol": "BEML", "security_id": "395"},
            {"isin": "INE000000002", "symbol": "TCS", "security_id": "11536"},
        ],
    )
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    for item in historical_store.items(run_id, status="queued", limit=10):
        candles = near_support_reclaim_candles(window.from_date) if item["symbol"] == "BEML" else sr_candles(window.from_date)
        historical_store.upsert_candles(
            item,
            [historical_candle(candle) for candle in candles],
            "NSE_EQ",
            "EQUITY",
        )

    items = SupportResistanceService(token_store).nifty_500_near_support(limit=10)

    assert [item["symbol"] for item in items] == ["BEML"]
    assert items[0]["inside_support_zone"] is True
    assert items[0]["near_support"] is True
    assert items[0]["support_reclaim"] is True
    assert items[0]["nearest_support"]["role"] == "support"


def test_nifty_500_near_support_limit_applies_after_full_scan(tmp_path):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbols(
        universe_store,
        instrument_store,
        [
            {"isin": "INE000000001", "symbol": "AAAAA", "security_id": "101"},
            {"isin": "INE000000002", "symbol": "BEML", "security_id": "395"},
        ],
    )
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    for item in historical_store.items(run_id, status="queued", limit=10):
        candles = near_support_reclaim_candles(window.from_date) if item["symbol"] == "BEML" else sr_candles(window.from_date)
        historical_store.upsert_candles(
            item,
            [historical_candle(candle) for candle in candles],
            "NSE_EQ",
            "EQUITY",
        )

    items = SupportResistanceService(token_store).nifty_500_near_support(limit=1)

    assert [item["symbol"] for item in items] == ["BEML"]
