from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TokenState = Literal["missing", "active", "expiring_soon", "expired", "renew_failed", "config_error", "unknown"]
GeminiKeyState = Literal["missing", "active", "validation_failed", "config_error", "unknown"]
AiReviewDecision = Literal["ENTER", "WAIT", "IGNORE"]
AiReviewStatus = Literal["completed", "failed"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str


class TokenUpdateRequest(BaseModel):
    dhan_client_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=20)
    expiry_time: datetime | None = None
    validate_with_dhan: bool = True


class TokenStatusResponse(BaseModel):
    state: TokenState
    has_token: bool
    dhan_client_id: str | None = None
    masked_token: str | None = None
    expiry_time: datetime | None = None
    minutes_to_expiry: int | None = None
    active_segment: str | None = None
    ddpi: str | None = None
    mtf: str | None = None
    data_plan: str | None = None
    data_validity: str | None = None
    last_status_check_at: datetime | None = None
    last_renew_attempt_at: datetime | None = None
    last_renew_success_at: datetime | None = None
    last_error: str = ""
    token_source: str | None = None


class GeminiKeyUpdateRequest(BaseModel):
    api_key: str = Field(min_length=20)
    validate_with_gemini: bool = True


class GeminiKeyStatusResponse(BaseModel):
    provider: Literal["gemini"]
    state: GeminiKeyState
    has_key: bool
    masked_key: str | None = None
    key_source: str | None = None
    last_validated_at: datetime | None = None
    last_error: str = ""
    updated_at: datetime | None = None


class AiSignalReviewResponse(BaseModel):
    id: int
    source_signal_hit_id: int
    provider: str
    model: str
    status: AiReviewStatus
    decision: AiReviewDecision
    confidence: float
    summary: str
    support_price: float | None = None
    resistance_price: float | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    trailing_stop_loss: float | None = None
    risk_reward: float | None = None
    wait_until: str
    invalidation: str
    sources: list[dict] = Field(default_factory=list)
    error: str = ""
    created_at: datetime
    updated_at: datetime


class RenewResponse(BaseModel):
    renewed: bool
    status: TokenStatusResponse
    message: str


class InstrumentImportSummary(BaseModel):
    run_id: int
    source_url: str
    exchange_filter: str
    segment_filter: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class InstrumentMasterStatusResponse(BaseModel):
    total_count: int
    active_count: int
    nse_count: int
    active_nse_count: int
    last_import: dict | None = None


class InstrumentSearchItem(BaseModel):
    id: int
    exchange_id: str
    segment: str
    security_id: str
    isin: str
    instrument: str
    symbol_name: str
    display_name: str
    instrument_type: str
    series: str
    lot_size: float | None = None
    expiry_date: str
    strike_price: float | None = None
    option_type: str
    tick_size: float | None = None
    buy_sell_indicator: str
    asm_gsm_flag: str
    mtf_leverage: str
    raw: dict


class UniverseImportSummary(BaseModel):
    run_id: int
    index_name: str
    source_url: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class UniverseStatusResponse(BaseModel):
    index_name: str
    total_count: int
    active_count: int
    industry_count: int
    last_import: dict | None = None


class UniverseConstituentItem(BaseModel):
    id: int
    index_name: str
    company_name: str
    industry: str
    symbol: str
    series: str
    isin: str
    raw: dict


class HistoricalFetchStatusResponse(BaseModel):
    id: int
    universe_name: str
    lookback_calendar_days: int
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    mapped_symbols: int
    skipped_symbols: int
    queued_count: int
    fetching_count: int
    done_count: int
    failed_count: int
    skipped_count: int
    candles_received: int
    stored_candle_count: int
    error: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class HistoricalFetchItem(BaseModel):
    id: int
    run_id: int
    index_constituent_id: int
    instrument_id: int | None = None
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    status: str
    attempts: int
    candles_received: int
    error: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class DailyCandleItem(BaseModel):
    instrument_id: int
    security_id: str
    exchange_segment: str
    instrument: str
    trading_date: str
    source_timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    source: str
    fetched_at: datetime


class QualityItem(BaseModel):
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    quality_status: str
    issues: list[str]
    latest_candle_date: str | None = None
    expected_sessions: int
    candle_count: int
    missing_sessions: int
    invalid_ohlc_count: int
    zero_volume_count: int
    negative_volume_count: int
    extreme_move_count: int
    fetch_status: str
    fetch_error: str


