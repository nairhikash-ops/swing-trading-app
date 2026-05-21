import { StrictMode, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
  Radar,
  RefreshCcw,
  Save,
  Search,
  Shield,
  TrendingUp,
  Wifi,
} from "lucide-react";
import "./styles.css";

type TokenState =
  | "missing"
  | "active"
  | "expiring_soon"
  | "expired"
  | "renew_failed"
  | "config_error"
  | "unknown";

type AppPage = "dashboard" | "drishti" | "demo" | "data" | "settings";

type TokenStatus = {
  state: TokenState;
  has_token: boolean;
  dhan_client_id?: string | null;
  masked_token?: string | null;
  expiry_time?: string | null;
  minutes_to_expiry?: number | null;
  active_segment?: string | null;
  ddpi?: string | null;
  mtf?: string | null;
  data_plan?: string | null;
  data_validity?: string | null;
  last_status_check_at?: string | null;
  last_renew_attempt_at?: string | null;
  last_renew_success_at?: string | null;
  last_error: string;
  token_source?: string | null;
};

type GeminiKeyStatus = {
  provider: "gemini";
  state: "missing" | "active" | "validation_failed" | "config_error" | "unknown";
  has_key: boolean;
  masked_key?: string | null;
  key_source?: string | null;
  last_validated_at?: string | null;
  last_error: string;
  updated_at?: string | null;
};

type RenewResponse = {
  renewed: boolean;
  status: TokenStatus;
  message: string;
};

type InstrumentStatus = {
  total_count: number;
  active_count: number;
  nse_count: number;
  active_nse_count: number;
  last_import?: {
    id: number;
    source_url: string;
    source_columns_json: string;
    total_rows_seen: number;
    imported_rows: number;
    inserted_rows: number;
    updated_rows: number;
    unchanged_rows: number;
    deactivated_rows: number;
    completed_at?: string | null;
    error: string;
  } | null;
};

type InstrumentItem = {
  id: number;
  exchange_id: string;
  segment: string;
  security_id: string;
  isin: string;
  instrument: string;
  symbol_name: string;
  display_name: string;
  instrument_type: string;
  series: string;
  lot_size?: number | null;
  expiry_date: string;
  strike_price?: number | null;
  option_type: string;
  tick_size?: number | null;
  buy_sell_indicator: string;
  asm_gsm_flag: string;
  mtf_leverage: string;
};

type UniverseStatus = {
  index_name: string;
  total_count: number;
  active_count: number;
  industry_count: number;
  last_import?: {
    id: number;
    source_url: string;
    source_columns_json: string;
    total_rows_seen: number;
    imported_rows: number;
    inserted_rows: number;
    updated_rows: number;
    unchanged_rows: number;
    deactivated_rows: number;
    completed_at?: string | null;
    error: string;
  } | null;
};

type UniverseItem = {
  id: number;
  index_name: string;
  company_name: string;
  industry: string;
  symbol: string;
  series: string;
  isin: string;
  raw: Record<string, string>;
};

type HistoricalStatus = {
  id: number;
  universe_name: string;
  lookback_calendar_days: number;
  from_date: string;
  to_date_exclusive: string;
  status: string;
  total_symbols: number;
  mapped_symbols: number;
  skipped_symbols: number;
  queued_count: number;
  fetching_count: number;
  done_count: number;
  failed_count: number;
  skipped_count: number;
  candles_received: number;
  stored_candle_count: number;
  error: string;
  started_at: string;
  updated_at: string;
  completed_at?: string | null;
};

type HistoricalItem = {
  id: number;
  run_id: number;
  company_name: string;
  industry: string;
  symbol: string;
  isin: string;
  security_id: string;
  status: string;
  attempts: number;
  candles_received: number;
  error: string;
};

