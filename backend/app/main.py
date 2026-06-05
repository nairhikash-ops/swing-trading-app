from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.candlesticks import CandlestickService
from app.config import Settings, get_settings
from app.data_maintenance import DataMaintenanceScheduler
from app.data_quality import DataQualityService
from app.demo_automation import DemoAutomationService
from app.demo_trading import DemoTradingService
from app.discipline import AlgoDisciplineReviewService
from app.drishti import DrishtiSignalService
from app.historical_data import HistoricalDataService, HistoricalDataStore, upward_movers_universe_name
from app.index_universe import IndexUniverseService, IndexUniverseStore
from app.instrument_master import InstrumentMasterService, InstrumentMasterStore
from app.learning import LearningStore
from app.move_events import MoveEventService
from app.range_movers import RangeMoverService
from app.regime import StockRegimeService
from app.support_resistance import SupportResistanceService
from app.trading_journal import TradingJournalStore
from app.schemas import (
    AiSignalReviewResponse,
    CandlestickReportResponse,
    DailyCandleItem,
    DemoAccountSummary,
    DemoAutomationRunResponse,
    DemoJournalItem,
    DemoJournalNotesUpdateRequest,
    DemoJournalResponse,
    DemoLedgerResetResponse,
    DemoOrderCreateResponse,
    DemoOrderFromSignalRequest,
    DemoOrderItem,
    DemoPositionItem,
    DemoRefreshResponse,
    DrishtiSignalReportResponse,
    HealthResponse,
    HistoricalFetchItem,
    HistoricalFetchStatusResponse,
    InstrumentImportSummary,
    InstrumentMasterStatusResponse,
    InstrumentSearchItem,
    LearningDecisionSnapshotItem,
    LearningStatusResponse,
    LearningTradeOutcomeItem,
    MoveEventReportResponse,
    Nifty500NearSupportItem,
    QualityReportResponse,
    RangeMoverReportResponse,
    RenewResponse,
    StockRegimeItem,
    StockRegimeReportResponse,
    SupportResistanceReportResponse,
    TokenStatusResponse,
    TokenUpdateRequest,
    UniverseConstituentItem,
    UniverseImportSummary,
    UniverseStatusResponse,
    WatchlistCandidateItem,
    WatchlistMonitorResponse,
)
from app.scheduler import RenewalScheduler
from app.store import TokenStore
from app.token_service import TokenService
from app.watchlist import WatchlistService


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


def build_drishti_signal_service(settings: Settings) -> DrishtiSignalService:
    return DrishtiSignalService(settings=settings, token_store=TokenStore(settings.database_path))


def build_demo_trading_service(settings: Settings) -> DemoTradingService:
    return DemoTradingService(settings=settings, token_store=TokenStore(settings.database_path))


def build_algo_discipline_review_service(settings: Settings) -> AlgoDisciplineReviewService:
    return AlgoDisciplineReviewService(settings=settings, token_store=TokenStore(settings.database_path))


def build_demo_automation_service(
    settings: Settings,
    drishti_signal_service: DrishtiSignalService,
    demo_trading_service: DemoTradingService,
) -> DemoAutomationService:
    return DemoAutomationService(
        settings=settings,
        token_store=TokenStore(settings.database_path),
        drishti_signal_service=drishti_signal_service,
        demo_trading_service=demo_trading_service,
    )


def build_learning_store(settings: Settings) -> LearningStore:
    return LearningStore(TokenStore(settings.database_path))


def build_trading_journal_store(settings: Settings) -> TradingJournalStore:
    return TradingJournalStore(TokenStore(settings.database_path))


def build_watchlist_service(settings: Settings, demo_trading_service: DemoTradingService) -> WatchlistService:
    return WatchlistService(settings, TokenStore(settings.database_path), demo_trading_service)


def build_regime_service(settings: Settings) -> StockRegimeService:
    return StockRegimeService(TokenStore(settings.database_path))


def build_support_resistance_service(settings: Settings) -> SupportResistanceService:
    return SupportResistanceService(TokenStore(settings.database_path))


