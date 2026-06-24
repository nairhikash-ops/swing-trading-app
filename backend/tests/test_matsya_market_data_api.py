from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.matsya import api as matsya_api


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


class FakeMarketDataStore:
    def __init__(self) -> None:
        self.ohlcv_calls: list[dict[str, object]] = []
        self.latest_calls: list[dict[str, object]] = []

    def status(self) -> dict[str, object]:
        return {
            "total_instruments": 9541,
            "universe_members": 500,
            "ohlcv_row_count": 554444,
            "first_candle_date": "2021-06-25",
            "latest_candle_date": "2026-06-23",
            "symbols_with_candles": 500,
            "duplicate_count": 0,
            "null_ohlcv_count": 0,
            "bad_ohlc_count": 0,
            "negative_volume_count": 0,
            "stale_symbols": 0,
            "missing_recent_symbol_dates": 0,
            "latest_ohlcv_run": {"id": 3, "status": "completed", "total_symbols": 500, "mapped_symbols": 500},
            "token_state": "active",
        }

    def symbols(self, *, universe: str, active: bool, limit: int, offset: int) -> dict[str, object]:
        return {
            "universe": universe,
            "limit": min(limit, 5000),
            "offset": offset,
            "symbols": [
                {
                    "symbol": "RELIANCE",
                    "company_name": "Reliance Industries Limited",
                    "exchange": "NSE",
                    "segment": "E",
                    "instrument": "EQUITY",
                    "security_id": "2885",
                    "first_candle_date": "2021-06-25",
                    "latest_candle_date": "2026-06-23",
                    "candle_count": 1237,
                    "freshness_state": "FRESH",
                }
            ],
        }

    def ohlcv(
        self,
        *,
        symbol: str | None,
        security_id: str | None,
        from_date: date | None,
        to_date: date | None,
        limit: int,
        order: str,
    ) -> dict[str, object]:
        self.ohlcv_calls.append(
            {
                "symbol": symbol,
                "security_id": security_id,
                "from_date": from_date,
                "to_date": to_date,
                "limit": limit,
                "order": order,
            }
        )
        return {
            "symbol": symbol or "RELIANCE",
            "security_id": security_id or "2885",
            "exchange_segment": "NSE_EQ",
            "instrument": "EQUITY",
            "limit": min(limit, 5000),
            "order": order,
            "candles": [
                {
                    "trading_date": "2026-06-23",
                    "open": 1.0,
                    "high": 2.0,
                    "low": 1.0,
                    "close": 1.5,
                    "volume": 100.0,
                }
            ],
        }

    def latest_ohlcv(self, *, symbol: str | None, security_id: str | None, days: int) -> dict[str, object]:
        self.latest_calls.append({"symbol": symbol, "security_id": security_id, "days": days})
        return {
            "symbol": symbol or "RELIANCE",
            "security_id": security_id or "2885",
            "exchange_segment": "NSE_EQ",
            "instrument": "EQUITY",
            "days": min(days, 2000),
            "candles": [
                {
                    "trading_date": "2026-06-23",
                    "open": 1.0,
                    "high": 2.0,
                    "low": 1.0,
                    "close": 1.5,
                    "volume": 100.0,
                }
            ],
        }

    def validation(self) -> dict[str, object]:
        return {
            "total_rows": 554444,
            "symbols_with_candles": 500,
            "first_stored_candle_date": "2021-06-25",
            "latest_stored_candle_date": "2026-06-23",
            "duplicate_count": 0,
            "null_ohlcv_count": 0,
            "bad_ohlc_count": 0,
            "negative_volume_count": 0,
            "zero_candle_symbols": 0,
            "stale_symbols": 0,
            "missing_recent_symbol_dates": 0,
            "expected_latest_candle_date": "2026-06-23",
            "validation_start_date": "2026-04-01",
        }


def make_client(fake: FakeMarketDataStore) -> TestClient:
    app = FastAPI()
    app.include_router(matsya_api.router)
    matsya_api.build_market_data_store = lambda: fake  # type: ignore[method-assign]
    return TestClient(app)


def test_market_data_routes_are_get_only_and_read_only() -> None:
    api = read("backend/app/matsya/api.py")
    market_data = read("backend/app/matsya/market_data.py")

    assert '@router.get("/market-data/status"' in api
    assert '@router.get("/market-data/symbols"' in api
    assert '@router.get("/market-data/ohlcv"' in api
    assert '@router.get("/market-data/ohlcv/latest"' in api
    assert '@router.get("/market-data/validation"' in api
    assert '@router.post("/market-data' not in api
    assert '@router.put("/market-data' not in api
    assert '@router.patch("/market-data' not in api
    assert '@router.delete("/market-data' not in api

    read_only_source = market_data.upper()
    assert "INSERT INTO" not in read_only_source
    assert "UPDATE " not in read_only_source
    assert "DELETE FROM" not in read_only_source
    assert "TRUNCATE" not in read_only_source
    assert "DROP TABLE" not in read_only_source


def test_market_data_status_excludes_secret_fields() -> None:
    client = make_client(FakeMarketDataStore())
    response = client.get("/api/matsya/market-data/status")

    assert response.status_code == 200
    body = response.json()
    assert body["token_state"] == "active"
    text = response.text.lower()
    assert "access_token" not in text
    assert "encrypted_access_token" not in text
    assert "password" not in text
    assert "secret" not in text


def test_market_data_symbols_returns_mapped_symbols_with_cap() -> None:
    client = make_client(FakeMarketDataStore())
    response = client.get("/api/matsya/market-data/symbols?limit=999999&offset=2")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5000
    assert body["offset"] == 2
    assert body["symbols"][0]["symbol"] == "RELIANCE"
    assert body["symbols"][0]["security_id"] == "2885"


def test_market_data_ohlcv_supports_symbol_security_id_date_filter_and_limit_cap() -> None:
    fake = FakeMarketDataStore()
    client = make_client(fake)

    by_symbol = client.get("/api/matsya/market-data/ohlcv?symbol=RELIANCE&from=2026-06-01&to=2026-06-23&limit=999999&order=desc")
    by_security = client.get("/api/matsya/market-data/ohlcv?security_id=2885&limit=5&order=asc")

    assert by_symbol.status_code == 200
    assert by_symbol.json()["limit"] == 5000
    assert by_symbol.json()["order"] == "desc"
    assert fake.ohlcv_calls[0]["from_date"] == date(2026, 6, 1)
    assert fake.ohlcv_calls[0]["to_date"] == date(2026, 6, 23)
    assert by_security.status_code == 200
    assert fake.ohlcv_calls[1]["security_id"] == "2885"


def test_market_data_ohlcv_requires_symbol_or_security_id() -> None:
    client = make_client(FakeMarketDataStore())

    response = client.get("/api/matsya/market-data/ohlcv?limit=5")

    assert response.status_code == 400


def test_market_data_latest_caps_days_and_returns_ascending_candles() -> None:
    fake = FakeMarketDataStore()
    client = make_client(fake)

    response = client.get("/api/matsya/market-data/ohlcv/latest?symbol=RELIANCE&days=999999")

    assert response.status_code == 200
    assert response.json()["days"] == 2000
    assert fake.latest_calls[0]["symbol"] == "RELIANCE"


def test_market_data_validation_is_safe_summary() -> None:
    client = make_client(FakeMarketDataStore())

    response = client.get("/api/matsya/market-data/validation")

    assert response.status_code == 200
    body = response.json()
    assert body["duplicate_count"] == 0
    assert body["null_ohlcv_count"] == 0
    assert "raw_candle" not in response.text
