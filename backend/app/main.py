from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.data_quality import DataQualityService
from app.historical_data import HistoricalDataService, HistoricalDataStore, upward_movers_universe_name
from app.index_universe import IndexUniverseService, IndexUniverseStore
from app.instrument_master import InstrumentMasterService, InstrumentMasterStore
from app.move_events import MoveEventService
from app.nse_import import NseImportService, NseImportStore
from app.range_movers import RangeMoverService
from app.schemas import (
    DailyCandleItem,
    HealthResponse,
    HistoricalFetchItem,
    HistoricalFetchStatusResponse,
    InstrumentImportSummary,
    InstrumentMasterStatusResponse,
    InstrumentSearchItem,
    MoveEventReportResponse,
    NseEodCoverageResponse,
    NseEodRowItem,
    NseImportStatusResponse,
    NseImportUploadResponse,
    QualityReportResponse,
    RangeMoverReportResponse,
    RenewResponse,
    TokenStatusResponse,
    TokenUpdateRequest,
    UniverseConstituentItem,
    UniverseImportSummary,
    UniverseStatusResponse,
)
from app.scheduler import RenewalScheduler
from app.store import TokenStore
from app.token_service import TokenService


def build_token_service(settings: Settings) -> TokenService:
    return TokenService(settings=settings, store=TokenStore(settings.database_path))


def build_instrument_service(settings: Settings) -> InstrumentMasterService:
    token_store = TokenStore(settings.database_path)
    return InstrumentMasterService(settings=settings, store=InstrumentMasterStore(token_store))


def build_universe_service(settings: Settings) -> IndexUniverseService:
    token_store = TokenStore(settings.database_path)
    return IndexUniverseService(settings=settings, store=IndexUniverseStore(token_store))


def build_historical_service(settings: Settings) -> HistoricalDataService:
    token_store = TokenStore(settings.database_path)
    return HistoricalDataService(
        settings=settings,
        token_store=token_store,
        store=HistoricalDataStore(token_store),
    )


def build_quality_service(settings: Settings) -> DataQualityService:
    return DataQualityService(settings=settings, token_store=TokenStore(settings.database_path))


def build_range_mover_service(settings: Settings) -> RangeMoverService:
    return RangeMoverService(settings=settings, token_store=TokenStore(settings.database_path))


def build_move_event_service(settings: Settings) -> MoveEventService:
    return MoveEventService(settings=settings, token_store=TokenStore(settings.database_path))


def build_nse_import_service(settings: Settings) -> NseImportService:
    token_store = TokenStore(settings.database_path)
    return NseImportService(settings=settings, store=NseImportStore(settings, token_store))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    token_service = build_token_service(settings)
    instrument_service = build_instrument_service(settings)
    universe_service = build_universe_service(settings)
    historical_service = build_historical_service(settings)
    quality_service = build_quality_service(settings)
    range_mover_service = build_range_mover_service(settings)
    move_event_service = build_move_event_service(settings)
    nse_import_service = build_nse_import_service(settings)
    scheduler = RenewalScheduler(settings, token_service)
    app.state.settings = settings
    app.state.token_service = token_service
    app.state.instrument_service = instrument_service
    app.state.universe_service = universe_service
    app.state.historical_service = historical_service
    app.state.quality_service = quality_service
    app.state.range_mover_service = range_mover_service
    app.state.move_event_service = move_event_service
    app.state.nse_import_service = nse_import_service
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Swing Trading App", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_token_service_dep() -> TokenService:
    return app.state.token_service


def get_instrument_service_dep() -> InstrumentMasterService:
    return app.state.instrument_service


def get_universe_service_dep() -> IndexUniverseService:
    return app.state.universe_service


def get_historical_service_dep() -> HistoricalDataService:
    return app.state.historical_service


def get_quality_service_dep() -> DataQualityService:
    return app.state.quality_service


def get_range_mover_service_dep() -> RangeMoverService:
    return app.state.range_mover_service


def get_move_event_service_dep() -> MoveEventService:
    return app.state.move_event_service


def get_nse_import_service_dep() -> NseImportService:
    return app.state.nse_import_service


def get_settings_dep() -> Settings:
    return app.state.settings


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app="swing-trading-app")


@app.get("/api/dhan/status", response_model=TokenStatusResponse)
async def dhan_status(token_service: TokenService = Depends(get_token_service_dep)) -> TokenStatusResponse:
    return token_service.status()


@app.post("/api/dhan/status/refresh", response_model=TokenStatusResponse)
async def dhan_refresh_status(token_service: TokenService = Depends(get_token_service_dep)) -> TokenStatusResponse:
    try:
        return await token_service.refresh_profile()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dhan/token", response_model=TokenStatusResponse)
