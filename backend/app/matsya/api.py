from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.matsya.market_data import DEFAULT_LATEST_DAYS, DEFAULT_LIMIT, MAX_LATEST_DAYS, MAX_LIMIT, MatsyaMarketDataStore
from app.matsya.paper_trading_report import PaperTradingReportService
from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import MatsyaDhanTokenService
from app.matsya.v8_demo_report import V8DemoReportService


router = APIRouter(prefix="/api/matsya", tags=["Matsya"])


TokenState = Literal["missing", "active", "expiring_soon", "expired", "renew_failed", "config_error", "unknown"]


class MatsyaHealthResponse(BaseModel):
    status: str
    app: str


class MatsyaDhanStatusResponse(BaseModel):
    has_token: bool
    dhan_client_id: str | None = None
    token_state: TokenState
    expiry_time: datetime | None = None
    data_plan: str | None = None
    data_validity: str | None = None
    last_status_check_at: datetime | None = None
    last_renew_success_at: datetime | None = None
    last_error: str = ""


class MatsyaDhanTokenRequest(BaseModel):
    dhan_client_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=20)
    expiry_time: datetime | None = None
    validate_with_dhan: bool = True


class MatsyaRenewResponse(BaseModel):
    renewed: bool
    status: MatsyaDhanStatusResponse
    message: str


class MatsyaLatestRunResponse(BaseModel):
    id: int | None = None
    status: str = ""
    total_symbols: int = 0
    mapped_symbols: int = 0
    skipped_symbols: int = 0
    error_message: str = ""
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class MatsyaMarketDataStatusResponse(BaseModel):
    total_instruments: int
    universe_members: int
    ohlcv_row_count: int
    first_candle_date: str | None = None
    latest_candle_date: str | None = None
    symbols_with_candles: int
    duplicate_count: int
    null_ohlcv_count: int
    bad_ohlc_count: int
    negative_volume_count: int
    stale_symbols: int
    missing_recent_symbol_dates: int
    latest_ohlcv_run: MatsyaLatestRunResponse
    token_state: TokenState


class MatsyaMarketSymbolResponse(BaseModel):
    symbol: str
    company_name: str = ""
    exchange: str = ""
    segment: str = ""
    instrument: str = ""
    security_id: str
    first_candle_date: str | None = None
    latest_candle_date: str | None = None
    candle_count: int
    freshness_state: str


class MatsyaMarketSymbolsResponse(BaseModel):
    universe: str
    limit: int
    offset: int
    symbols: list[MatsyaMarketSymbolResponse]


class MatsyaOhlcvCandleResponse(BaseModel):
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MatsyaOhlcvResponse(BaseModel):
    symbol: str
    security_id: str
    exchange_segment: str
    instrument: str
    limit: int | None = None
    order: Literal["asc", "desc"] | None = None
    days: int | None = None
    candles: list[MatsyaOhlcvCandleResponse]


class MatsyaMarketValidationResponse(BaseModel):
    total_rows: int
    symbols_with_candles: int
    first_stored_candle_date: str | None = None
    latest_stored_candle_date: str | None = None
    duplicate_count: int
    null_ohlcv_count: int
    bad_ohlc_count: int
    negative_volume_count: int
    zero_candle_symbols: int
    stale_symbols: int
    missing_recent_symbol_dates: int
    expected_latest_candle_date: str
    validation_start_date: str


def build_token_service() -> MatsyaDhanTokenService:
    return MatsyaDhanTokenService(MatsyaSettings.from_env())


def build_market_data_store() -> MatsyaMarketDataStore:
    return MatsyaMarketDataStore(MatsyaSettings.from_env())


def market_data_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail="Matsya market data query failed.")


@router.get("/health", response_model=MatsyaHealthResponse)
async def health() -> MatsyaHealthResponse:
    return MatsyaHealthResponse(status="ok", app="matsya-api")


@router.get("/dhan/status", response_model=MatsyaDhanStatusResponse)
async def dhan_status() -> MatsyaDhanStatusResponse:
    try:
        return MatsyaDhanStatusResponse(**build_token_service().status())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/token", response_model=MatsyaDhanStatusResponse)
