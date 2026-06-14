import { StrictMode, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
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

type AppPage = "dashboard" | "data" | "review" | "settings";

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
  data_api_active: boolean;
  historical_fetch_allowed: boolean;
  historical_block_reason: string;
  data_validity?: string | null;
  last_status_check_at?: string | null;
  last_renew_attempt_at?: string | null;
  last_renew_success_at?: string | null;
  last_error: string;
  token_source?: string | null;
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
    imported_rows: number;
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
};

type UniverseStatus = {
  index_name: string;
  total_count: number;
  active_count: number;
  industry_count: number;
  last_import?: {
    imported_rows: number;
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
  first_stored_candle_date?: string | null;
  latest_stored_candle_date?: string | null;
  source_floor_reached_count?: number;
  complete_available_history_count?: number;
  next_retry_after?: string | null;
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
  request_from_date?: string | null;
  request_to_date?: string | null;
  archive_status?: string;
  source_floor_reason?: string;
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
  first_stored_candle_date?: string | null;
  source_floor_reached: boolean;
  source_floor_date?: string | null;
  source_floor_reason: string;
  complete_available_history: boolean;
  next_retry_after?: string | null;
  archive_status: string;
  archive_message: string;
  effective_start_date?: string | null;
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
};

type RangeMoverReport = {
  generated_at: string;
  threshold_percent: number;
  from_date: string;
  to_date_exclusive: string;
  total_scanned: number;
  match_count: number;
  items: RangeMoverItem[];
};

type MoveEventItem = {
  id: number;
  symbol: string;
  company_name: string;
  industry: string;
  bucket: string;
  event_number: number;
  low_price: number;
  low_date: string;
  high_price: number;
  high_date: string;
  move_percent: number;
  duration_trading_sessions: number;
  duration_calendar_days: number;
};

type MoveEventReport = {
  generated_at: string;
  threshold_percent: number;
  pullback_percent: number;
  from_date: string;
  to_date_exclusive: string;
  scanned_symbols: number;
  candidate_symbols: number;
  event_count: number;
  error: string;
  items: MoveEventItem[];
};

type RegimeItem = {
  symbol: string;
  company_name: string;
  industry: string;
  isin: string;
  security_id: string;
  trading_date: string;
  close: number;
  regime: string;
  confidence: number;
};

type RegimeReport = {
  generated_at?: string | null;
  status: string;
  total_symbols: number;
  scanned_symbols: number;
  classified_count: number;
  uptrend_count: number;
  downtrend_count: number;
  sideways_count: number;
  error: string;
  items: RegimeItem[];
};

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "");
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
  const [regimeReport, setRegimeReport] = useState<RegimeReport | null>(null);
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

  const stateMeta = useMemo(() => getStateMeta(status?.state ?? "unknown"), [status?.state]);
  const dataApiBlocked = status ? !status.historical_fetch_allowed : false;

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
      if (instrumentQuery.trim()) await searchInstruments(instrumentQuery);
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
      if (data?.id && data.failed_count > 0) await loadHistoricalItems(data.id, "failed");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load historical fetch status.");
    }
  }

  async function startHistoricalFetch() {
    if (status && !status.historical_fetch_allowed) {
      setMessage(status.historical_block_reason || "Historical candle refresh is blocked.");
      return;
    }
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

  async function loadRegimes() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/regimes/nifty500/latest?limit=500`);
      if (!response.ok) throw new Error(await readError(response));
      setRegimeReport(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load regime diagnostics.");
    }
  }

  async function refreshRegimes() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/regimes/nifty500/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as RegimeReport;
      setRegimeReport(data);
      setMessage(`Regime review classified ${formatNumber(data.classified_count)} stock(s).`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh regime diagnostics.");
    } finally {
      setBusy(false);
    }
  }

  function changeRangeMoverThreshold(value: string) {
    const nextThreshold = Number(value);
    setRangeMoverThreshold(nextThreshold);
    void loadRangeMovers(nextThreshold);
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

  useEffect(() => {
    void loadStatus();
    void loadInstrumentStatus();
    void loadUniverseStatus();
    void loadUniverse();
    void loadHistoricalStatus();
    void loadQualityReport();
    void loadRangeMovers();
    void loadMoveEvents();
    void loadRegimes();
    const timer = window.setInterval(() => void loadStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!historicalStatus || !["queued", "running"].includes(historicalStatus.status)) return;
    const timer = window.setInterval(() => void loadHistoricalStatus(), 3_000);
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
    status?.historical_fetch_allowed ?? true,
    historicalStatus?.status,
    qualityReport?.blocked_count ?? 0,
  );
  const activeStatusMeta = activePage === "settings" ? getSettingsStateMeta(stateMeta) : systemStateMeta;
  const pageMeta = getPageMeta(activePage);
  const actionCount =
    (status?.state && !["active", "expiring_soon"].includes(status.state) ? 1 : 0) +
    (dataApiBlocked ? 1 : 0) +
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
            <TabButton label="Dashboard" page="dashboard" activePage={activePage} setActivePage={setActivePage} />
            <TabButton label="Data Health" page="data" activePage={activePage} setActivePage={setActivePage} />
            <TabButton label="Review Tools" page="review" activePage={activePage} setActivePage={setActivePage} />
            <TabButton label="Settings" page="settings" activePage={activePage} setActivePage={setActivePage} />
          </nav>
        </div>
      </section>

      {activePage === "dashboard" ? (
        <>
          <section className="dashboard-grid">
            <article className="hero-panel">
              <div>
                <p className="eyebrow">Data Foundation</p>
                <h2>Operations Dashboard</h2>
              </div>
              <dl className="hero-metrics">
                <StatusRow label="Dhan" value={formatStatus(status?.state)} />
                <StatusRow label="Data API" value={formatDataApiStatus(status)} />
                <StatusRow label="Nifty 500 active" value={formatNumber(universeStatus?.active_count)} />
                <StatusRow label="Historical progress" value={`${historicalProgress}%`} />
                <StatusRow label="Action items" value={formatNumber(actionCount)} />
              </dl>
              <div className="button-row">
                <button onClick={() => setActivePage("data")}>
                  <Database size={17} />
                  Inspect data
                </button>
                <button className="secondary" onClick={() => setActivePage("review")}>
                  <Search size={17} />
                  Review tools
                </button>
              </div>
            </article>

            <article className="dashboard-card">
              <div className="card-icon ok"><Wifi size={19} /></div>
              <p className="eyebrow">Connection</p>
              <h2>Dhan Feed</h2>
              <dl className="mini-list">
                <StatusRow label="Token" value={formatStatus(status?.state)} />
                <StatusRow label="Data API" value={formatDataApiStatus(status)} />
                <StatusRow label="Token expiry" value={formatDate(status?.expiry_time)} />
                <StatusRow label="Data plan" value={status?.data_plan ?? "-"} />
              </dl>
              {dataApiBlocked ? <p className="error-text">{dataApiWarning(status)}</p> : null}
              <button className="secondary" onClick={() => setActivePage("settings")}>
                Open settings
              </button>
            </article>

            <article className="dashboard-card">
              <div className="card-icon warn"><Database size={19} /></div>
              <p className="eyebrow">Storage</p>
              <h2>Nifty 500 Candles</h2>
              <dl className="mini-list">
                <StatusRow label="Historical" value={historicalStatus?.status ?? "-"} />
                <StatusRow label="Stored candles" value={formatNumber(historicalStatus?.stored_candle_count)} />
                <StatusRow label="Quality blocked" value={formatNumber(qualityReport?.blocked_count)} />
              </dl>
              <button className="secondary" onClick={() => setActivePage("data")}>
                Data health
              </button>
            </article>
          </section>

          <DataQualityPanel qualityReport={qualityReport} />
        </>
      ) : null}

      {activePage === "settings" ? (
        <SettingsPanel
          status={status}
          form={form}
          busy={busy}
          setForm={setForm}
          saveToken={saveToken}
          renewToken={renewToken}
          loadStatus={loadStatus}
        />
      ) : null}

      {activePage === "data" ? (
        <>
          <section className="grid instruments-panel">
            <StatusPanel
              title="Instrument Master"
              eyebrow="Dhan"
              icon={<Database size={22} />}
              rows={[
                ["Total", formatNumber(instrumentStatus?.total_count)],
                ["Active", formatNumber(instrumentStatus?.active_count)],
                ["Active NSE", formatNumber(instrumentStatus?.active_nse_count)],
                ["Last import", formatDate(instrumentStatus?.last_import?.completed_at)],
              ]}
              actions={[
                <button key="refresh" onClick={refreshInstruments} disabled={busy}>
                  <RefreshCcw size={17} />
                  Refresh instruments
                </button>,
              ]}
            />

            <StatusPanel
              title="Nifty 500 Universe"
              eyebrow="Universe"
              icon={<TrendingUp size={22} />}
              rows={[
                ["Active", formatNumber(universeStatus?.active_count)],
                ["Industries", formatNumber(universeStatus?.industry_count)],
                ["Last import", formatDate(universeStatus?.last_import?.completed_at)],
              ]}
              actions={[
                <button key="refresh" onClick={refreshUniverse} disabled={busy}>
                  <RefreshCcw size={17} />
                  Refresh universe
                </button>,
              ]}
            />
          </section>

          <HistoricalPanel
            tokenStatus={status}
            historicalStatus={historicalStatus}
            historicalItems={historicalItems}
            historicalProgress={historicalProgress}
            busy={busy}
            startHistoricalFetch={startHistoricalFetch}
            loadHistoricalStatus={loadHistoricalStatus}
            loadHistoricalItems={loadHistoricalItems}
          />

          <CandleLookup
            candleSymbol={candleSymbol}
            candles={candles}
            setCandleSymbol={setCandleSymbol}
            loadCandles={loadCandles}
          />

          <InstrumentAndUniverseSearch
            instrumentQuery={instrumentQuery}
            instrumentResults={instrumentResults}
            searchInstruments={searchInstruments}
            universeQuery={universeQuery}
            universeResults={universeResults}
            loadUniverse={loadUniverse}
          />

          <DataQualityPanel qualityReport={qualityReport} />
        </>
      ) : null}

      {activePage === "review" ? (
        <>
          <RangeMoversPanel
            report={rangeMoverReport}
            threshold={rangeMoverThreshold}
            busy={busy}
            changeRangeMoverThreshold={changeRangeMoverThreshold}
            loadRangeMovers={loadRangeMovers}
          />
          <MoveEventsPanel
            report={moveEventReport}
            busy={busy}
            refreshMoveEvents={refreshMoveEvents}
            loadMoveEvents={loadMoveEvents}
          />
          <RegimePanel report={regimeReport} busy={busy} refreshRegimes={refreshRegimes} loadRegimes={loadRegimes} />
        </>
      ) : null}

      {message ? <p className="message">{message}</p> : null}
    </main>
  );
}

function TabButton({
  label,
  page,
  activePage,
  setActivePage,
}: {
  label: string;
  page: AppPage;
  activePage: AppPage;
  setActivePage: (page: AppPage) => void;
}) {
  return (
    <button type="button" className={`page-tab ${activePage === page ? "active" : ""}`} onClick={() => setActivePage(page)}>
      {label}
    </button>
  );
}

function SettingsPanel({
  status,
  form,
  busy,
  setForm,
  saveToken,
  renewToken,
  loadStatus,
}: {
  status: TokenStatus | null;
  form: { dhanClientId: string; accessToken: string; expiryTime: string; validateWithDhan: boolean };
  busy: boolean;
  setForm: (form: { dhanClientId: string; accessToken: string; expiryTime: string; validateWithDhan: boolean }) => void;
  saveToken: (event: FormEvent<HTMLFormElement>) => void;
  renewToken: () => void;
  loadStatus: (refresh?: boolean) => void;
}) {
  return (
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
          <StatusRow label="Dhan token" value={formatStatus(status?.state)} />
          <StatusRow label="Dhan data API" value={formatDataApiStatus(status)} />
          <StatusRow label="Historical fetch" value={status?.historical_fetch_allowed ? "Allowed" : "Blocked"} />
          <StatusRow label="Client ID" value={status?.dhan_client_id ?? "-"} />
          <StatusRow label="Stored token" value={status?.masked_token ?? "-"} />
          <StatusRow label="Token source" value={status?.token_source ?? "-"} />
          <StatusRow label="Expiry" value={formatDate(status?.expiry_time)} />
          <StatusRow label="Minutes left" value={formatNumber(status?.minutes_to_expiry)} />
          <StatusRow label="Data plan" value={status?.data_plan ?? "-"} />
          <StatusRow label="Active segment" value={status?.active_segment ?? "-"} />
          <StatusRow label="Last renew" value={formatDate(status?.last_renew_success_at)} />
        </dl>

        {status && !status.historical_fetch_allowed ? <p className="error-text">{dataApiWarning(status)}</p> : null}
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
  );
}

function StatusPanel({
  title,
  eyebrow,
  icon,
  rows,
  actions,
}: {
  title: string;
  eyebrow: string;
  icon: ReactNode;
  rows: [string, string][];
  actions?: ReactNode[];
}) {
  return (
    <section className="panel status-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        {icon}
      </div>
      <dl className="status-list">
        {rows.map(([label, value]) => (
          <StatusRow key={label} label={label} value={value} />
        ))}
      </dl>
      {actions?.length ? <div className="button-row">{actions}</div> : null}
    </section>
  );
}

function HistoricalPanel({
  tokenStatus,
  historicalStatus,
  historicalItems,
  historicalProgress,
  busy,
  startHistoricalFetch,
  loadHistoricalStatus,
  loadHistoricalItems,
}: {
  tokenStatus: TokenStatus | null;
  historicalStatus: HistoricalStatus | null;
  historicalItems: HistoricalItem[];
  historicalProgress: number;
  busy: boolean;
  startHistoricalFetch: () => void;
  loadHistoricalStatus: () => void;
  loadHistoricalItems: (runId?: number, itemStatus?: string) => void;
}) {
  const historicalBlocked = tokenStatus ? !tokenStatus.historical_fetch_allowed : false;
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Historical Candles</p>
          <h2>Nifty 500 OHLCV Storage</h2>
        </div>
        <Database size={22} />
      </div>
      <dl className="status-list compact">
        <StatusRow label="Dhan data API" value={formatDataApiStatus(tokenStatus)} />
        <StatusRow label="Historical fetch" value={historicalBlocked ? "Blocked" : "Allowed"} />
        <StatusRow label="Status" value={historicalStatus?.status ?? "-"} />
        <StatusRow label="Run ID" value={formatNumber(historicalStatus?.id)} />
        <StatusRow label="Progress" value={`${historicalProgress}%`} />
        <StatusRow label="Mapped symbols" value={formatNumber(historicalStatus?.mapped_symbols)} />
        <StatusRow label="Done" value={formatNumber(historicalStatus?.done_count)} />
        <StatusRow label="Failed" value={formatNumber(historicalStatus?.failed_count)} />
        <StatusRow label="Stored candles" value={formatNumber(historicalStatus?.stored_candle_count)} />
        <StatusRow label="First stored date" value={historicalStatus?.first_stored_candle_date ?? "-"} />
        <StatusRow label="Latest stored date" value={historicalStatus?.latest_stored_candle_date ?? "-"} />
        <StatusRow label="Source floor reached" value={formatNumber(historicalStatus?.source_floor_reached_count)} />
        <StatusRow label="Complete available" value={formatNumber(historicalStatus?.complete_available_history_count)} />
        <StatusRow label="Next retry" value={formatDate(historicalStatus?.next_retry_after)} />
        <StatusRow label="Window" value={`${historicalStatus?.from_date ?? "-"} to ${historicalStatus?.to_date_exclusive ?? "-"}`} />
      </dl>
      {historicalBlocked ? <p className="error-text">{dataApiWarning(tokenStatus)}</p> : null}
      {historicalStatus?.error ? <p className="error-text">{historicalStatus.error}</p> : null}
      <div className="button-row">
        <button onClick={startHistoricalFetch} disabled={busy || historicalBlocked}>
          <RefreshCcw size={17} />
          Start/resume Nifty 500 fetch
        </button>
        <button className="secondary" onClick={loadHistoricalStatus} disabled={busy}>
          <Wifi size={17} />
          Reload status
        </button>
        {historicalStatus?.id ? (
          <button className="secondary" onClick={() => loadHistoricalItems(historicalStatus.id, "failed")} disabled={busy}>
            <AlertTriangle size={17} />
            Show failures
          </button>
        ) : null}
      </div>
      {historicalItems.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Candles</th>
                <th>Request</th>
                <th>Archive</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {historicalItems.map((item) => (
                <tr key={item.id}>
                  <td>{item.symbol}</td>
                  <td>{formatStatus(item.status)}</td>
                  <td>{formatNumber(item.attempts)}</td>
                  <td>{formatNumber(item.candles_received)}</td>
                  <td>{item.request_from_date ? `${item.request_from_date} to ${item.request_to_date ?? "-"}` : "-"}</td>
                  <td>{formatStatus(item.archive_status || item.source_floor_reason || "-")}</td>
                  <td>{item.error || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function CandleLookup({
  candleSymbol,
  candles,
  setCandleSymbol,
  loadCandles,
}: {
  candleSymbol: string;
  candles: DailyCandle[];
  setCandleSymbol: (symbol: string) => void;
  loadCandles: (symbol?: string) => void;
}) {
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Stored OHLCV</p>
          <h2>Latest Candles</h2>
        </div>
        <Search size={22} />
      </div>
      <form
        className="search-row"
        onSubmit={(event) => {
          event.preventDefault();
          loadCandles();
        }}
      >
        <input value={candleSymbol} onChange={(event) => setCandleSymbol(event.target.value)} placeholder="RELIANCE" />
        <button type="submit">
          <Search size={17} />
          Load candles
        </button>
      </form>
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
            {candles.length === 0 ? (
              <tr>
                <td colSpan={6}>No candles loaded.</td>
              </tr>
            ) : (
              candles.map((candle) => (
                <tr key={candle.trading_date}>
                  <td>{candle.trading_date}</td>
                  <td>{formatPrice(candle.open)}</td>
                  <td>{formatPrice(candle.high)}</td>
                  <td>{formatPrice(candle.low)}</td>
                  <td>{formatPrice(candle.close)}</td>
                  <td>{formatNumber(candle.volume)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InstrumentAndUniverseSearch({
  instrumentQuery,
  instrumentResults,
  searchInstruments,
  universeQuery,
  universeResults,
  loadUniverse,
}: {
  instrumentQuery: string;
  instrumentResults: InstrumentItem[];
  searchInstruments: (query?: string) => void;
  universeQuery: string;
  universeResults: UniverseItem[];
  loadUniverse: (query?: string) => void;
}) {
  const [instrumentDraft, setInstrumentDraft] = useState(instrumentQuery);
  const [universeDraft, setUniverseDraft] = useState(universeQuery);

  return (
    <section className="grid instruments-panel">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Dhan Master</p>
            <h2>Instrument Search</h2>
          </div>
          <Search size={22} />
        </div>
        <form
          className="search-row"
          onSubmit={(event) => {
            event.preventDefault();
            searchInstruments(instrumentDraft);
          }}
        >
          <input value={instrumentDraft} onChange={(event) => setInstrumentDraft(event.target.value)} placeholder="RELIANCE" />
          <button type="submit">
            <Search size={17} />
            Search
          </button>
        </form>
        <div className="table-wrap compact-table">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Security</th>
                <th>ISIN</th>
                <th>Series</th>
              </tr>
            </thead>
            <tbody>
              {instrumentResults.length === 0 ? (
                <tr>
                  <td colSpan={4}>Search for an instrument.</td>
                </tr>
              ) : (
                instrumentResults.map((item) => (
                  <tr key={item.id}>
                    <td>{item.display_name || item.symbol_name}</td>
                    <td>{item.security_id}</td>
                    <td>{item.isin}</td>
                    <td>{item.series || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Universe</p>
            <h2>Nifty 500 Constituents</h2>
          </div>
          <Search size={22} />
        </div>
        <form
          className="search-row"
          onSubmit={(event) => {
            event.preventDefault();
            loadUniverse(universeDraft);
          }}
        >
          <input value={universeDraft} onChange={(event) => setUniverseDraft(event.target.value)} placeholder="INFY" />
          <button type="submit">
            <Search size={17} />
            Search
          </button>
        </form>
        <div className="table-wrap compact-table">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Company</th>
                <th>Industry</th>
                <th>ISIN</th>
              </tr>
            </thead>
            <tbody>
              {universeResults.length === 0 ? (
                <tr>
                  <td colSpan={4}>No constituents loaded.</td>
                </tr>
              ) : (
                universeResults.slice(0, 25).map((item) => (
                  <tr key={item.id}>
                    <td>{item.symbol}</td>
                    <td>{item.company_name}</td>
                    <td>{item.industry}</td>
                    <td>{item.isin}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function DataQualityPanel({ qualityReport }: { qualityReport: QualityReport | null }) {
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Data Quality</p>
          <h2>Nifty 500 Exceptions</h2>
        </div>
        <AlertTriangle size={22} />
      </div>
      <dl className="status-list compact">
        <StatusRow label="Historical run" value={qualityReport?.historical_run_status ?? "-"} />
        <StatusRow label="Expected sessions" value={formatNumber(qualityReport?.expected_session_count)} />
        <StatusRow label="Healthy" value={formatNumber(qualityReport?.healthy_count)} />
        <StatusRow label="Warnings" value={formatNumber(qualityReport?.warning_count)} />
        <StatusRow label="Blocked" value={formatNumber(qualityReport?.blocked_count)} />
        <StatusRow label="Generated" value={formatDate(qualityReport?.generated_at)} />
      </dl>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Symbol</th>
              <th>Archive</th>
              <th>First</th>
              <th>Latest</th>
              <th>Candles</th>
              <th>Missing</th>
              <th>Source floor</th>
              <th>Issues</th>
              <th>Fetch</th>
            </tr>
          </thead>
          <tbody>
            {!qualityReport || qualityReport.items.length === 0 ? (
              <tr>
                <td colSpan={10}>No data quality exceptions.</td>
              </tr>
            ) : (
              qualityReport.items.map((item) => (
                <tr key={item.symbol}>
                  <td>{formatStatus(item.quality_status)}</td>
                  <td>{item.symbol}</td>
                  <td>{item.archive_message || formatStatus(item.archive_status)}</td>
                  <td>{item.first_stored_candle_date ?? "-"}</td>
                  <td>{item.latest_candle_date ?? "-"}</td>
                  <td>{formatNumber(item.candle_count)}</td>
                  <td>{formatNumber(item.missing_sessions)}</td>
                  <td>{item.source_floor_reached ? formatStatus(item.source_floor_reason) : "-"}</td>
                  <td>{formatIssues(item.issues)}</td>
                  <td>{item.fetch_error || formatStatus(item.fetch_status)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RangeMoversPanel({
  report,
  threshold,
  busy,
  changeRangeMoverThreshold,
  loadRangeMovers,
}: {
  report: RangeMoverReport | null;
  threshold: number;
  busy: boolean;
  changeRangeMoverThreshold: (value: string) => void;
  loadRangeMovers: () => void;
}) {
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Review Tool</p>
          <h2>45-Day Upward Move Above {threshold}%</h2>
        </div>
        <TrendingUp size={22} />
      </div>
      <dl className="status-list compact">
        <StatusRow label="Matches" value={formatNumber(report?.match_count)} />
        <StatusRow label="Scanned" value={formatNumber(report?.total_scanned)} />
        <StatusRow label="Threshold" value={formatPercent(report?.threshold_percent)} />
        <StatusRow label="Window" value={`${report?.from_date ?? "-"} to ${report?.to_date_exclusive ?? "-"}`} />
      </dl>
      <div className="button-row">
        <label className="inline-control">
          Minimum upward move
          <select value={threshold} onChange={(event) => changeRangeMoverThreshold(event.target.value)}>
            {rangeMoverThresholdOptions.map((value) => (
              <option key={value} value={value}>
                {value}%
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={loadRangeMovers} disabled={busy}>
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
            {!report || report.items.length === 0 ? (
              <tr>
                <td colSpan={9}>No stocks crossed the threshold.</td>
              </tr>
            ) : (
              report.items.map((item) => (
                <tr key={item.symbol}>
                  <td>
                    <a className="table-action" href={dhanTradingViewUrl(item)} target="_blank" rel="noreferrer">
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
  );
}

function MoveEventsPanel({
  report,
  busy,
  refreshMoveEvents,
  loadMoveEvents,
}: {
  report: MoveEventReport | null;
  busy: boolean;
  refreshMoveEvents: () => void;
  loadMoveEvents: () => void;
}) {
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Review Tool</p>
          <h2>45-Day Candidate Events</h2>
        </div>
        <Search size={22} />
      </div>
      <dl className="status-list compact">
        <StatusRow label="Events" value={formatNumber(report?.event_count)} />
        <StatusRow label="Candidate stocks" value={formatNumber(report?.candidate_symbols)} />
        <StatusRow label="Scanned" value={formatNumber(report?.scanned_symbols)} />
        <StatusRow label="Threshold" value={formatPercent(report?.threshold_percent)} />
        <StatusRow label="Pullback split" value={formatPercent(report?.pullback_percent)} />
      </dl>
      {report?.error ? <p className="error-text">{report.error}</p> : null}
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
              <th>Bucket</th>
              <th>Low</th>
              <th>Low date</th>
              <th>High</th>
              <th>High date</th>
              <th>Move</th>
              <th>Sessions</th>
            </tr>
          </thead>
          <tbody>
            {!report || report.items.length === 0 ? (
              <tr>
                <td colSpan={9}>No stored candidate events.</td>
              </tr>
            ) : (
              report.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.symbol}</td>
                  <td>{item.company_name}</td>
                  <td>{item.bucket}</td>
                  <td>{formatPrice(item.low_price)}</td>
                  <td>{item.low_date}</td>
                  <td>{formatPrice(item.high_price)}</td>
                  <td>{item.high_date}</td>
                  <td>{formatPercent(item.move_percent)}</td>
                  <td>{formatNumber(item.duration_trading_sessions)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RegimePanel({
  report,
  busy,
  refreshRegimes,
  loadRegimes,
}: {
  report: RegimeReport | null;
  busy: boolean;
  refreshRegimes: () => void;
  loadRegimes: () => void;
}) {
  return (
    <section className="panel instruments-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Review Tool</p>
          <h2>Regime Diagnostics</h2>
        </div>
        <Database size={22} />
      </div>
      <dl className="status-list compact">
        <StatusRow label="Status" value={report?.status ?? "-"} />
        <StatusRow label="Classified" value={formatNumber(report?.classified_count)} />
        <StatusRow label="Uptrend" value={formatNumber(report?.uptrend_count)} />
        <StatusRow label="Downtrend" value={formatNumber(report?.downtrend_count)} />
        <StatusRow label="Sideways" value={formatNumber(report?.sideways_count)} />
      </dl>
      {report?.error ? <p className="error-text">{report.error}</p> : null}
      <div className="button-row">
        <button onClick={refreshRegimes} disabled={busy}>
          <RefreshCcw size={17} />
          Refresh regimes
        </button>
        <button className="secondary" onClick={loadRegimes} disabled={busy}>
          <Wifi size={17} />
          Reload latest
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Company</th>
              <th>Regime</th>
              <th>Confidence</th>
              <th>Close</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {!report || report.items.length === 0 ? (
              <tr>
                <td colSpan={6}>No regime diagnostics loaded.</td>
              </tr>
            ) : (
              report.items.slice(0, 100).map((item) => (
                <tr key={`${item.symbol}-${item.trading_date}`}>
                  <td>{item.symbol}</td>
                  <td>{item.company_name}</td>
                  <td>{formatStatus(item.regime)}</td>
                  <td>{formatPercent(item.confidence)}</td>
                  <td>{formatPrice(item.close)}</td>
                  <td>{item.trading_date}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
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

function getSystemStateMeta(dhanState: TokenState, historicalFetchAllowed: boolean, historicalState?: string, blockedCount = 0) {
  if (dhanState === "expired" || dhanState === "renew_failed" || dhanState === "config_error") {
    return { label: "Dhan needs attention", className: "bad", icon: <AlertTriangle size={18} /> };
  }
  if (!historicalFetchAllowed) {
    return { label: "Data API inactive", className: "warn", icon: <AlertTriangle size={18} /> };
  }
  if (blockedCount > 0 || historicalState === "failed") {
    return { label: "Data needs review", className: "warn", icon: <AlertTriangle size={18} /> };
  }
  if (dhanState === "active" || dhanState === "expiring_soon") {
    return { label: "Data system ready", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  return { label: "Setup incomplete", className: "neutral", icon: <Clock size={18} /> };
}

function getSettingsStateMeta(dhanMeta: ReturnType<typeof getStateMeta>) {
  if (dhanMeta.className === "bad") {
    return { label: "Settings need attention", className: "bad", icon: <AlertTriangle size={18} /> };
  }
  if (dhanMeta.className === "ok" || dhanMeta.className === "warn") {
    return { label: "Settings ready", className: "ok", icon: <CheckCircle2 size={18} /> };
  }
  return { label: "Settings incomplete", className: "neutral", icon: <Shield size={18} /> };
}

function getPageMeta(page: AppPage) {
  if (page === "data") return { eyebrow: "Operations", title: "Data Health" };
  if (page === "review") return { eyebrow: "Diagnostics", title: "Review Tools" };
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

function formatPercent(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}%`;
}

function formatIssues(value: string[]) {
  if (value.length === 0) return "-";
  return value.map((item) => item.replaceAll("_", " ")).join(", ");
}

function formatStatus(value?: string | null) {
  if (!value) return "-";
  return value.replaceAll("_", " ");
}

function formatDataApiStatus(status?: TokenStatus | null) {
  if (!status) return "-";
  if (status.data_api_active) return "Active";
  if (status.state === "active") return "Inactive / Renewal pending";
  return "Blocked";
}

function dataApiWarning(status?: TokenStatus | null) {
  if (status?.historical_block_reason === "Dhan token is not active.") return status.historical_block_reason;
  return "Dhan data API is inactive or pending renewal. Historical candle refresh is blocked until renewal is complete.";
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
