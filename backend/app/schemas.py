from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TokenState = Literal["missing", "active", "expiring_soon", "expired", "renew_failed", "config_error", "unknown"]


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
    anchor_regime: str
    anchor_regime_confidence: float
    anchor_sma_50: float
    anchor_sma_50_slope_10d_percent: float
    anchor_range_position: float
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


class StockRegimeItem(BaseModel):
    instrument_id: int
    trading_date: str
    run_id: int
    index_constituent_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    regime: Literal["UPTREND", "DOWNTREND", "SIDEWAYS"]
    confidence: float
    close: float
    sma_50: float
    sma_50_slope_10d_percent: float
    low_45: float
    high_45: float
    range_position: float
    reason: dict
    created_at: datetime
    updated_at: datetime


class StockRegimeReportResponse(BaseModel):
    run_id: int | None = None
    universe_name: str
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    scanned_symbols: int
    classified_count: int
    uptrend_count: int
    downtrend_count: int
    sideways_count: int
    error: str
    generated_at: datetime
    items: list[StockRegimeItem]


class SupportResistancePivotTouchItem(BaseModel):
    price: float
    date: str
    index: int
    confirmed_index: int
    confirmed_date: str
    volume: float
    source: str


class SupportResistanceLevelItem(BaseModel):
    price: float
    mid_price: float
    zone_low: float
    zone_high: float
    zone_width: float
    role: Literal["support", "resistance"]
    inside_zone: bool
    touch_count: int
    first_touch_date: str
    last_touch_date: str
    recency_sessions: int
    distance_percent: float
    strength: float
    sources: list[str]
    touches: list[SupportResistancePivotTouchItem] = Field(default_factory=list)


class SupportResistanceReportResponse(BaseModel):
    symbol: str
    instrument_id: int | None = None
    security_id: str
    isin: str
    display_name: str
    status: str
    generated_at: datetime
    candle_count: int
    latest_date: str
    latest_close: float
    atr_14: float
    pivot_left: int
    pivot_right: int
    cluster_tolerance_percent: float
    zone_percent: float
    zone_atr_multiplier: float
    nearest_support: SupportResistanceLevelItem | None = None
    nearest_resistance: SupportResistanceLevelItem | None = None
    supports: list[SupportResistanceLevelItem]
    resistances: list[SupportResistanceLevelItem]
    near_support: bool
    inside_support_zone: bool
    support_distance_percent: float | None = None
    support_zone_state: Literal[
        "no_support",
        "above_support",
        "near_support",
        "inside_support_zone",
        "below_support_broken",
    ]
    support_reclaim: bool
    broke_below_support_recently: bool
    reclaimed_support_on_latest_close: bool


class Nifty500NearSupportItem(BaseModel):
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    latest_date: str
    latest_close: float
    nearest_support: SupportResistanceLevelItem
    support_distance_percent: float
    inside_support_zone: bool
    near_support: bool
    support_zone_state: Literal["near_support", "inside_support_zone"]
    support_reclaim: bool
    broke_below_support_recently: bool
    reclaimed_support_on_latest_close: bool


class ReversalOpportunityItem(BaseModel):
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    latest_date: str
    latest_close: float
    regime: Literal["DOWNTREND"]
    regime_confidence: float
    opportunity_stage: Literal[
        "downtrend_only",
        "near_support",
        "indecision_near_support",
        "support_reclaim",
        "bullish_reversal_watch",
        "confirmed_reversal",
        "entry_watch",
        "ignore",
    ]
    opportunity_score: float
    entry_quality_score: float
    reasons: list[str]
    near_support: bool
    inside_support_zone: bool
    support_reclaim: bool
    quality_support_reclaim: bool
    support_distance_percent: float | None = None
    nearest_support: SupportResistanceLevelItem | None = None
    support_strength: float | None = None
    support_touch_count: int | None = None
    support_recency_sessions: int | None = None
    latest_patterns: list[str]
    latest_reversal_patterns: list[str]
    recent_patterns: list[str]
    recent_reversal_patterns: list[str]
    recent_indecision_date: str | None = None
    recent_reversal_date: str | None = None
    bullish_reversal_source_date: str | None = None
    confirmation_source: str | None = None
    indecision_score: float
    reversal_score: float
    reversal_bias: Literal["bullish", "bearish", "mixed", "none"]
    suggested_next_action: Literal[
        "watch_only",
        "wait_for_confirmation",
        "wait_for_breakout",
        "wait_for_pullback",
        "ready_for_drishti_review",
        "ignore",
    ]


