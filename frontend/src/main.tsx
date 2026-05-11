import { StrictMode, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Database,
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

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  configuredApiBaseUrl && configuredApiBaseUrl.length > 0
    ? configuredApiBaseUrl
    : `${window.location.protocol}//${window.location.hostname}:8000`;
const rangeMoverThresholdOptions = [10, 15, 20, 30, 40, 50];

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
  const [rangeMoverThreshold, setRangeMoverThreshold] = useState(20);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    dhanClientId: "",
    accessToken: "",
    expiryTime: "",
    validateWithDhan: true,
  });

  const stateMeta = useMemo(() => getStateMeta(status?.state ?? "unknown"), [status?.state]);

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

  useEffect(() => {
    loadStatus();
    loadInstrumentStatus();
    loadUniverseStatus();
    loadUniverse();
    loadHistoricalStatus();
    loadQualityReport();
    loadRangeMovers();
    loadMoveEvents();
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

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Stage 1</p>
          <h1>Dhan Token Control</h1>
        </div>
        <div className={`status-pill ${stateMeta.className}`}>
          {stateMeta.icon}
          <span>{stateMeta.label}</span>
        </div>
      </section>

      <section className="grid">
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
                  <td colSpan={8}>No stocks crossed the threshold.</td>
                </tr>
              ) : (
                rangeMoverReport.items.map((item) => (
                  <tr key={item.symbol}>
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