def build_candlestick_service(settings: Settings) -> CandlestickService:
    return CandlestickService(TokenStore(settings.database_path))


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
    drishti_signal_service = build_drishti_signal_service(settings)
    demo_trading_service = build_demo_trading_service(settings)
    algo_discipline_review_service = build_algo_discipline_review_service(settings)
    demo_automation_service = build_demo_automation_service(
        settings,
        drishti_signal_service,
        demo_trading_service,
    )
    learning_store = build_learning_store(settings)
    trading_journal_store = build_trading_journal_store(settings)
    watchlist_service = build_watchlist_service(settings, demo_trading_service)
    regime_service = build_regime_service(settings)
    support_resistance_service = build_support_resistance_service(settings)
    candlestick_service = build_candlestick_service(settings)
    renewal_scheduler = RenewalScheduler(settings, token_service)
    data_maintenance_scheduler = DataMaintenanceScheduler(
        settings,
        token_service,
        historical_service,
        regime_service,
        demo_automation_service,
    )
    app.state.settings = settings
    app.state.token_service = token_service
    app.state.instrument_service = instrument_service
    app.state.universe_service = universe_service
    app.state.historical_service = historical_service
    app.state.quality_service = quality_service
    app.state.range_mover_service = range_mover_service
    app.state.move_event_service = move_event_service
    app.state.drishti_signal_service = drishti_signal_service
    app.state.demo_trading_service = demo_trading_service
    app.state.algo_discipline_review_service = algo_discipline_review_service
    app.state.demo_automation_service = demo_automation_service
    app.state.learning_store = learning_store
    app.state.trading_journal_store = trading_journal_store
    app.state.watchlist_service = watchlist_service
    app.state.regime_service = regime_service
    app.state.support_resistance_service = support_resistance_service
    app.state.candlestick_service = candlestick_service
    renewal_scheduler.start()
    data_maintenance_scheduler.start()
    try:
        yield
    finally:
        await data_maintenance_scheduler.stop()
        await renewal_scheduler.stop()


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


def get_drishti_signal_service_dep() -> DrishtiSignalService:
    return app.state.drishti_signal_service


def get_demo_trading_service_dep() -> DemoTradingService:
    return app.state.demo_trading_service


def get_algo_discipline_review_service_dep() -> AlgoDisciplineReviewService:
    return app.state.algo_discipline_review_service


def get_demo_automation_service_dep() -> DemoAutomationService:
    return app.state.demo_automation_service


def get_learning_store_dep() -> LearningStore:
    return app.state.learning_store


def get_trading_journal_store_dep() -> TradingJournalStore:
    return app.state.trading_journal_store


def get_watchlist_service_dep() -> WatchlistService:
    return app.state.watchlist_service


def get_regime_service_dep() -> StockRegimeService:
    return app.state.regime_service


def get_support_resistance_service_dep() -> SupportResistanceService:
    return app.state.support_resistance_service


def get_candlestick_service_dep() -> CandlestickService:
    return app.state.candlestick_service


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


@app.get("/api/algo/reviews/drishti-hit/{hit_id}", response_model=AiSignalReviewResponse | None)
async def algo_review_for_drishti_hit(
    hit_id: int,
    algo_discipline_review_service: AlgoDisciplineReviewService = Depends(get_algo_discipline_review_service_dep),
) -> AiSignalReviewResponse | None:
    review = algo_discipline_review_service.latest_review_for_hit(hit_id)
    return AiSignalReviewResponse(**review) if review else None


@app.post("/api/algo/reviews/drishti-hit/{hit_id}", response_model=AiSignalReviewResponse)
async def algo_review_drishti_hit(
    hit_id: int,
    algo_discipline_review_service: AlgoDisciplineReviewService = Depends(get_algo_discipline_review_service_dep),
) -> AiSignalReviewResponse:
    try:
        return AiSignalReviewResponse(**(await algo_discipline_review_service.review_drishti_hit(hit_id)))
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
    threshold_percent: float | None = Query(default=None, ge=10.0, le=100.0),
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
    settings: Settings = Depends(get_settings_dep),
) -> HistoricalFetchStatusResponse | None:
    threshold = threshold_percent or settings.extended_history_upward_move_threshold_percent
    status = historical_service.latest_status(upward_movers_universe_name(threshold))
    return HistoricalFetchStatusResponse(**status) if status else None