class QualityReportResponse(BaseModel):
    generated_at: datetime
    historical_run_id: int | None = None
    historical_run_status: str
    from_date: str
    to_date_exclusive: str
    latest_expected_session: str | None = None
    expected_session_count: int
    total_symbols: int
    healthy_count: int
    warning_count: int
    blocked_count: int
    issue_counts: dict[str, int]
    items: list[QualityItem]


class RangeMoverItem(BaseModel):
    index_constituent_id: int | None = None
    instrument_id: int | None = None
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    lowest_low: float
    lowest_low_date: str
    highest_high: float
    highest_high_date: str
    move_percent: float
    range_amount: float
    candle_count: int


class RangeMoverReportResponse(BaseModel):
    generated_at: datetime
    historical_run_id: int | None = None
    from_date: str
    to_date_exclusive: str
    threshold_percent: float
    total_scanned: int
    match_count: int
    items: list[RangeMoverItem]


class MoveEventItem(BaseModel):
    id: int
    run_id: int
    index_constituent_id: int
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    event_number: int
    bucket: str
    low_date: str
    low_price: float
    high_date: str
    high_price: float
    move_percent: float
    duration_calendar_days: int
    duration_trading_sessions: int
    threshold_percent: float
    pullback_percent: float
    split_pullback_date: str | None = None
    split_pullback_close: float | None = None
    created_at: datetime


class MoveEventReportResponse(BaseModel):
    run_id: int | None = None
    universe_name: str
    threshold_percent: float
    pullback_percent: float
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    scanned_symbols: int
    candidate_symbols: int
    event_count: int
    error: str
    generated_at: datetime
    items: list[MoveEventItem]


class DrishtiSignalHitItem(BaseModel):
    id: int
    run_id: int
    signal_id: str
    index_constituent_id: int
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    anchor_date: str
    trigger_date: str
    anchor_open: float
    anchor_high: float
    anchor_low: float
    anchor_close: float
    anchor_volume: float
    trigger_open: float
    trigger_high: float
    trigger_low: float
    trigger_close: float
    trigger_volume: float
    volume_ratio_1d: float
    volume_vs_sma: float
    close_to_anchor_high_ratio: float
    future_high: float
    future_high_date: str
    outcome_from_trigger_percent: float
    outcome_from_anchor_percent: float
    created_at: datetime


class DrishtiSignalReportResponse(BaseModel):
    run_id: int | None = None
    signal_id: str
    signal_name: str
    description: str
    universe_name: str
    lookback_sessions: int
    volume_sma_sessions: int
    min_volume_ratio_1d: float
    min_volume_vs_sma: float
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    scanned_symbols: int
    hit_count: int
    outcome_ge_10_count: int
    outcome_ge_20_count: int
    error: str
    generated_at: datetime
    items: list[DrishtiSignalHitItem]


class DemoOrderFromSignalRequest(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    risk_reward: float | None = Field(default=None, ge=1.0, le=10.0)


class DemoAccountSummary(BaseModel):
    currency: str
    cash_balance: float
    realized_pnl: float
    unrealized_pnl: float
    open_market_value: float
    equity_value: float
    pending_orders: int
    filled_orders: int
    rejected_orders: int
    open_positions: int
    closed_positions: int
    updated_at: datetime


class DemoOrderItem(BaseModel):
    id: int
    source_signal_hit_id: int | None = None
    source_signal_id: str
    source_run_id: int | None = None
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    side: str
    quantity: float
    order_type: str
    status: str
    trigger_date: str
    requested_price: float
    fill_after_date: str
    filled_date: str | None = None
    filled_price: float | None = None
    stop_loss: float
    target_price: float | None = None
    risk_reward: float
    rejection_reason: str
    created_at: datetime
    updated_at: datetime


class DemoPositionItem(BaseModel):
    id: int
    order_id: int
    source_signal_hit_id: int | None = None
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    side: str
    quantity: float
    entry_date: str
    entry_price: float
    stop_loss: float
    target_price: float
    risk_amount: float
    risk_reward: float
    status: str
    latest_candle_date: str | None = None
    latest_close: float | None = None
    holding_sessions: int
    unrealized_pnl: float
    unrealized_pnl_percent: float
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str
    realized_pnl: float
    realized_pnl_percent: float
    created_at: datetime
    updated_at: datetime


class DemoOrderCreateResponse(BaseModel):
    order: DemoOrderItem
    position: DemoPositionItem | None = None
    summary: DemoAccountSummary


class DemoRefreshResponse(BaseModel):
    filled_orders: list[DemoOrderItem]
    rejected_orders: list[DemoOrderItem]
    updated_positions: list[DemoPositionItem]
    closed_positions: list[DemoPositionItem]
    summary: DemoAccountSummary
