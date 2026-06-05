from datetime import date

from app.config import Settings
from app.demo_trading import DemoTradingService
from app.drishti import DrishtiSignalService
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore


def make_stores(tmp_path, **settings_overrides):
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path, historical_lookback_calendar_days=90, **settings_overrides)
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


def signal_candles(start_date: date, include_next_session: bool = True):
    candles = []
    for index in range(59):
        close = 180.0 - index * 0.8
        candles.append(
            {
                "trading_date": date.fromordinal(start_date.toordinal() + index).isoformat(),
                "open": close + 0.5,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1000.0,
            }
        )
    candles.extend(
        [
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 59).isoformat(),
                "open": 108.0,
                "high": 110.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1000.0,
            },
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 60).isoformat(),
                "open": 106.0,
                "high": 126.0,
                "low": 105.0,
                "close": 124.0,
                "volume": 1500.0,
            },
        ]
    )
    if include_next_session:
        candles.append(
            {
                "trading_date": date.fromordinal(start_date.toordinal() + 61).isoformat(),
                "open": 101.0,
                "high": 104.0,
                "low": 100.5,
                "close": 103.0,
                "volume": 1200.0,
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


def seed_drishti_hit(tmp_path, include_next_session: bool = True):
    settings, token_store, universe_store, instrument_store, historical_store = make_stores(tmp_path)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    historical_store.upsert_candles(
        item,
        [historical_candle(candle) for candle in signal_candles(window.from_date, include_next_session)],
        "NSE_EQ",
        "EQUITY",
    )
    report = DrishtiSignalService(settings, token_store).refresh_nifty_500_signal_01()
    return settings, token_store, report["items"][0]


def test_demo_order_from_drishti_hit_fills_next_session_and_tracks_target_exit(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    service = DemoTradingService(settings, token_store)
    expected_entry_date = date.fromordinal(date.fromisoformat(hit["trigger_date"]).toordinal() + 1).isoformat()

    result = service.place_order_from_drishti_hit(hit["id"])

    assert result["order"]["status"] == "filled"
    assert result["order"]["filled_date"] == expected_entry_date
    assert result["order"]["filled_price"] == 101.0
    assert result["order"]["stop_loss"] == 100.0
    assert result["order"]["target_price"] == 103.0
    assert result["position"]["status"] == "closed"
    assert result["position"]["exit_reason"] == "TARGET"
    assert result["position"]["realized_pnl"] == 2.0
    assert result["summary"]["realized_pnl"] == 2.0


def test_demo_order_creation_is_idempotent_for_same_signal_hit(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    service = DemoTradingService(settings, token_store)

    first = service.place_order_from_drishti_hit(hit["id"])
    second = service.place_order_from_drishti_hit(hit["id"])
    orders = service.orders()

    assert first["order"]["id"] == second["order"]["id"]
    assert len(orders) == 1


def test_demo_order_creation_is_idempotent_for_same_signal_identity(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    service = DemoTradingService(settings, token_store)
    first = service.place_order_from_drishti_hit(hit["id"])
    with token_store._connect() as conn:
        original = dict(conn.execute("SELECT * FROM drishti_signal_hits WHERE id = ?", (hit["id"],)).fetchone())
        original.pop("id")
        original["run_id"] = int(original["run_id"]) + 1
        columns = list(original.keys())
        column_sql = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO drishti_signal_hits ({column_sql}) VALUES ({placeholders})",
            tuple(original[column] for column in columns),
        )
        duplicate_id = conn.execute("SELECT MAX(id) AS id FROM drishti_signal_hits").fetchone()["id"]

    second = service.place_order_from_drishti_hit(int(duplicate_id))

    assert first["order"]["id"] == second["order"]["id"]
    assert len(service.orders()) == 1


def test_demo_order_waits_when_next_session_candle_is_missing(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    service = DemoTradingService(settings, token_store)

    result = service.place_order_from_drishti_hit(hit["id"])

    assert result["order"]["status"] == "pending_entry"
    assert result["position"] is None
    assert result["summary"]["pending_orders"] == 1