@app.post("/api/historical/nifty500/upward-movers/refresh", response_model=HistoricalFetchStatusResponse)
async def historical_nifty_500_upward_movers_refresh(
    threshold_percent: float | None = Query(default=None, ge=10.0, le=100.0),
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
    threshold_percent: float = Query(default=20.0, ge=10.0, le=100.0),
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


@app.get("/api/drishti/nifty500/signals/local-low-reversal", response_model=DrishtiSignalReportResponse | None)
async def drishti_nifty_500_local_low_reversal(
    limit: int = Query(default=500, ge=1, le=1000),
    drishti_signal_service: DrishtiSignalService = Depends(get_drishti_signal_service_dep),
) -> DrishtiSignalReportResponse | None:
    report = drishti_signal_service.latest_nifty_500_signal_01_report(limit=limit)
    return DrishtiSignalReportResponse(**report) if report else None


@app.post("/api/drishti/nifty500/signals/local-low-reversal/refresh", response_model=DrishtiSignalReportResponse)
async def drishti_nifty_500_local_low_reversal_refresh(
    lookback_sessions: int = Query(default=45, ge=20, le=90),
    volume_sma_sessions: int = Query(default=20, ge=5, le=60),
    min_volume_ratio_1d: float = Query(default=1.2, ge=1.0, le=10.0),
    min_volume_vs_sma: float = Query(default=1.0, ge=0.1, le=10.0),
    drishti_signal_service: DrishtiSignalService = Depends(get_drishti_signal_service_dep),
) -> DrishtiSignalReportResponse:
    try:
        return DrishtiSignalReportResponse(
            **drishti_signal_service.refresh_nifty_500_signal_01(
                lookback_sessions=lookback_sessions,
                volume_sma_sessions=volume_sma_sessions,
                min_volume_ratio_1d=min_volume_ratio_1d,
                min_volume_vs_sma=min_volume_vs_sma,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/regimes/nifty500/latest", response_model=StockRegimeReportResponse | None)
async def regimes_nifty_500_latest(
    regime: str | None = Query(default=None, max_length=32),
    query: str = Query(default="", max_length=64),
    limit: int = Query(default=500, ge=1, le=1000),
    regime_service: StockRegimeService = Depends(get_regime_service_dep),
) -> StockRegimeReportResponse | None:
    report = regime_service.latest_nifty_500_regimes(regime=regime, query=query, limit=limit)
    return StockRegimeReportResponse(**report) if report else None


@app.post("/api/regimes/nifty500/refresh", response_model=StockRegimeReportResponse)
async def regimes_nifty_500_refresh(
    regime_service: StockRegimeService = Depends(get_regime_service_dep),
) -> StockRegimeReportResponse:
    try:
        return StockRegimeReportResponse(**regime_service.refresh_nifty_500_regimes())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/regimes/nifty500/history", response_model=list[StockRegimeItem])
async def regimes_nifty_500_history(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=365, ge=1, le=365),
    regime_service: StockRegimeService = Depends(get_regime_service_dep),
) -> list[StockRegimeItem]:
    return [
        StockRegimeItem.model_validate(item)
        for item in regime_service.history_for_symbol(symbol=symbol, limit=limit)
    ]


@app.get("/api/technical/support-resistance", response_model=SupportResistanceReportResponse)
async def technical_support_resistance(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=365, ge=20, le=365),
    support_resistance_service: SupportResistanceService = Depends(get_support_resistance_service_dep),
) -> SupportResistanceReportResponse:
    return SupportResistanceReportResponse(
        **support_resistance_service.report_for_symbol(symbol=symbol, limit=limit)
    )


@app.get("/api/technical/support-resistance/nifty500/near-support", response_model=list[Nifty500NearSupportItem])
async def technical_support_resistance_nifty500_near_support(
    limit: int = Query(default=500, ge=1, le=500),
    max_distance_percent: float = Query(default=2.0, ge=0.0, le=20.0),
    support_resistance_service: SupportResistanceService = Depends(get_support_resistance_service_dep),
) -> list[Nifty500NearSupportItem]:
    return [
        Nifty500NearSupportItem.model_validate(item)
        for item in support_resistance_service.nifty_500_near_support(
            limit=limit,
            max_distance_percent=max_distance_percent,
        )
    ]


@app.get("/api/technical/candlesticks", response_model=CandlestickReportResponse)
async def technical_candlesticks(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=120, ge=5, le=365),
    candlestick_service: CandlestickService = Depends(get_candlestick_service_dep),
) -> CandlestickReportResponse:
    return CandlestickReportResponse(**candlestick_service.report_for_symbol(symbol=symbol, limit=limit))