class ReversalOpportunitySnapshotItem(BaseModel):
    id: int
    run_id: int
    instrument_id: int
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    signal_date: str
    latest_close: float
    regime: Literal["DOWNTREND"]
    regime_confidence: float
    opportunity_stage: Literal[
        "downtrend_only",
        "near_support",
        "indecision_near_support",
        "support_reclaim",
        "bullish_reversal_watch",
        "confirmed_reversal",
        "entry_watch",
        "ignore",
    ]
    opportunity_score: float
    entry_quality_score: float
    suggested_next_action: Literal[
        "watch_only",
        "wait_for_confirmation",
        "wait_for_breakout",
        "wait_for_pullback",
        "ready_for_drishti_review",
        "ignore",
    ]
    near_support: bool
    inside_support_zone: bool
    support_reclaim: bool
    quality_support_reclaim: bool
    support_distance_percent: float | None = None
    support_strength: float | None = None
    support_touch_count: int | None = None
    support_recency_sessions: int | None = None
    indecision_score: float
    reversal_score: float
    reversal_bias: Literal["bullish", "bearish", "mixed", "none"]
    recent_indecision_date: str | None = None
    recent_reversal_date: str | None = None
    bullish_reversal_source_date: str | None = None
    confirmation_source: str | None = None
    reasons: list[str]
    latest_patterns: list[str]
    latest_reversal_patterns: list[str]
    recent_patterns: list[str]
    recent_reversal_patterns: list[str]
    nearest_support: dict[str, Any] | None = None
    outcome_1d_return_percent: float | None = None
    outcome_3d_return_percent: float | None = None
    outcome_5d_return_percent: float | None = None
    outcome_10d_return_percent: float | None = None
    max_favorable_10d_percent: float | None = None
    max_adverse_10d_percent: float | None = None
    support_broken_10d: bool | None = None
    outcome_status: Literal["pending", "partial", "complete", "not_enough_future_candles"]
    outcome_checked_at: datetime | None = None


class ReversalOpportunityRunResponse(BaseModel):
    id: int
    universe_name: str
    run_date: str
    generated_at: datetime
    min_score: float
    min_entry_quality_score: float
    include_watch_only: bool
    limit: int
    item_count: int
    run_type: str = "live"
    source: str = "manual"
    items: list[ReversalOpportunitySnapshotItem]


class ReversalOpportunityOutcomeRefreshResponse(BaseModel):
    checked_count: int
    updated_count: int
    complete_count: int
    partial_count: int
    not_enough_future_candles_count: int
    generated_at: datetime
    items: list[ReversalOpportunitySnapshotItem]


class ReversalOpportunityBackfillGroupSummary(BaseModel):
    group: str
    count: int
    average_1d_return_percent: float | None = None
    average_3d_return_percent: float | None = None
    average_5d_return_percent: float | None = None
    average_10d_return_percent: float | None = None
    average_max_favorable_10d_percent: float | None = None
    average_max_adverse_10d_percent: float | None = None
    support_broken_rate: float


class ReversalOpportunityBackfillResponse(BaseModel):
    run_count: int
    run_ids: list[int]
    item_count: int
    complete_count: int
    partial_count: int
    not_enough_future_candles_count: int
    date_range: dict[str, str | None]
    sample_every_n_sessions: int
    min_entry_quality_score: float
    stage_summary: list[ReversalOpportunityBackfillGroupSummary]
    entry_quality_summary: list[ReversalOpportunityBackfillGroupSummary]


class ReversalOpportunityPromotionItem(BaseModel):
    radar_item_id: int
    run_id: int
    symbol: str
    opportunity_stage: Literal[
        "confirmed_reversal",
        "support_reclaim",
        "bullish_reversal_watch",
        "indecision_near_support",
        "downtrend_only",
        "near_support",
        "entry_watch",
        "ignore",
    ]
    entry_quality_score: float
    opportunity_score: float
    suggested_next_action: Literal[
        "watch_only",
        "wait_for_confirmation",
        "wait_for_breakout",
        "wait_for_pullback",
        "ready_for_drishti_review",
        "ignore",
    ]
    status: Literal[
        "eligible",
        "promoted",
        "duplicate",
        "ineligible_low_score",
        "ineligible_stage",
        "ineligible_action",
        "error",
    ]
    reason: str
    watchlist_candidate_id: int | None = None
    source_signal_hit_id: int | None = None