type DailyCandle = {
  trading_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type QualityItem = {
  symbol: string;
  company_name: string;
  industry: string;
  isin: string;
  security_id: string;
  quality_status: "healthy" | "warning" | "blocked";
  issues: string[];
  latest_candle_date?: string | null;
  expected_sessions: number;
  candle_count: number;
  missing_sessions: number;
  invalid_ohlc_count: number;
  zero_volume_count: number;
  negative_volume_count: number;
  extreme_move_count: number;
  fetch_status: string;
  fetch_error: string;
};

type QualityReport = {
  generated_at: string;
  historical_run_id?: number | null;
  historical_run_status: string;
  from_date: string;
  to_date_exclusive: string;
  latest_expected_session?: string | null;
  expected_session_count: number;
  total_symbols: number;
  healthy_count: number;
  warning_count: number;
  blocked_count: number;
  issue_counts: Record<string, number>;
  items: QualityItem[];
};

type RangeMoverItem = {
  index_constituent_id?: number | null;
  instrument_id?: number | null;
  symbol: string;
  company_name: string;
  industry: string;
  isin: string;
  security_id: string;
  lowest_low: number;
  lowest_low_date: string;
  highest_high: number;
  highest_high_date: string;
  move_percent: number;
  range_amount: number;
  candle_count: number;
};

type RangeMoverReport = {
  generated_at: string;
  historical_run_id?: number | null;
  from_date: string;
  to_date_exclusive: string;
  threshold_percent: number;
  total_scanned: number;
  match_count: number;
  items: RangeMoverItem[];
};

type MoveEventItem = {
  id: number;
  run_id: number;
  symbol: string;
  company_name: string;
  industry: string;
  event_number: number;
  bucket: string;
  low_date: string;
  low_price: number;
  high_date: string;
  high_price: number;
  move_percent: number;
  duration_calendar_days: number;
  duration_trading_sessions: number;
  split_pullback_date?: string | null;
  split_pullback_close?: number | null;
};

type MoveEventReport = {
  run_id?: number | null;
  universe_name: string;
  threshold_percent: number;
  pullback_percent: number;
  from_date: string;
  to_date_exclusive: string;
  status: string;
  total_symbols: number;
  scanned_symbols: number;
  candidate_symbols: number;
  event_count: number;
  error: string;
  generated_at: string;
  items: MoveEventItem[];
};

type DrishtiSignalHitItem = {
  id: number;
  run_id: number;
  signal_id: string;
  symbol: string;
  company_name: string;
  industry: string;
  isin: string;
  security_id: string;
  anchor_date: string;
  trigger_date: string;
  anchor_low: number;
  anchor_high: number;
  anchor_close: number;
  anchor_volume: number;
  trigger_close: number;
  trigger_volume: number;
  volume_ratio_1d: number;
  volume_vs_sma: number;
  close_to_anchor_high_ratio: number;
  future_high: number;
  future_high_date: string;
  outcome_from_trigger_percent: number;
  outcome_from_anchor_percent: number;
};

type DrishtiSignalReport = {
  run_id?: number | null;
  signal_id: string;
  signal_name: string;
  description: string;
  universe_name: string;
  lookback_sessions: number;
  volume_sma_sessions: number;
  min_volume_ratio_1d: number;
  min_volume_vs_sma: number;
  from_date: string;
  to_date_exclusive: string;
  status: string;
  total_symbols: number;
  scanned_symbols: number;
  hit_count: number;
  outcome_ge_10_count: number;
  outcome_ge_20_count: number;
  error: string;
  generated_at: string;
  items: DrishtiSignalHitItem[];
};

type AiSignalReview = {
  id: number;
  source_signal_hit_id: number;
  provider: string;
  model: string;
  grounding_enabled: boolean;
  status: "completed" | "quota_limited" | "failed";
  decision: "ENTER" | "WAIT" | "IGNORE";
  confidence: number;
  summary: string;
  support_price?: number | null;
  resistance_price?: number | null;
  entry_low?: number | null;
  entry_high?: number | null;
  stop_loss?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  trailing_stop_loss?: number | null;
  risk_reward?: number | null;
  wait_until: string;
  invalidation: string;
  sources: { title?: string; uri?: string }[];
  error: string;
  created_at: string;
  updated_at: string;
};

type DemoSummary = {
  currency: string;
  cash_balance: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_market_value: number;
  equity_value: number;
  pending_orders: number;
  filled_orders: number;
  rejected_orders: number;
  open_positions: number;
  closed_positions: number;
  updated_at: string;
};

type DemoOrder = {
  id: number;
  source_signal_hit_id?: number | null;
  source_signal_id: string;
  source_run_id?: number | null;
  symbol: string;
  company_name: string;
  industry: string;
  security_id: string;
  side: string;
  quantity: number;
  order_type: string;
  status: string;
  trigger_date: string;
  requested_price: number;
  fill_after_date: string;
  filled_date?: string | null;
  filled_price?: number | null;
  stop_loss: number;
  target_price?: number | null;
  risk_reward: number;
  rejection_reason: string;
  created_at: string;
  updated_at: string;
};

type DemoPosition = {
  id: number;
  order_id: number;
  source_signal_hit_id?: number | null;
  symbol: string;
  company_name: string;
  industry: string;
  security_id: string;
  side: string;
  quantity: number;
  entry_date: string;
  entry_price: number;
  stop_loss: number;
  target_price: number;
  risk_amount: number;
  risk_reward: number;
  status: string;
  latest_candle_date?: string | null;
  latest_close?: number | null;
  holding_sessions: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  exit_date?: string | null;
  exit_price?: number | null;
  exit_reason: string;
  realized_pnl: number;
  realized_pnl_percent: number;
  updated_at: string;
};

type DemoOrderCreateResponse = {
  order: DemoOrder;
  position?: DemoPosition | null;
  summary: DemoSummary;
};

type DemoRefreshResponse = {
  filled_orders: DemoOrder[];
  rejected_orders: DemoOrder[];
  updated_positions: DemoPosition[];
  closed_positions: DemoPosition[];
  summary: DemoSummary;
};

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  configuredApiBaseUrl && configuredApiBaseUrl.length > 0
    ? configuredApiBaseUrl
    : `${window.location.protocol}//${window.location.hostname}:8000`;
const rangeMoverThresholdOptions = [10, 15, 20, 30, 40, 50];

function dhanTradingViewUrl(item: { symbol: string; security_id?: string | null }): string {
  const symbol = item.symbol.trim().toUpperCase();
  const params = new URLSearchParams({
    symbol: `NSE:${symbol}`,
    dhan_symbol: symbol,
    exchange: "NSE",
    segment: "E",
  });
  if (item.security_id) params.set("security_id", item.security_id);
  return `https://tv.dhan.co/?${params.toString()}`;
}

function App() {
  const [status, setStatus] = useState<TokenStatus | null>(null);
  const [geminiStatus, setGeminiStatus] = useState<GeminiKeyStatus | null>(null);
  const [instrumentStatus, setInstrumentStatus] = useState<InstrumentStatus | null>(null);
  const [instrumentResults, setInstrumentResults] = useState<InstrumentItem[]>([]);
  const [instrumentQuery, setInstrumentQuery] = useState("");
  const [universeStatus, setUniverseStatus] = useState<UniverseStatus | null>(null);
  const [universeResults, setUniverseResults] = useState<UniverseItem[]>([]);
  const [universeQuery, setUniverseQuery] = useState("");
  const [historicalStatus, setHistoricalStatus] = useState<HistoricalStatus | null>(null);
  const [historicalItems, setHistoricalItems] = useState<HistoricalItem[]>([]);
  const [candleSymbol, setCandleSymbol] = useState("RELIANCE");
  const [candles, setCandles] = useState<DailyCandle[]>([]);
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [rangeMoverReport, setRangeMoverReport] = useState<RangeMoverReport | null>(null);
  const [moveEventReport, setMoveEventReport] = useState<MoveEventReport | null>(null);
  const [drishtiReport, setDrishtiReport] = useState<DrishtiSignalReport | null>(null);
  const [aiReviewsByHit, setAiReviewsByHit] = useState<Record<number, AiSignalReview>>({});
  const [drishtiBusy, setDrishtiBusy] = useState(false);
  const [reviewingHitId, setReviewingHitId] = useState<number | null>(null);
  const [demoSummary, setDemoSummary] = useState<DemoSummary | null>(null);
  const [demoOrders, setDemoOrders] = useState<DemoOrder[]>([]);
  const [demoOpenPositions, setDemoOpenPositions] = useState<DemoPosition[]>([]);
  const [demoClosedPositions, setDemoClosedPositions] = useState<DemoPosition[]>([]);
  const [rangeMoverThreshold, setRangeMoverThreshold] = useState(20);
  const [activePage, setActivePage] = useState<AppPage>("dashboard");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    dhanClientId: "",
    accessToken: "",
    expiryTime: "",
    validateWithDhan: true,
  });
  const [geminiForm, setGeminiForm] = useState({
    apiKey: "",
    validateWithGemini: true,
  });

  const stateMeta = useMemo(() => getStateMeta(status?.state ?? "unknown"), [status?.state]);
  const geminiStateMeta = useMemo(() => getGeminiStateMeta(geminiStatus?.state ?? "unknown"), [geminiStatus?.state]);

  async function loadStatus(refresh = false) {
    setBusy(true);
    setMessage("");
    try {
      const endpoint = refresh ? "/api/dhan/status/refresh" : "/api/dhan/status";
      const response = await fetch(`${apiBaseUrl}${endpoint}`, { method: refresh ? "POST" : "GET" });
      if (!response.ok) throw new Error(await readError(response));
      setStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Dhan status.");
    } finally {
      setBusy(false);
    }
  }

  async function loadGeminiStatus() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/ai/gemini/status`);
      if (!response.ok) throw new Error(await readError(response));
      setGeminiStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Gemini key status.");
    }
  }

  async function validateGeminiKey() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/ai/gemini/validate`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as GeminiKeyStatus;
      setGeminiStatus(data);
      setMessage(data.state === "active" ? "Gemini API key validated." : data.last_error || "Gemini validation failed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to validate Gemini key.");
    } finally {
      setBusy(false);
    }
  }

  async function loadInstrumentStatus() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/instruments/status`);
      if (!response.ok) throw new Error(await readError(response));
      setInstrumentStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load instrument master status.");
    }
  }

  async function refreshInstruments() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/instruments/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setMessage(`Imported ${formatNumber(data.imported_rows)} NSE instruments from Dhan.`);
      await loadInstrumentStatus();
      if (instrumentQuery.trim()) {
        await searchInstruments(instrumentQuery);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh instrument master.");
    } finally {
      setBusy(false);
    }
  }

  async function loadUniverseStatus() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/universe/nifty500/status`);
      if (!response.ok) throw new Error(await readError(response));
      setUniverseStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Nifty 500 status.");
    }
  }

  async function refreshUniverse() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/universe/nifty500/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setMessage(`Imported ${formatNumber(data.imported_rows)} Nifty 500 constituents from NSE.`);
      await loadUniverseStatus();
      await loadUniverse(universeQuery);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh Nifty 500 universe.");
    } finally {
      setBusy(false);
    }
  }

  async function loadUniverse(query = universeQuery) {
    const trimmed = query.trim();
    setUniverseQuery(query);
    try {
      const params = new URLSearchParams({ limit: "600" });
      if (trimmed) params.set("query", trimmed);
      const response = await fetch(`${apiBaseUrl}/api/universe/nifty500/constituents?${params.toString()}`);
      if (!response.ok) throw new Error(await readError(response));
      setUniverseResults(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Nifty 500 constituents.");
    }
  }

  async function searchInstruments(query = instrumentQuery) {
    const trimmed = query.trim();
    setInstrumentQuery(query);
    if (!trimmed) {
      setInstrumentResults([]);
      return;
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/instruments/search?query=${encodeURIComponent(trimmed)}&limit=10`);
      if (!response.ok) throw new Error(await readError(response));
      setInstrumentResults(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to search instruments.");
    }
  }

  async function loadHistoricalStatus() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/historical/nifty500/status`);
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as HistoricalStatus | null;
      setHistoricalStatus(data);
      if (data?.id && data.failed_count > 0) {
        await loadHistoricalItems(data.id, "failed");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load historical fetch status.");
    }
  }

  async function startHistoricalFetch() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/historical/nifty500/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as HistoricalStatus;
      setHistoricalStatus(data);
      setMessage(
        data.status === "up_to_date"
          ? "Historical candles are already up to date. No Dhan fetch was started."
          : `Historical fetch run ${data.id} started or resumed.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start historical fetch.");
    } finally {
      setBusy(false);
    }
  }

  async function loadHistoricalItems(runId = historicalStatus?.id, itemStatus = "failed") {
    if (!runId) return;
    try {
      const params = new URLSearchParams({ run_id: String(runId), status: itemStatus, limit: "50" });
      const response = await fetch(`${apiBaseUrl}/api/historical/nifty500/items?${params.toString()}`);
      if (!response.ok) throw new Error(await readError(response));
      setHistoricalItems(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load historical fetch items.");
    }
  }

  async function loadCandles(symbol = candleSymbol) {
    const trimmed = symbol.trim();
    setCandleSymbol(symbol);
    if (!trimmed) {
      setCandles([]);
      return;
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/historical/candles?symbol=${encodeURIComponent(trimmed)}&limit=10`);
      if (!response.ok) throw new Error(await readError(response));
      setCandles(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load stored candles.");
    }
  }

  async function loadQualityReport() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/quality/nifty500/report?status=exceptions&limit=100`);
      if (!response.ok) throw new Error(await readError(response));
      setQualityReport(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load data quality report.");
    }
  }

  async function loadRangeMovers(threshold = rangeMoverThreshold) {
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/analytics/nifty500/upward-movers?threshold_percent=${threshold}&limit=500`,
      );
      if (!response.ok) throw new Error(await readError(response));
      setRangeMoverReport(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load range movers.");
    }
  }

  async function loadMoveEvents() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/research/nifty500/move-events?limit=500`);
      if (!response.ok) throw new Error(await readError(response));
      setMoveEventReport(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load move events.");
    }
  }

  async function loadDrishtiSignal01(showBusy = false) {
    if (showBusy) {
      setDrishtiBusy(true);
      setMessage("");
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/drishti/nifty500/signals/local-low-reversal?limit=500`);
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as DrishtiSignalReport | null;
      setDrishtiReport(data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Drishti signal.");
    } finally {
      if (showBusy) setDrishtiBusy(false);
    }
  }

  async function reviewDrishtiHitWithAi(hit: DrishtiSignalHitItem) {
    setReviewingHitId(hit.id);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/ai/reviews/drishti-hit/${hit.id}`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const review = (await response.json()) as AiSignalReview;
      setAiReviewsByHit((current) => ({ ...current, [hit.id]: review }));
      setMessage(
        review.status !== "completed"
          ? `Gemini review for ${hit.symbol} failed: ${review.error || "unknown error"}.`
          : `Gemini review for ${hit.symbol}: ${review.decision}.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to review Drishti hit with Gemini.");
    } finally {
      setReviewingHitId(null);
    }
  }

  async function refreshDrishtiSignal01() {
    setDrishtiBusy(true);
    setMessage("");
    try {
      const params = new URLSearchParams({
        lookback_sessions: "45",
        volume_sma_sessions: "20",
        min_volume_ratio_1d: "1.2",
        min_volume_vs_sma: "1.0",
      });
      const response = await fetch(`${apiBaseUrl}/api/drishti/nifty500/signals/local-low-reversal/refresh?${params}`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as DrishtiSignalReport;
      setDrishtiReport(data);
      setMessage(`Drishti Signal 01 found ${formatNumber(data.hit_count)} historical hit(s).`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh Drishti signal.");
    } finally {
      setDrishtiBusy(false);
    }
  }

  async function loadDemoTrading() {
    try {
      const [summaryResponse, ordersResponse, openPositionsResponse, closedPositionsResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/demo/summary`),
        fetch(`${apiBaseUrl}/api/demo/orders?limit=50`),
        fetch(`${apiBaseUrl}/api/demo/positions?status=open&limit=50`),
        fetch(`${apiBaseUrl}/api/demo/positions?status=closed&limit=50`),
      ]);
      if (!summaryResponse.ok) throw new Error(await readError(summaryResponse));
      if (!ordersResponse.ok) throw new Error(await readError(ordersResponse));
      if (!openPositionsResponse.ok) throw new Error(await readError(openPositionsResponse));
      if (!closedPositionsResponse.ok) throw new Error(await readError(closedPositionsResponse));
      setDemoSummary(await summaryResponse.json());
      setDemoOrders(await ordersResponse.json());
      setDemoOpenPositions(await openPositionsResponse.json());
      setDemoClosedPositions(await closedPositionsResponse.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load demo trading ledger.");
    }
  }

  async function createDemoOrderFromHit(hit: DrishtiSignalHitItem) {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/demo/orders/from-drishti-hit/${hit.id}`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as DemoOrderCreateResponse;
      setDemoSummary(data.summary);
      setMessage(`Demo order ${data.order.id} for ${data.order.symbol} is ${formatStatus(data.order.status)}.`);
      await loadDemoTrading();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create demo order.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshDemoTrading() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/demo/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as DemoRefreshResponse;
      setDemoSummary(data.summary);
      setMessage(
        `Demo refreshed: ${formatNumber(data.filled_orders.length)} filled, ${formatNumber(data.closed_positions.length)} closed, ${formatNumber(data.rejected_orders.length)} rejected.`,
      );
      await loadDemoTrading();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh demo trades.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshMoveEvents() {
    setBusy(true);
    setMessage("");
    try {
      const params = new URLSearchParams({ threshold_percent: "10", pullback_percent: "5" });
      const response = await fetch(`${apiBaseUrl}/api/research/nifty500/move-events/refresh?${params.toString()}`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as MoveEventReport;
      setMoveEventReport(data);
      setMessage(
        `Detected ${formatNumber(data.event_count)} >=10% event(s) across ${formatNumber(data.candidate_symbols)} stock(s).`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh move events.");
    } finally {
      setBusy(false);
    }
  }

  function changeRangeMoverThreshold(value: string) {
    const nextThreshold = Number(value);
    setRangeMoverThreshold(nextThreshold);
    loadRangeMovers(nextThreshold);
  }

  async function renewToken() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/dhan/renew`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as RenewResponse;
      setStatus(data.status);
      setMessage(data.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to renew Dhan token.");
    } finally {
      setBusy(false);
    }
  }

  async function saveToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/dhan/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dhan_client_id: form.dhanClientId.trim(),
          access_token: form.accessToken.trim(),
          expiry_time: form.expiryTime ? new Date(form.expiryTime).toISOString() : null,
          validate_with_dhan: form.validateWithDhan,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      setStatus(await response.json());
      setForm({ dhanClientId: "", accessToken: "", expiryTime: "", validateWithDhan: true });
      setMessage("Token saved. Automatic renewal will take over before expiry.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save Dhan token.");
    } finally {
      setBusy(false);
    }
  }

  async function saveGeminiKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/ai/gemini/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: geminiForm.apiKey.trim(),
          validate_with_gemini: geminiForm.validateWithGemini,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as GeminiKeyStatus;
      setGeminiStatus(data);
      setGeminiForm({ apiKey: "", validateWithGemini: true });
      setMessage(
        data.state === "active"
          ? "Gemini API key saved on the backend."
          : data.last_error || "Gemini API key saved, but validation is not active.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save Gemini key.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadStatus();
    loadGeminiStatus();
    loadInstrumentStatus();
    loadUniverseStatus();
    loadUniverse();
    loadHistoricalStatus();
    loadQualityReport();
    loadRangeMovers();
    loadMoveEvents();
    loadDrishtiSignal01();
    loadDemoTrading();
    const timer = window.setInterval(() => loadStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!historicalStatus || !["queued", "running"].includes(historicalStatus.status)) return;
    const timer = window.setInterval(() => loadHistoricalStatus(), 3_000);
    return () => window.clearInterval(timer);
  }, [historicalStatus?.id, historicalStatus?.status]);

  const historicalProgress =
    historicalStatus && historicalStatus.total_symbols > 0
      ? Math.round(
          ((historicalStatus.done_count + historicalStatus.failed_count + historicalStatus.skipped_count) /
            historicalStatus.total_symbols) *
            100,
        )
      : 0;
  const systemStateMeta = getSystemStateMeta(
    status?.state ?? "unknown",
    geminiStatus?.state ?? "unknown",
    historicalStatus?.status,
    qualityReport?.blocked_count ?? 0,
  );
  const activeStatusMeta = activePage === "settings" ? getSettingsStateMeta(stateMeta, geminiStateMeta) : systemStateMeta;
  const pageMeta = getPageMeta(activePage);
  const latestDrishtiItems = drishtiReport?.items.slice(0, 8) ?? [];
  const actionCount =
    (status?.state && !["active", "expiring_soon"].includes(status.state) ? 1 : 0) +
    (geminiStatus?.state === "missing" || geminiStatus?.state === "validation_failed" ? 1 : 0) +
    (historicalStatus?.failed_count ?? 0) +
    (qualityReport?.blocked_count ?? 0);

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">{pageMeta.eyebrow}</p>
          <h1>{pageMeta.title}</h1>
        </div>
        <div className="topbar-actions">
          <div className={`status-pill ${activeStatusMeta.className}`}>
            {activeStatusMeta.icon}
            <span>{activeStatusMeta.label}</span>
          </div>
          <nav className="page-tabs" aria-label="Dashboard views">
            <button
              type="button"
              className={`page-tab ${activePage === "dashboard" ? "active" : ""}`}
              onClick={() => setActivePage("dashboard")}
            >
              Dashboard
            </button>
            <button
              type="button"
              className={`page-tab ${activePage === "drishti" ? "active" : ""}`}
              onClick={() => setActivePage("drishti")}
            >
              Drishti
            </button>
            <button
              type="button"
              className={`page-tab ${activePage === "demo" ? "active" : ""}`}
              onClick={() => setActivePage("demo")}
            >
              Demo Trading
            </button>
            <button
              type="button"
              className={`page-tab ${activePage === "data" ? "active" : ""}`}
              onClick={() => setActivePage("data")}
            >
              Data Health
            </button>
            <button
              type="button"
              className={`page-tab ${activePage === "settings" ? "active" : ""}`}
              onClick={() => setActivePage("settings")}
            >
              Settings
            </button>
          </nav>
        </div>
      </section>

      {activePage === "settings" ? (
        <>
        <section className="grid">
          <div className="panel status-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Gemini</p>
                <h2>API Key Status</h2>
              </div>
              <button className="icon-button" onClick={loadGeminiStatus} disabled={busy} title="Refresh Gemini status">
                <RefreshCcw size={18} />
              </button>
            </div>

            <dl className="status-list">
              <StatusRow label="Provider" value={geminiStatus?.provider ?? "gemini"} />
              <StatusRow label="State" value={formatStatus(geminiStatus?.state)} />
              <StatusRow label="Stored key" value={geminiStatus?.masked_key ?? "-"} />
              <StatusRow label="Key source" value={geminiStatus?.key_source ?? "-"} />
              <StatusRow label="Last validation" value={formatDate(geminiStatus?.last_validated_at)} />
              <StatusRow label="Updated" value={formatDate(geminiStatus?.updated_at)} />
            </dl>

            {geminiStatus?.last_error ? <p className="error-text">{geminiStatus.last_error}</p> : null}

            <div className="button-row">
              <button onClick={validateGeminiKey} disabled={busy || !geminiStatus?.has_key}>
                <CheckCircle2 size={17} />
                Validate key
              </button>
              <button className="secondary" onClick={loadGeminiStatus} disabled={busy}>
                <Wifi size={17} />
                Check local
              </button>
            </div>
          </div>

          <form className="panel" onSubmit={saveGeminiKey}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Backend Secret</p>
                <h2>Save Gemini API Key</h2>
              </div>
              <Shield size={22} />
            </div>

            <label>
              Gemini API key
              <textarea
                value={geminiForm.apiKey}
                onChange={(event) => setGeminiForm({ ...geminiForm, apiKey: event.target.value })}
                autoComplete="off"
                rows={4}
                required
              />
            </label>

            <label className="check-row">
              <input
                type="checkbox"
                checked={geminiForm.validateWithGemini}
                onChange={(event) => setGeminiForm({ ...geminiForm, validateWithGemini: event.target.checked })}
              />
              Validate with Gemini before saving
            </label>

            <button type="submit" disabled={busy}>
              <Save size={17} />
              Save Gemini key
            </button>
          </form>
        </section>

        <section className="grid instruments-panel">
        <div className="panel status-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Connection</p>
              <h2>Dhan API Status</h2>
            </div>
            <button className="icon-button" onClick={() => loadStatus(true)} disabled={busy} title="Refresh status">
              <RefreshCcw size={18} />
            </button>
          </div>

          <dl className="status-list">
            <StatusRow label="Client ID" value={status?.dhan_client_id ?? "-"} />
            <StatusRow label="Stored token" value={status?.masked_token ?? "-"} />
            <StatusRow label="Token source" value={status?.token_source ?? "-"} />
            <StatusRow label="Expiry" value={formatDate(status?.expiry_time)} />
            <StatusRow label="Minutes left" value={formatNumber(status?.minutes_to_expiry)} />
            <StatusRow label="Data plan" value={status?.data_plan ?? "-"} />
            <StatusRow label="Active segment" value={status?.active_segment ?? "-"} />
            <StatusRow label="Last renew" value={formatDate(status?.last_renew_success_at)} />
          </dl>

          {status?.last_error ? <p className="error-text">{status.last_error}</p> : null}

          <div className="button-row">
            <button onClick={renewToken} disabled={busy || !status?.has_token}>
              <RefreshCcw size={17} />
              Renew now
            </button>
            <button className="secondary" onClick={() => loadStatus(false)} disabled={busy}>
              <Wifi size={17} />
              Check local
            </button>
          </div>
        </div>

        <form className="panel" onSubmit={saveToken}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Fallback</p>
              <h2>Manual Token Update</h2>
            </div>
            <Shield size={22} />
          </div>

          <label>
            Dhan Client ID
            <input
              value={form.dhanClientId}
              onChange={(event) => setForm({ ...form, dhanClientId: event.target.value })}
              autoComplete="off"
              required
            />
          </label>

          <label>
            Access Token
            <textarea
              value={form.accessToken}
              onChange={(event) => setForm({ ...form, accessToken: event.target.value })}
              autoComplete="off"
              rows={5}
              required
            />
          </label>

          <label>
            Expiry time
            <input
              type="datetime-local"
              value={form.expiryTime}
              onChange={(event) => setForm({ ...form, expiryTime: event.target.value })}
            />
          </label>

          <label className="check-row">
            <input
              type="checkbox"
              checked={form.validateWithDhan}
              onChange={(event) => setForm({ ...form, validateWithDhan: event.target.checked })}
            />
            Validate with Dhan profile before saving
          </label>

          <button type="submit" disabled={busy}>
            <Save size={17} />
            Save token
          </button>
        </form>
      </section>
        </>

      ) : (
        <>
      {activePage === "dashboard" ? (
        <>
          <section className="dashboard-grid">
            <article className="hero-panel">
              <div>
                <p className="eyebrow">Today</p>
                <h2>Command Center</h2>
              </div>
              <dl className="hero-metrics">
                <StatusRow label="Drishti alerts" value={formatNumber(drishtiReport?.hit_count)} />
                <StatusRow label="Open demo positions" value={formatNumber(demoSummary?.open_positions)} />
                <StatusRow label="Pending demo orders" value={formatNumber(demoSummary?.pending_orders)} />
                <StatusRow label="Action items" value={formatNumber(actionCount)} />
              </dl>
              <div className="button-row">
                <button onClick={() => setActivePage("drishti")}>
                  <Radar size={17} />
                  Review Drishti
                </button>
                <button className="secondary" onClick={refreshDemoTrading} disabled={busy}>
                  <RefreshCcw size={17} />
                  Refresh demo
                </button>
              </div>
            </article>

            <article className="dashboard-card">
              <div className="card-icon ok"><Wifi size={19} /></div>
              <p className="eyebrow">Connections</p>
              <h2>Dhan & Gemini</h2>
              <dl className="mini-list">
                <StatusRow label="Dhan" value={formatStatus(status?.state)} />
                <StatusRow label="Gemini" value={formatStatus(geminiStatus?.state)} />
                <StatusRow label="Token expiry" value={formatDate(status?.expiry_time)} />
              </dl>
              <button className="secondary" onClick={() => setActivePage("settings")}>
                Open settings
              </button>
            </article>

            <article className="dashboard-card">
              <div className="card-icon warn"><Database size={19} /></div>
              <p className="eyebrow">Data Layer</p>
              <h2>Nifty 500 Feed</h2>
              <dl className="mini-list">
                <StatusRow label="Historical" value={historicalStatus?.status ?? "-"} />
                <StatusRow label="Progress" value={`${historicalProgress}%`} />
                <StatusRow label="Quality blocked" value={formatNumber(qualityReport?.blocked_count)} />
              </dl>
              <button className="secondary" onClick={() => setActivePage("data")}>
                Inspect data
              </button>
            </article>
          </section>

          <section className="panel instruments-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Latest Watchlist</p>
                <h2>Recent Drishti Signal 01 Alerts</h2>
              </div>
              <Radar size={22} />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Trigger</th>
                    <th>Trigger close</th>
                    <th>Volume</th>
                    <th>Outcome</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {latestDrishtiItems.length === 0 ? (
                    <tr>
                      <td colSpan={6}>No Drishti alerts loaded yet.</td>
                    </tr>
                  ) : (
                    latestDrishtiItems.map((item) => (
                      <tr key={`dashboard-${item.id}`}>
                        <td>{item.symbol}</td>
                        <td>{item.trigger_date}</td>
                        <td>{formatPrice(item.trigger_close)}</td>
                        <td>{formatMultiplier(item.volume_ratio_1d)}</td>
                        <td>{formatPercent(item.outcome_from_trigger_percent)}</td>
                        <td>
                          <button className="mini-action" onClick={() => createDemoOrderFromHit(item)} disabled={busy}>
                            Paper
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {activePage === "drishti" ? (
        <>
      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Drishti Early Watch</p>
            <h2>Signal 01: Local Low Reversal</h2>
          </div>
          <Radar size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Stored signal" value={drishtiReport?.signal_id ?? "DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL"} />
          <StatusRow label="Hits" value={formatNumber(drishtiReport?.hit_count)} />
          <StatusRow label="Scanned" value={formatNumber(drishtiReport?.scanned_symbols)} />
          <StatusRow label="Lookback sessions" value={formatNumber(drishtiReport?.lookback_sessions)} />
          <StatusRow label="Volume rule" value={`${formatMultiplier(drishtiReport?.min_volume_ratio_1d)} day / ${formatMultiplier(drishtiReport?.min_volume_vs_sma)} SMA`} />
          <StatusRow label=">=10% outcome" value={formatNumber(drishtiReport?.outcome_ge_10_count)} />
          <StatusRow label=">=20% outcome" value={formatNumber(drishtiReport?.outcome_ge_20_count)} />
          <StatusRow label="Window from" value={drishtiReport?.from_date ?? "-"} />
          <StatusRow label="Window to" value={drishtiReport?.to_date_exclusive ?? "-"} />
          <StatusRow label="Generated" value={formatDate(drishtiReport?.generated_at)} />
        </dl>

        {drishtiReport?.error ? <p className="error-text">{drishtiReport.error}</p> : null}

        <div className="button-row">
          <button onClick={refreshDrishtiSignal01} disabled={drishtiBusy}>
            <RefreshCcw size={17} />
            {drishtiBusy ? "Running..." : "Run Signal 01"}
          </button>
          <button className="secondary" onClick={() => loadDrishtiSignal01(true)} disabled={drishtiBusy}>
            <Wifi size={17} />
            Load saved run
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Chart</th>
                <th>Demo</th>
                <th>AI</th>
                <th>Symbol</th>
                <th>Company</th>
                <th>Anchor</th>
                <th>Trigger</th>
                <th>Anchor low</th>
                <th>Trigger close</th>
                <th>Volume</th>
                <th>Vol/SMA</th>
                <th>Future high</th>
                <th>Trigger outcome</th>
              </tr>
            </thead>
            <tbody>
              {!drishtiReport || drishtiReport.items.length === 0 ? (
                <tr>
                  <td colSpan={13}>No saved Drishti hits yet.</td>
                </tr>
              ) : (
                drishtiReport.items.map((item) => {
                  const review = aiReviewsByHit[item.id];
                  return [
                    <tr key={`${item.symbol}-${item.trigger_date}-${item.id}`}>
                      <td>
                        <a
                          className="table-action"
                          href={dhanTradingViewUrl(item)}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`Open ${item.symbol} in Dhan TradingView`}
                          title={`Open ${item.symbol} in Dhan TradingView`}
                        >
                          <ExternalLink size={16} />
                        </a>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="mini-action"
                          onClick={() => createDemoOrderFromHit(item)}
                          disabled={busy}
                          title={`Create demo order for ${item.symbol}`}
                        >
                          Paper
                        </button>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="mini-action ai-action"
                          onClick={() => reviewDrishtiHitWithAi(item)}
                          disabled={reviewingHitId === item.id || geminiStatus?.state !== "active"}
                          title={`Ask Gemini to review ${item.symbol}`}
                        >
                          {reviewingHitId === item.id
                            ? "..."
                            : review?.status === "quota_limited"
                              ? "Quota"
                              : review?.status === "failed"
                              ? "Retry AI"
                              : review
                                ? review.decision
                                : "AI"}
                        </button>
                      </td>
                      <td>{item.symbol}</td>
                      <td>{item.company_name}</td>
                      <td>{item.anchor_date}</td>
                      <td>{item.trigger_date}</td>
                      <td>{formatPrice(item.anchor_low)}</td>
                      <td>{formatPrice(item.trigger_close)}</td>
                      <td>{formatMultiplier(item.volume_ratio_1d)}</td>
                      <td>{formatMultiplier(item.volume_vs_sma)}</td>
                      <td>
                        {formatPrice(item.future_high)} on {item.future_high_date}
                      </td>
                      <td>{formatPercent(item.outcome_from_trigger_percent)}</td>
                    </tr>,
                    review ? (
                      <tr key={`review-${review.id}`} className="review-row">
                        <td colSpan={13}>
                          <div className="review-card">
                            <div>
                              <p
                                className={`review-decision ${
                                  review.status === "quota_limited"
                                    ? "quota"
                                    : review.status === "failed"
                                      ? "failed"
                                      : review.decision.toLowerCase()
                                }`}
                              >
                                {review.status === "quota_limited"
                                  ? "QUOTA LIMITED"
                                  : review.status === "failed"
                                    ? "AI FAILED"
                                    : review.decision}
                              </p>
                              <p>{review.summary || "No summary returned."}</p>
                              <p className="review-mode">
                                {review.provider} / {review.model} /{" "}
                                {review.grounding_enabled ? "cached data + search" : "cached data only"}
                              </p>
                            </div>
                            <dl className="review-grid">
                              <StatusRow label="Confidence" value={`${formatNumber(review.confidence)}%`} />
                              <StatusRow label="Error" value={review.error || "-"} />
                              <StatusRow label="Entry" value={`${formatPrice(review.entry_low)} - ${formatPrice(review.entry_high)}`} />
                              <StatusRow label="Stop" value={formatPrice(review.stop_loss)} />
                              <StatusRow label="Trail stop" value={formatPrice(review.trailing_stop_loss)} />
                              <StatusRow label="Target 1" value={formatPrice(review.target_1)} />
                              <StatusRow label="Target 2" value={formatPrice(review.target_2)} />
                              <StatusRow label="R:R" value={formatNumber(review.risk_reward)} />
                              <StatusRow label="Wait until" value={review.wait_until || "-"} />
                              <StatusRow label="Invalidation" value={review.invalidation || "-"} />
                            </dl>
                          </div>
                        </td>
                      </tr>
                    ) : null,
                  ];
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

        </>
      ) : null}

      {activePage === "demo" ? (
        <>
      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Demo Trading</p>
            <h2>Paper Orders And Positions</h2>
          </div>
          <TrendingUp size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Cash" value={formatCurrency(demoSummary?.cash_balance)} />
          <StatusRow label="Equity" value={formatCurrency(demoSummary?.equity_value)} />
          <StatusRow label="Open value" value={formatCurrency(demoSummary?.open_market_value)} />
          <StatusRow label="Realized P&L" value={formatCurrency(demoSummary?.realized_pnl)} />
          <StatusRow label="Unrealized P&L" value={formatCurrency(demoSummary?.unrealized_pnl)} />
          <StatusRow label="Pending orders" value={formatNumber(demoSummary?.pending_orders)} />
          <StatusRow label="Open positions" value={formatNumber(demoSummary?.open_positions)} />
          <StatusRow label="Closed positions" value={formatNumber(demoSummary?.closed_positions)} />
          <StatusRow label="Rejected orders" value={formatNumber(demoSummary?.rejected_orders)} />
          <StatusRow label="Updated" value={formatDate(demoSummary?.updated_at)} />
        </dl>

        <div className="button-row">
          <button onClick={refreshDemoTrading} disabled={busy}>
            <RefreshCcw size={17} />
            Refresh demo lifecycle
          </button>
          <button className="secondary" onClick={loadDemoTrading} disabled={busy}>
            <Wifi size={17} />
            Reload ledger
          </button>
        </div>

        <h3 className="table-heading">Open positions</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Entry</th>
                <th>Entry date</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Latest</th>
                <th>Sessions</th>
                <th>Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {demoOpenPositions.length === 0 ? (
                <tr>
                  <td colSpan={8}>No open demo positions.</td>
                </tr>
              ) : (
                demoOpenPositions.map((position) => (
                  <tr key={position.id}>
                    <td>{position.symbol}</td>
                    <td>{formatPrice(position.entry_price)}</td>
                    <td>{position.entry_date}</td>
                    <td>{formatPrice(position.stop_loss)}</td>
                    <td>{formatPrice(position.target_price)}</td>
                    <td>
                      {formatPrice(position.latest_close)} on {position.latest_candle_date ?? "-"}
                    </td>
                    <td>{formatNumber(position.holding_sessions)}</td>
                    <td>
                      {formatCurrency(position.unrealized_pnl)} ({formatPercent(position.unrealized_pnl_percent)})
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <h3 className="table-heading">Recent orders</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Symbol</th>
                <th>Trigger</th>
                <th>Requested</th>
                <th>Filled</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {demoOrders.length === 0 ? (
                <tr>
                  <td colSpan={8}>No demo orders yet. Use Paper from a Drishti row.</td>
                </tr>
              ) : (
                demoOrders.map((order) => (
                  <tr key={order.id}>
                    <td>{formatStatus(order.status)}</td>
                    <td>{order.symbol}</td>
                    <td>{order.trigger_date}</td>
                    <td>{formatPrice(order.requested_price)}</td>
                    <td>
                      {formatPrice(order.filled_price)} {order.filled_date ? `on ${order.filled_date}` : ""}
                    </td>
                    <td>{formatPrice(order.stop_loss)}</td>
                    <td>{formatPrice(order.target_price)}</td>
                    <td>{order.rejection_reason || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <h3 className="table-heading">Closed positions</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Reason</th>
                <th>Sessions</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {demoClosedPositions.length === 0 ? (
                <tr>
                  <td colSpan={6}>No closed demo positions.</td>
                </tr>
              ) : (
                demoClosedPositions.map((position) => (
                  <tr key={position.id}>
                    <td>{position.symbol}</td>
                    <td>
                      {formatPrice(position.entry_price)} on {position.entry_date}
                    </td>
                    <td>
                      {formatPrice(position.exit_price)} on {position.exit_date ?? "-"}
                    </td>
                    <td>{position.exit_reason || "-"}</td>
                    <td>{formatNumber(position.holding_sessions)}</td>
                    <td>
                      {formatCurrency(position.realized_pnl)} ({formatPercent(position.realized_pnl_percent)})
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

        </>
      ) : null}

      {activePage === "drishti" ? (
        <>
      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Research Events</p>
            <h2>45-Day Candidate Events</h2>
          </div>
          <Search size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Events" value={formatNumber(moveEventReport?.event_count)} />
          <StatusRow label="Candidate stocks" value={formatNumber(moveEventReport?.candidate_symbols)} />
          <StatusRow label="Scanned" value={formatNumber(moveEventReport?.scanned_symbols)} />
          <StatusRow label="Threshold" value={formatPercent(moveEventReport?.threshold_percent)} />
          <StatusRow label="Pullback split" value={formatPercent(moveEventReport?.pullback_percent)} />
          <StatusRow label="Window from" value={moveEventReport?.from_date ?? "-"} />
          <StatusRow label="Window to" value={moveEventReport?.to_date_exclusive ?? "-"} />
          <StatusRow label="Generated" value={formatDate(moveEventReport?.generated_at)} />
        </dl>

        {moveEventReport?.error ? <p className="error-text">{moveEventReport.error}</p> : null}

        <div className="button-row">
          <button onClick={refreshMoveEvents} disabled={busy}>
            <RefreshCcw size={17} />
            Detect candidate events
          </button>
          <button className="secondary" onClick={loadMoveEvents} disabled={busy}>
            <Wifi size={17} />
            Reload events
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Company</th>
                <th>Industry</th>
                <th>Bucket</th>
                <th>Event</th>
                <th>Low</th>
                <th>Low date</th>
                <th>High</th>
                <th>High date</th>
                <th>Move</th>
                <th>Sessions</th>
                <th>Days</th>
              </tr>
            </thead>
            <tbody>
              {!moveEventReport || moveEventReport.items.length === 0 ? (
                <tr>
                  <td colSpan={12}>No stored candidate events. Run detection after the 45-day data is current.</td>
                </tr>
              ) : (
                moveEventReport.items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.symbol}</td>
                    <td>{item.company_name}</td>
                    <td>{item.industry}</td>
                    <td>{item.bucket}</td>
                    <td>{formatNumber(item.event_number)}</td>
                    <td>{formatPrice(item.low_price)}</td>
                    <td>{item.low_date}</td>
                    <td>{formatPrice(item.high_price)}</td>
                    <td>{item.high_date}</td>
                    <td>{formatPercent(item.move_percent)}</td>
                    <td>{formatNumber(item.duration_trading_sessions)}</td>
                    <td>{formatNumber(item.duration_calendar_days)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

        </>
      ) : null}

      {activePage === "data" ? (
        <>
      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Momentum Scan</p>
            <h2>45-Day Upward Move Above {rangeMoverThreshold}%</h2>
          </div>
          <TrendingUp size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Matches" value={formatNumber(rangeMoverReport?.match_count)} />
          <StatusRow label="Scanned" value={formatNumber(rangeMoverReport?.total_scanned)} />
          <StatusRow label="Threshold" value={formatPercent(rangeMoverReport?.threshold_percent)} />
          <StatusRow label="Window from" value={rangeMoverReport?.from_date ?? "-"} />
          <StatusRow label="Window to" value={rangeMoverReport?.to_date_exclusive ?? "-"} />
          <StatusRow label="Generated" value={formatDate(rangeMoverReport?.generated_at)} />
        </dl>

        <div className="button-row">
          <label className="inline-control">
            Minimum upward move
            <select value={rangeMoverThreshold} onChange={(event) => changeRangeMoverThreshold(event.target.value)}>
              {rangeMoverThresholdOptions.map((value) => (
                <option key={value} value={value}>
                  {value}%
                </option>
              ))}
            </select>
          </label>
          <button className="secondary" onClick={() => loadRangeMovers()} disabled={busy}>
            <RefreshCcw size={17} />
            Recheck movers
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Chart</th>
                <th>Symbol</th>
                <th>Company</th>
                <th>Industry</th>
                <th>Low</th>
                <th>Low date</th>
                <th>High</th>
                <th>High date</th>
                <th>Move</th>
              </tr>
            </thead>
            <tbody>
              {!rangeMoverReport || rangeMoverReport.items.length === 0 ? (
                <tr>
                  <td colSpan={9}>No stocks crossed the threshold.</td>
                </tr>
              ) : (
                rangeMoverReport.items.map((item) => (
                  <tr key={item.symbol}>
                    <td>
                      <a
                        className="table-action"
                        href={dhanTradingViewUrl(item)}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open ${item.symbol} in Dhan TradingView`}
                        title={`Open ${item.symbol} in Dhan TradingView`}
                      >
                        <ExternalLink size={16} />
                      </a>
                    </td>
                    <td>{item.symbol}</td>
                    <td>{item.company_name}</td>
                    <td>{item.industry}</td>
                    <td>{formatPrice(item.lowest_low)}</td>
                    <td>{item.lowest_low_date}</td>
                    <td>{formatPrice(item.highest_high)}</td>
                    <td>{item.highest_high_date}</td>
                    <td>{formatPercent(item.move_percent)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

        </>
      ) : null}

      {activePage === "data" ? (
        <>
      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Quality</p>
            <h2>Nifty 500 Data Checks</h2>
          </div>
          <CheckCircle2 size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Healthy" value={formatNumber(qualityReport?.healthy_count)} />
          <StatusRow label="Warnings" value={formatNumber(qualityReport?.warning_count)} />
          <StatusRow label="Blocked" value={formatNumber(qualityReport?.blocked_count)} />
          <StatusRow label="Expected sessions" value={formatNumber(qualityReport?.expected_session_count)} />
          <StatusRow label="Latest session" value={qualityReport?.latest_expected_session ?? "-"} />
          <StatusRow label="Historical run" value={qualityReport?.historical_run_status ?? "-"} />
          <StatusRow label="Generated" value={formatDate(qualityReport?.generated_at)} />
          <StatusRow label="Exceptions shown" value={formatNumber(qualityReport?.items.length)} />
        </dl>

        <div className="button-row">
          <button className="secondary" onClick={loadQualityReport} disabled={busy}>
            <RefreshCcw size={17} />
            Recheck quality
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Symbol</th>
                <th>Company</th>
                <th>Latest</th>
                <th>Candles</th>
                <th>Missing</th>
                <th>Issues</th>
              </tr>
            </thead>
            <tbody>
              {!qualityReport || qualityReport.items.length === 0 ? (
                <tr>
                  <td colSpan={7}>No quality exceptions.</td>
                </tr>
              ) : (
                qualityReport.items.map((item) => (
                  <tr key={item.symbol}>
                    <td>{item.quality_status}</td>
                    <td>{item.symbol}</td>
                    <td>{item.company_name}</td>
                    <td>{item.latest_candle_date ?? "-"}</td>
                    <td>{formatNumber(item.candle_count)}</td>
                    <td>{formatNumber(item.missing_sessions)}</td>
                    <td>{formatIssues(item.issues)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Historical Data</p>
            <h2>Nifty 500 Rolling 45 Days</h2>
          </div>
          <Clock size={22} />
        </div>

        <div className="progress-track" aria-label="Historical fetch progress">
          <span style={{ width: `${historicalProgress}%` }} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Run status" value={historicalStatus?.status ?? "-"} />
          <StatusRow label="Progress" value={`${historicalProgress}%`} />
          <StatusRow label="Window from" value={historicalStatus?.from_date ?? "-"} />
          <StatusRow label="Window to" value={historicalStatus?.to_date_exclusive ?? "-"} />
          <StatusRow label="Mapped" value={formatNumber(historicalStatus?.mapped_symbols)} />
          <StatusRow label="Done" value={formatNumber(historicalStatus?.done_count)} />
          <StatusRow label="Failed" value={formatNumber(historicalStatus?.failed_count)} />
          <StatusRow label="Skipped" value={formatNumber(historicalStatus?.skipped_count)} />
          <StatusRow label="Candles received" value={formatNumber(historicalStatus?.candles_received)} />
          <StatusRow label="Stored candles" value={formatNumber(historicalStatus?.stored_candle_count)} />
          <StatusRow label="Updated" value={formatDate(historicalStatus?.updated_at)} />
          <StatusRow label="Completed" value={formatDate(historicalStatus?.completed_at)} />
        </dl>

        {historicalStatus?.error ? <p className="error-text">{historicalStatus.error}</p> : null}

        <div className="button-row">
          <button onClick={startHistoricalFetch} disabled={busy}>
            <RefreshCcw size={17} />
            Check / fetch missing
          </button>
          <button className="secondary" onClick={() => loadHistoricalStatus()} disabled={busy}>
            <Wifi size={17} />
            Check status
          </button>
        </div>

        {historicalItems.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Failed symbol</th>
                  <th>Company</th>
                  <th>Attempts</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {historicalItems.map((item) => (
                  <tr key={item.id}>
                    <td>{item.symbol}</td>
                    <td>{item.company_name}</td>
                    <td>{formatNumber(item.attempts)}</td>
                    <td>{item.error || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <label className="search-label">
          Inspect stored candles
          <div className="search-row">
            <input
              value={candleSymbol}
              onChange={(event) => loadCandles(event.target.value)}
              placeholder="RELIANCE"
            />
            <button type="button" className="secondary" onClick={() => loadCandles()} disabled={busy}>
              <Search size={17} />
            </button>
          </div>
        </label>

        {candles.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Open</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Close</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {candles.map((candle) => (
                  <tr key={candle.trading_date}>
                    <td>{candle.trading_date}</td>
                    <td>{formatPrice(candle.open)}</td>
                    <td>{formatPrice(candle.high)}</td>
                    <td>{formatPrice(candle.low)}</td>
                    <td>{formatPrice(candle.close)}</td>
                    <td>{formatNumber(candle.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Universe</p>
            <h2>Nifty 500 Constituents</h2>
          </div>
          <Database size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Active stocks" value={formatNumber(universeStatus?.active_count)} />
          <StatusRow label="Stored rows" value={formatNumber(universeStatus?.total_count)} />
          <StatusRow label="Industries" value={formatNumber(universeStatus?.industry_count)} />
          <StatusRow label="Last import" value={formatDate(universeStatus?.last_import?.completed_at)} />
          <StatusRow label="Source rows seen" value={formatNumber(universeStatus?.last_import?.total_rows_seen)} />
          <StatusRow label="Inserted" value={formatNumber(universeStatus?.last_import?.inserted_rows)} />
          <StatusRow label="Updated" value={formatNumber(universeStatus?.last_import?.updated_rows)} />
          <StatusRow label="Deactivated" value={formatNumber(universeStatus?.last_import?.deactivated_rows)} />
        </dl>

        {universeStatus?.last_import?.error ? <p className="error-text">{universeStatus.last_import.error}</p> : null}

        <div className="button-row">
          <button onClick={refreshUniverse} disabled={busy}>
            <RefreshCcw size={17} />
            Refresh Nifty 500
          </button>
        </div>

        <label className="search-label">
          Search Nifty 500 universe
          <div className="search-row">
            <input
              value={universeQuery}
              onChange={(event) => loadUniverse(event.target.value)}
              placeholder="RELIANCE, bank, Financial Services"
            />
            <button type="button" className="secondary" onClick={() => loadUniverse()} disabled={busy}>
              <Search size={17} />
            </button>
          </div>
        </label>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Industry</th>
                <th>Symbol</th>
                <th>Series</th>
                <th>ISIN</th>
              </tr>
            </thead>
            <tbody>
              {universeResults.length === 0 ? (
                <tr>
                  <td colSpan={5}>No constituents loaded.</td>
                </tr>
              ) : (
                universeResults.map((item) => (
                  <tr key={item.id}>
                    <td>{item.company_name || "-"}</td>
                    <td>{item.industry || "-"}</td>
                    <td>{item.symbol || "-"}</td>
                    <td>{item.series || "-"}</td>
                    <td>{item.isin || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel instruments-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Master Data</p>
            <h2>NSE Instrument Master</h2>
          </div>
          <Database size={22} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Active NSE equities" value={formatNumber(instrumentStatus?.active_nse_count)} />
          <StatusRow label="Stored NSE equities" value={formatNumber(instrumentStatus?.nse_count)} />
          <StatusRow label="Last import" value={formatDate(instrumentStatus?.last_import?.completed_at)} />
          <StatusRow label="Source rows seen" value={formatNumber(instrumentStatus?.last_import?.total_rows_seen)} />
          <StatusRow label="Inserted" value={formatNumber(instrumentStatus?.last_import?.inserted_rows)} />
          <StatusRow label="Updated" value={formatNumber(instrumentStatus?.last_import?.updated_rows)} />
          <StatusRow label="Unchanged" value={formatNumber(instrumentStatus?.last_import?.unchanged_rows)} />
          <StatusRow label="Deactivated" value={formatNumber(instrumentStatus?.last_import?.deactivated_rows)} />
        </dl>

        {instrumentStatus?.last_import?.error ? <p className="error-text">{instrumentStatus.last_import.error}</p> : null}

        <div className="button-row">
          <button onClick={refreshInstruments} disabled={busy}>
            <RefreshCcw size={17} />
            Refresh from Dhan
          </button>
        </div>

        <label className="search-label">
          Search stored NSE equities
          <div className="search-row">
            <input
              value={instrumentQuery}
              onChange={(event) => searchInstruments(event.target.value)}
              placeholder="RELIANCE, HDFCBANK, NIFTY"
            />
            <button type="button" className="secondary" onClick={() => searchInstruments()} disabled={busy}>
              <Search size={17} />
            </button>
          </div>
        </label>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Display</th>
                <th>Security ID</th>
                <th>ISIN</th>
                <th>Segment</th>
                <th>Type</th>
                <th>Series</th>
                <th>Lot</th>
              </tr>
            </thead>
            <tbody>
              {instrumentResults.length === 0 ? (
                <tr>
                  <td colSpan={8}>No search results.</td>
                </tr>
              ) : (
                instrumentResults.map((item) => (
                  <tr key={item.id}>
                    <td>{item.symbol_name || "-"}</td>
                    <td>{item.display_name || "-"}</td>
                    <td>{item.security_id || "-"}</td>
                    <td>{item.isin || "-"}</td>
                    <td>{item.segment || "-"}</td>
                    <td>{item.instrument_type || item.instrument || "-"}</td>
                    <td>{item.series || "-"}</td>
                    <td>{formatNumber(item.lot_size)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
        </>
      ) : null}
        </>
      )}

      {message ? <p className="message">{message}</p> : null}
    </main>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function getStateMeta(state: TokenState) {
  if (state === "active") {
    return { label: "Active", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  if (state === "expiring_soon") {
    return { label: "Expiring soon", className: "warn", icon: <Clock size={18} /> };
  }
  if (state === "missing") {
    return { label: "No token", className: "neutral", icon: <Shield size={18} /> };
  }
  if (state === "expired" || state === "renew_failed" || state === "config_error") {
    return { label: state.replace("_", " "), className: "bad", icon: <AlertTriangle size={18} /> };
  }
  return { label: "Unknown", className: "neutral", icon: <Clock size={18} /> };
}

function getGeminiStateMeta(state: GeminiKeyStatus["state"]) {
  if (state === "active") {
    return { label: "Gemini ready", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  if (state === "missing") {
    return { label: "No AI key", className: "neutral", icon: <Shield size={18} /> };
  }
  if (state === "validation_failed" || state === "config_error") {
    return { label: state.replace("_", " "), className: "bad", icon: <AlertTriangle size={18} /> };
  }
  return { label: "Unknown", className: "neutral", icon: <Clock size={18} /> };
}

function getSystemStateMeta(
  dhanState: TokenState,
  geminiState: GeminiKeyStatus["state"],
  historicalState?: string,
  blockedCount = 0,
) {
  if (dhanState === "expired" || dhanState === "renew_failed" || dhanState === "config_error") {
    return { label: "Dhan needs attention", className: "bad", icon: <AlertTriangle size={18} /> };
  }
  if (geminiState === "validation_failed" || geminiState === "config_error") {
    return { label: "AI needs attention", className: "bad", icon: <AlertTriangle size={18} /> };
  }
  if (blockedCount > 0 || historicalState === "failed") {
    return { label: "Data needs review", className: "warn", icon: <AlertTriangle size={18} /> };
  }
  if (dhanState === "active" && geminiState === "active") {
    return { label: "System ready", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  return { label: "Setup incomplete", className: "neutral", icon: <Clock size={18} /> };
}

function getSettingsStateMeta(
  dhanMeta: ReturnType<typeof getStateMeta>,
  geminiMeta: ReturnType<typeof getGeminiStateMeta>,
) {
  if (dhanMeta.className === "bad" || geminiMeta.className === "bad") {
    return { label: "Settings need attention", className: "bad", icon: <AlertTriangle size={18} /> };
  }
  if (dhanMeta.className === "ok" && geminiMeta.className === "ok") {
    return { label: "Settings ready", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  return { label: "Settings incomplete", className: "neutral", icon: <Shield size={18} /> };
}

function getPageMeta(page: AppPage) {
  if (page === "drishti") return { eyebrow: "Early Watch", title: "Drishti Radar" };
  if (page === "demo") return { eyebrow: "Paper Ledger", title: "Demo Trading" };
  if (page === "data") return { eyebrow: "Operations", title: "Data Health" };
  if (page === "settings") return { eyebrow: "Admin", title: "Settings" };
  return { eyebrow: "Overview", title: "Command Dashboard" };
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

function formatNumber(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("en-IN").format(value);
}

function formatPrice(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
}

function formatCurrency(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}%`;
}

function formatMultiplier(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}x`;
}

function formatIssues(value: string[]) {
  if (value.length === 0) return "-";
  return value.map((item) => item.replaceAll("_", " ")).join(", ");
}

function formatStatus(value?: string | null) {
  if (!value) return "-";
  return value.replaceAll("_", " ");
}

async function readError(response: Response) {
  try {
    const payload = await response.json();
    return payload.detail ?? "Request failed.";
  } catch {
    return "Request failed.";
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