async def dhan_update_token(
    request: TokenUpdateRequest,
    token_service: TokenService = Depends(get_token_service_dep),
) -> TokenStatusResponse:
    try:
        return await token_service.save_manual_token(
            dhan_client_id=request.dhan_client_id,
            access_token=request.access_token,
            expiry_time=request.expiry_time,
            validate_with_dhan=request.validate_with_dhan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dhan/renew", response_model=RenewResponse)
async def dhan_renew(token_service: TokenService = Depends(get_token_service_dep)) -> RenewResponse:
    try:
        renewed, status, message = await token_service.renew_if_needed(force=True)
        return RenewResponse(renewed=renewed, status=status, message=message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/instruments/status", response_model=InstrumentMasterStatusResponse)
async def instrument_status(
    instrument_service: InstrumentMasterService = Depends(get_instrument_service_dep),
) -> InstrumentMasterStatusResponse:
    return InstrumentMasterStatusResponse(**instrument_service.status())


@app.post("/api/instruments/refresh", response_model=InstrumentImportSummary)
async def instrument_refresh(
    instrument_service: InstrumentMasterService = Depends(get_instrument_service_dep),
) -> InstrumentImportSummary:
    try:
        stats = await instrument_service.refresh()
        return InstrumentImportSummary(**stats.__dict__)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Instrument master refresh failed: {exc}") from exc


@app.get("/api/instruments/search", response_model=list[InstrumentSearchItem])
async def instrument_search(
    query: str = Query(min_length=1, max_length=64),
    exchange_id: str = Query(default="NSE", min_length=1, max_length=16),
    limit: int = Query(default=25, ge=1, le=100),
    instrument_service: InstrumentMasterService = Depends(get_instrument_service_dep),
) -> list[InstrumentSearchItem]:
    return [InstrumentSearchItem.model_validate(item) for item in instrument_service.search(query, exchange_id, limit)]


@app.get("/api/universe/nifty500/status", response_model=UniverseStatusResponse)
async def nifty_500_status(
    universe_service: IndexUniverseService = Depends(get_universe_service_dep),
) -> UniverseStatusResponse:
    return UniverseStatusResponse(**universe_service.nifty_500_status())


@app.post("/api/universe/nifty500/refresh", response_model=UniverseImportSummary)
async def nifty_500_refresh(
    universe_service: IndexUniverseService = Depends(get_universe_service_dep),
) -> UniverseImportSummary:
    try:
        stats = await universe_service.refresh_nifty_500()
        return UniverseImportSummary(**stats.__dict__)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Nifty 500 refresh failed: {exc}") from exc


@app.get("/api/universe/nifty500/constituents", response_model=list[UniverseConstituentItem])
async def nifty_500_constituents(
    query: str = Query(default="", max_length=64),
    limit: int = Query(default=600, ge=1, le=1000),
    universe_service: IndexUniverseService = Depends(get_universe_service_dep),
) -> list[UniverseConstituentItem]:
    return [
        UniverseConstituentItem.model_validate(item)
        for item in universe_service.nifty_500_constituents(query=query, limit=limit)
    ]


@app.get("/api/historical/nifty500/status", response_model=HistoricalFetchStatusResponse | None)
async def historical_nifty_500_status(
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
) -> HistoricalFetchStatusResponse | None:
    status = historical_service.latest_status("NIFTY_500")
    return HistoricalFetchStatusResponse(**status) if status else None


@app.post("/api/historical/nifty500/refresh", response_model=HistoricalFetchStatusResponse)
async def historical_nifty_500_refresh(
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
) -> HistoricalFetchStatusResponse:
    try:
        status = await historical_service.start_or_resume_nifty_500_fetch()
        return HistoricalFetchStatusResponse(**status)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/historical/nifty500/upward-movers/status", response_model=HistoricalFetchStatusResponse | None)
async def historical_nifty_500_upward_movers_status(
    threshold_percent: float | None = Query(default=None, ge=0.1, le=100.0),
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
    settings: Settings = Depends(get_settings_dep),
) -> HistoricalFetchStatusResponse | None:
    threshold = threshold_percent or settings.extended_history_upward_move_threshold_percent
    status = historical_service.latest_status(upward_movers_universe_name(threshold))
    return HistoricalFetchStatusResponse(**status) if status else None


@app.post("/api/historical/nifty500/upward-movers/refresh", response_model=HistoricalFetchStatusResponse)
async def historical_nifty_500_upward_movers_refresh(
    threshold_percent: float | None = Query(default=None, ge=0.1, le=100.0),
    lookback_calendar_days: int | None = Query(default=None, ge=1, le=365),
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
    range_mover_service: RangeMoverService = Depends(get_range_mover_service_dep),
    settings: Settings = Depends(get_settings_dep),
) -> HistoricalFetchStatusResponse:
    try:
        threshold = threshold_percent or settings.extended_history_upward_move_threshold_percent
        lookback_days = lookback_calendar_days or settings.extended_history_lookback_calendar_days
        report = range_mover_service.nifty_500_range_movers(threshold_percent=threshold, limit=500)
        constituent_ids = [
            int(item["index_constituent_id"])
            for item in report["items"]
            if item.get("index_constituent_id") is not None
        ]
        status = await historical_service.start_or_resume_constituent_fetch(
            universe_name=upward_movers_universe_name(threshold),
            constituent_ids=constituent_ids,
            lookback_calendar_days=lookback_days,
            source_universe_name="NIFTY_500",
        )
        return HistoricalFetchStatusResponse(**status)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/historical/nifty500/items", response_model=list[HistoricalFetchItem])
async def historical_nifty_500_items(
    run_id: int = Query(ge=1),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
) -> list[HistoricalFetchItem]:
    return [
        HistoricalFetchItem.model_validate(item)
        for item in historical_service.items(run_id=run_id, status=status, limit=limit)
    ]


@app.get("/api/historical/candles", response_model=list[DailyCandleItem])
async def historical_candles(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=80, ge=1, le=500),
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
) -> list[DailyCandleItem]:
    return [
        DailyCandleItem.model_validate(item)
        for item in historical_service.candles_for_symbol(symbol=symbol, limit=limit)
    ]


@app.get("/api/quality/nifty500/report", response_model=QualityReportResponse)
async def quality_nifty_500_report(
    status: str = Query(default="exceptions", max_length=32),
    limit: int = Query(default=200, ge=1, le=500),
    quality_service: DataQualityService = Depends(get_quality_service_dep),
) -> QualityReportResponse:
    return QualityReportResponse(**quality_service.report(status_filter=status, limit=limit))


@app.get("/api/analytics/nifty500/upward-movers", response_model=RangeMoverReportResponse)
@app.get("/api/analytics/nifty500/range-movers", response_model=RangeMoverReportResponse)
async def analytics_nifty_500_upward_movers(
    threshold_percent: float = Query(default=20.0, ge=0.1, le=100.0),
    limit: int = Query(default=500, ge=1, le=500),
    range_mover_service: RangeMoverService = Depends(get_range_mover_service_dep),
) -> RangeMoverReportResponse:
    return RangeMoverReportResponse(
        **range_mover_service.nifty_500_range_movers(threshold_percent=threshold_percent, limit=limit)
    )


@app.get("/api/research/nifty500/move-events", response_model=MoveEventReportResponse | None)
async def research_nifty_500_move_events(
    bucket: str = Query(default="", max_length=16),
    limit: int = Query(default=500, ge=1, le=1000),
    move_event_service: MoveEventService = Depends(get_move_event_service_dep),
) -> MoveEventReportResponse | None:
    report = move_event_service.latest_nifty_500_report(bucket=bucket, limit=limit)
    return MoveEventReportResponse(**report) if report else None


@app.post("/api/research/nifty500/move-events/refresh", response_model=MoveEventReportResponse)
async def research_nifty_500_move_events_refresh(
    threshold_percent: float = Query(default=10.0, ge=0.1, le=100.0),
    pullback_percent: float = Query(default=5.0, ge=0.1, le=50.0),
    move_event_service: MoveEventService = Depends(get_move_event_service_dep),
) -> MoveEventReportResponse:
    try:
        return MoveEventReportResponse(
            **move_event_service.refresh_nifty_500_events(
                threshold_percent=threshold_percent,
                pullback_percent=pullback_percent,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/nse/import/upload", response_model=NseImportUploadResponse)
async def nse_import_upload(
    files: list[UploadFile] = File(...),
    nse_service: NseImportService = Depends(get_nse_import_service_dep),
) -> NseImportUploadResponse:
    try:
        payload = [(file.filename or "upload", await file.read()) for file in files]
        return NseImportUploadResponse(**nse_service.import_files(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NSE import failed: {exc}") from exc


@app.post("/api/nse/import/scan", response_model=NseImportUploadResponse)
async def nse_import_scan(
    nse_service: NseImportService = Depends(get_nse_import_service_dep),
) -> NseImportUploadResponse:
    try:
        return NseImportUploadResponse(**nse_service.import_inbox())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NSE inbox import failed: {exc}") from exc


@app.get("/api/nse/import/status", response_model=NseImportStatusResponse)
async def nse_import_status(
    nse_service: NseImportService = Depends(get_nse_import_service_dep),
) -> NseImportStatusResponse:
    return NseImportStatusResponse(**nse_service.status())


@app.get("/api/nse/eod/coverage", response_model=NseEodCoverageResponse)
async def nse_eod_coverage(
    nse_service: NseImportService = Depends(get_nse_import_service_dep),
) -> NseEodCoverageResponse:
    return NseEodCoverageResponse(**nse_service.coverage())


@app.get("/api/nse/eod/rows", response_model=list[NseEodRowItem])
async def nse_eod_rows(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=80, ge=1, le=500),
    nse_service: NseImportService = Depends(get_nse_import_service_dep),
) -> list[NseEodRowItem]:
    return [NseEodRowItem.model_validate(item) for item in nse_service.rows_for_symbol(symbol, limit)]