class ReversalOpportunityPromotionResponse(BaseModel):
    run_id: int | None = None
    dry_run: bool
    min_entry_quality_score: float
    scanned_count: int
    eligible_count: int
    promoted_count: int
    skipped_duplicate_count: int
    skipped_ineligible_count: int
    items: list[ReversalOpportunityPromotionItem]


class CandlestickItem(BaseModel):
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    direction: Literal["green", "red", "flat"]
    body_percent: float
    upper_wick_percent: float
    lower_wick_percent: float
    range_amount: float
    setup_trend: Literal["up", "down", "sideways", "unknown"]
    patterns: list[str]
    indecision_score: float
    reversal_patterns: list[str]
    reversal_bias: Literal["bullish", "bearish", "mixed", "none"]
    reversal_score: float


class CandlestickReportResponse(BaseModel):
    symbol: str
    instrument_id: int | None = None
    security_id: str
    isin: str
    display_name: str
    status: str
    generated_at: datetime
    candle_count: int
    latest_date: str
    latest_patterns: list[str]
    latest_reversal_patterns: list[str]
    pattern_counts: dict[str, int]
    items: list[CandlestickItem]


class DemoOrderFromSignalRequest(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    risk_reward: float | None = Field(default=None, ge=1.0, le=10.0)
    stop_loss: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    entry_low: float | None = Field(default=None, gt=0)
    entry_high: float | None = Field(default=None, gt=0)
    trailing_stop_loss: float | None = Field(default=None, gt=0)


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
    decision_snapshot_id: int | None = None
    legacy_review_id: int | None = None
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
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float
    target_price: float | None = None
    trailing_stop_loss: float | None = None
    risk_reward: float
    rejection_reason: str
    created_at: datetime
    updated_at: datetime


class DemoPositionItem(BaseModel):
    id: int
    order_id: int
    source_signal_hit_id: int | None = None
    decision_snapshot_id: int | None = None
    legacy_review_id: int | None = None
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
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float
    target_price: float
    trailing_stop_loss: float | None = None
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


class DemoLedgerResetResponse(BaseModel):
    deleted_orders: int
    deleted_positions: int
    summary: DemoAccountSummary


class DemoAutomationRunResponse(BaseModel):
    id: int
    status: str
    reason: str
    historical_status: str
    historical_run_id: int | None = None
    drishti_run_id: int | None = None
    latest_trading_date: str | None = None
    fresh_hit_count: int
    algo_analyzed_count: int = 0
    reviewed_count: int
    enter_count: int
    orders_created_count: int
    skipped_count: int
    error: str
    started_at: datetime
    completed_at: datetime | None = None


class WatchlistCandidateItem(BaseModel):
    id: int
    source_signal_hit_id: int
    decision_snapshot_id: int | None = None
    analysis_review_id: int | None = None
    source_signal_id: str
    source_run_id: int | None = None
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    trigger_date: str
    status: str
    decision: str
    confidence: float
    entry_rule: str
    entry_low: float | None = None
    entry_high: float | None = None
    breakout_price: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    trailing_stop_loss: float | None = None
    risk_reward: float | None = None
    invalidation_price: float | None = None
    expires_after_date: str
    summary: str
    features: dict
    entered_order_id: int | None = None
    closed_reason: str
    last_checked_date: str | None = None
    created_at: datetime
    updated_at: datetime


class WatchlistActiveItem(BaseModel):
    watchlist_candidate_id: int
    symbol: str
    status: str
    decision: str
    source_signal_id: str
    source_type: str
    source_signal_hit_id: int
    source_run_id: int | None = None
    trigger_date: str
    last_checked_date: str | None = None
    entry_rule: str
    entry_low: float | None = None
    entry_high: float | None = None
    breakout_price: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    trailing_stop_loss: float | None = None
    invalidation_price: float | None = None
    entered_order_id: int | None = None
    demo_order_created: bool
    waiting_for: str
    invalidate_if: str
    expiry_date: str
    summary: str
    features: dict
    entry_extension_percent: float | None = None
    risk_percent_at_entry: float | None = None
    chase_guard_reason: str | None = None
    chase_guard_checked_date: str | None = None
    chase_guard_expected_entry_price: float | None = None


class WatchlistMonitorResponse(BaseModel):
    entered: list[WatchlistCandidateItem]
    expired: list[WatchlistCandidateItem]
    invalidated: list[WatchlistCandidateItem]
    waiting: list[WatchlistCandidateItem]
    skipped_entry: list[WatchlistCandidateItem] = Field(default_factory=list)


class LearningStatusResponse(BaseModel):
    decision_snapshot_count: int
    trade_outcome_count: int
    outcome_counts: dict[str, int]


class LearningDecisionSnapshotItem(BaseModel):
    id: int
    source_signal_hit_id: int
    signal_id: str
    source_run_id: int | None = None
    instrument_id: int
    symbol: str
    isin: str
    security_id: str
    trigger_date: str
    snapshot_version: int
    candle_count: int
    context: dict
    features: dict
    created_at: datetime
    updated_at: datetime


class LearningTradeOutcomeItem(BaseModel):
    id: int
    position_id: int
    order_id: int
    source_signal_hit_id: int | None = None
    decision_snapshot_id: int | None = None
    legacy_review_id: int | None = None
    instrument_id: int
    symbol: str
    isin: str
    security_id: str
    status: str
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str
    holding_sessions: int
    max_favorable_price: float | None = None
    max_favorable_percent: float | None = None
    max_adverse_price: float | None = None
    max_adverse_percent: float | None = None
    target_hit: bool
    stop_hit: bool
    time_exit: bool
    realized_pnl: float
    realized_pnl_percent: float
    outcome_label: str
    created_at: datetime
    updated_at: datetime


class DemoJournalSummary(BaseModel):
    total_trades: int
    pending_orders: int
    rejected_orders: int
    open_positions: int
    closed_positions: int
    winners: int
    failures: int
    neutral: int
    realized_pnl: float
    unrealized_pnl: float
    average_r: float
    win_rate_percent: float


class DemoJournalItem(BaseModel):
    order_id: int
    position_id: int | None = None
    source_signal_hit_id: int | None = None
    decision_snapshot_id: int | None = None
    legacy_review_id: int | None = None
    source_signal_id: str
    source_run_id: int | None = None
    instrument_id: int
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    side: str
    quantity: float
    status: str
    order_status: str
    position_status: str | None = None
    trigger_date: str
    requested_price: float
    fill_after_date: str
    filled_date: str | None = None
    filled_price: float | None = None
    entry_date: str | None = None
    entry_price: float | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float
    target_price: float | None = None
    trailing_stop_loss: float | None = None
    risk_amount: float | None = None
    risk_reward: float
    latest_candle_date: str | None = None
    latest_close: float | None = None
    holding_sessions: int
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str
    rejection_reason: str
    realized_pnl: float
    realized_pnl_percent: float
    unrealized_pnl: float
    unrealized_pnl_percent: float
    pnl: float
    pnl_percent: float
    r_multiple: float | None = None
    outcome_label: str
    max_favorable_price: float | None = None
    max_favorable_percent: float | None = None
    max_adverse_price: float | None = None
    max_adverse_percent: float | None = None
    target_hit: bool
    stop_hit: bool
    time_exit: bool
    review_provider: str | None = None
    review_model: str | None = None
    review_decision: str | None = None
    review_confidence: float | None = None
    review_summary: str
    review_wait_until: str
    review_invalidation: str
    watchlist_status: str | None = None
    watchlist_decision: str | None = None
    watchlist_entry_rule: str | None = None
    watchlist_summary: str
    setup_notes: str
    management_notes: str
    mistake_notes: str
    tags: list[str]
    notes_updated_at: datetime | None = None
    order_created_at: datetime
    order_updated_at: datetime


class DemoJournalResponse(BaseModel):
    summary: DemoJournalSummary
    items: list[DemoJournalItem]


class DemoJournalNotesUpdateRequest(BaseModel):
    setup_notes: str = ""
    management_notes: str = ""
    mistake_notes: str = ""
    tags: list[str] = []