@app.get("/api/demo/summary", response_model=DemoAccountSummary)
async def demo_summary(
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> DemoAccountSummary:
    return DemoAccountSummary(**demo_trading_service.summary())


@app.get("/api/demo/orders", response_model=list[DemoOrderItem])
async def demo_orders(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> list[DemoOrderItem]:
    return [DemoOrderItem.model_validate(item) for item in demo_trading_service.orders(status=status, limit=limit)]


@app.get("/api/demo/positions", response_model=list[DemoPositionItem])
async def demo_positions(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> list[DemoPositionItem]:
    return [DemoPositionItem.model_validate(item) for item in demo_trading_service.positions(status=status, limit=limit)]


@app.post("/api/demo/refresh", response_model=DemoRefreshResponse)
async def demo_refresh(
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> DemoRefreshResponse:
    return DemoRefreshResponse(**demo_trading_service.refresh())


@app.post("/api/demo/reset", response_model=DemoLedgerResetResponse)
async def demo_reset(
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> DemoLedgerResetResponse:
    return DemoLedgerResetResponse(**demo_trading_service.reset_ledger())


@app.get("/api/demo/automation/status", response_model=DemoAutomationRunResponse | None)
async def demo_automation_status(
    demo_automation_service: DemoAutomationService = Depends(get_demo_automation_service_dep),
) -> DemoAutomationRunResponse | None:
    status = demo_automation_service.latest_status()
    return DemoAutomationRunResponse(**status) if status else None


@app.post("/api/demo/automation/run", response_model=DemoAutomationRunResponse)
async def demo_automation_run(
    historical_service: HistoricalDataService = Depends(get_historical_service_dep),
    demo_automation_service: DemoAutomationService = Depends(get_demo_automation_service_dep),
) -> DemoAutomationRunResponse:
    status = historical_service.latest_status("NIFTY_500")
    return DemoAutomationRunResponse(**(await demo_automation_service.run_once(status)))


@app.post("/api/demo/orders/from-drishti-hit/{hit_id}", response_model=DemoOrderCreateResponse)
async def demo_order_from_drishti_hit(
    hit_id: int,
    request: DemoOrderFromSignalRequest | None = None,
    demo_trading_service: DemoTradingService = Depends(get_demo_trading_service_dep),
) -> DemoOrderCreateResponse:
    try:
        return DemoOrderCreateResponse(
            **demo_trading_service.place_order_from_drishti_hit(
                hit_id=hit_id,
                quantity=request.quantity if request else None,
                risk_reward=request.risk_reward if request else None,
                stop_loss=request.stop_loss if request else None,
                target_price=request.target_price if request else None,
                entry_low=request.entry_low if request else None,
                entry_high=request.entry_high if request else None,
                trailing_stop_loss=request.trailing_stop_loss if request else None,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/watchlist/candidates", response_model=list[WatchlistCandidateItem])
async def watchlist_candidates(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    watchlist_service: WatchlistService = Depends(get_watchlist_service_dep),
) -> list[WatchlistCandidateItem]:
    return [WatchlistCandidateItem.model_validate(item) for item in watchlist_service.latest(status=status, limit=limit)]


@app.post("/api/watchlist/monitor", response_model=WatchlistMonitorResponse)
async def watchlist_monitor(
    watchlist_service: WatchlistService = Depends(get_watchlist_service_dep),
) -> WatchlistMonitorResponse:
    return WatchlistMonitorResponse(**watchlist_service.monitor_entries())


@app.get("/api/demo/journal", response_model=DemoJournalResponse)
async def demo_journal(
    status: str = Query(default="", max_length=32),
    symbol: str = Query(default="", max_length=64),
    limit: int = Query(default=200, ge=1, le=500),
    trading_journal_store: TradingJournalStore = Depends(get_trading_journal_store_dep),
) -> DemoJournalResponse:
    return DemoJournalResponse(**trading_journal_store.journal(status=status, symbol=symbol, limit=limit))


@app.post("/api/demo/journal/{order_id}/notes", response_model=DemoJournalItem)
async def demo_journal_notes_update(
    order_id: int,
    request: DemoJournalNotesUpdateRequest,
    trading_journal_store: TradingJournalStore = Depends(get_trading_journal_store_dep),
) -> DemoJournalItem:
    try:
        return DemoJournalItem.model_validate(
            trading_journal_store.upsert_notes(
                order_id=order_id,
                setup_notes=request.setup_notes,
                management_notes=request.management_notes,
                mistake_notes=request.mistake_notes,
                tags=request.tags,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/learning/status", response_model=LearningStatusResponse)
async def learning_status(
    learning_store: LearningStore = Depends(get_learning_store_dep),
) -> LearningStatusResponse:
    return LearningStatusResponse(**learning_store.status())


@app.get("/api/learning/snapshots", response_model=list[LearningDecisionSnapshotItem])
async def learning_snapshots(
    limit: int = Query(default=100, ge=1, le=500),
    learning_store: LearningStore = Depends(get_learning_store_dep),
) -> list[LearningDecisionSnapshotItem]:
    return [LearningDecisionSnapshotItem.model_validate(item) for item in learning_store.latest_snapshots(limit=limit)]


@app.get("/api/learning/trade-outcomes", response_model=list[LearningTradeOutcomeItem])
async def learning_trade_outcomes(
    limit: int = Query(default=100, ge=1, le=500),
    learning_store: LearningStore = Depends(get_learning_store_dep),
) -> list[LearningTradeOutcomeItem]:
    return [LearningTradeOutcomeItem.model_validate(item) for item in learning_store.latest_trade_outcomes(limit=limit)]