async def save_dhan_token(request: MatsyaDhanTokenRequest) -> MatsyaDhanStatusResponse:
    try:
        status = await build_token_service().save_manual_token(
            dhan_client_id=request.dhan_client_id.strip(),
            access_token=request.access_token.strip(),
            expiry_time=request.expiry_time,
            validate_with_dhan=request.validate_with_dhan,
        )
        return MatsyaDhanStatusResponse(**status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/status/refresh", response_model=MatsyaDhanStatusResponse)
async def refresh_dhan_status() -> MatsyaDhanStatusResponse:
    try:
        return MatsyaDhanStatusResponse(**await build_token_service().refresh_profile())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/renew", response_model=MatsyaRenewResponse)
async def renew_dhan_token() -> MatsyaRenewResponse:
    try:
        renewed, status, message = await build_token_service().renew()
        return MatsyaRenewResponse(renewed=renewed, status=MatsyaDhanStatusResponse(**status), message=message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/market-data/status", response_model=MatsyaMarketDataStatusResponse)
async def market_data_status() -> MatsyaMarketDataStatusResponse:
    try:
        return MatsyaMarketDataStatusResponse(**build_market_data_store().status())
    except Exception as exc:
        raise market_data_error(exc) from exc


@router.get("/market-data/symbols", response_model=MatsyaMarketSymbolsResponse)
async def market_data_symbols(
    universe: str = Query(default="NIFTY_500", min_length=1, max_length=64),
    active: bool = Query(default=True),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1),
    offset: int = Query(default=0, ge=0),
) -> MatsyaMarketSymbolsResponse:
    try:
        return MatsyaMarketSymbolsResponse(
            **build_market_data_store().symbols(universe=universe, active=active, limit=limit, offset=offset)
        )
    except Exception as exc:
        raise market_data_error(exc) from exc


@router.get("/market-data/ohlcv", response_model=MatsyaOhlcvResponse)
async def market_data_ohlcv(
    symbol: str | None = Query(default=None, min_length=1, max_length=64),
    security_id: str | None = Query(default=None, min_length=1, max_length=64),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1),
    order: Literal["asc", "desc"] = Query(default="asc"),
) -> MatsyaOhlcvResponse:
    if not symbol and not security_id:
        raise HTTPException(status_code=400, detail="Either symbol or security_id is required.")
    try:
        result = build_market_data_store().ohlcv(
            symbol=symbol,
            security_id=security_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            order=order,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Matsya instrument not found.")
        return MatsyaOhlcvResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise market_data_error(exc) from exc


@router.get("/market-data/ohlcv/latest", response_model=MatsyaOhlcvResponse)
async def market_data_latest_ohlcv(
    symbol: str | None = Query(default=None, min_length=1, max_length=64),
    security_id: str | None = Query(default=None, min_length=1, max_length=64),
    days: int = Query(default=DEFAULT_LATEST_DAYS, ge=1),
) -> MatsyaOhlcvResponse:
    if not symbol and not security_id:
        raise HTTPException(status_code=400, detail="Either symbol or security_id is required.")
    try:
        result = build_market_data_store().latest_ohlcv(symbol=symbol, security_id=security_id, days=days)
        if result is None:
            raise HTTPException(status_code=404, detail="Matsya instrument not found.")
        return MatsyaOhlcvResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise market_data_error(exc) from exc


@router.get("/market-data/validation", response_model=MatsyaMarketValidationResponse)
async def market_data_validation() -> MatsyaMarketValidationResponse:
    try:
        return MatsyaMarketValidationResponse(**build_market_data_store().validation())
    except Exception as exc:
        raise market_data_error(exc) from exc

@router.get("/demo/v8/status")
async def demo_v8_status(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return V8DemoReportService().status(limit=limit)


@router.get("/demo/paper-trading/status")
async def demo_paper_trading_status(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return PaperTradingReportService().combined_status(limit=limit)
