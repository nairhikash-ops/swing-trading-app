import { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, Database, FileText, RefreshCcw, Save, Shield, Wifi } from "lucide-react";
import "./styles.css";

type TokenState = "missing" | "active" | "expiring_soon" | "expired" | "renew_failed" | "config_error" | "unknown";
type DemoRow = Record<string, string | number | boolean | null>;

type Health = { status: string; app: string };

type DhanStatus = {
  has_token: boolean;
  dhan_client_id?: string | null;
  token_state: TokenState;
  expiry_time?: string | null;
  data_plan?: string | null;
  data_validity?: string | null;
  last_status_check_at?: string | null;
  last_renew_success_at?: string | null;
  last_error: string;
};

type FormState = {
  dhanClientId: string;
  accessToken: string;
  expiryTime: string;
  validateWithDhan: boolean;
};

type PaperStrategyStatus = {
  strategy_id: string;
  name: string;
  output_dir: string;
  latest: DemoRow | null;
  account: { cash: number; pending_orders_count: number; open_positions_count: number; closed_trades_count: number };
  pending_orders: DemoRow[];
  open_positions: DemoRow[];
  closed_trades: DemoRow[];
  order_ledger: DemoRow[];
  signals: DemoRow[];
  watch_candidates: DemoRow[];
  daily_reports: DemoRow[];
  signal_count_key: string;
  fetch_failures: { as_of_date?: string; symbols_requested?: number; symbols_loaded?: number; fetch_failures?: Record<string, string> };
  files: Record<string, { exists: boolean; path: string; size_bytes: number; updated_at?: number | null }>;
};

type PaperTradingStatus = {
  mode: string;
  leakage_guard: string;
  summary: {
    strategy_count: number;
    latest_dates: string[];
    total_cash: number;
    total_pending_orders: number;
    total_open_positions: number;
    total_closed_trades: number;
    total_signals_latest: number;
    total_watch_candidates_latest: number;
    total_orders_placed_latest: number;
  };
  strategies: PaperStrategyStatus[];
};

const API_BASE = import.meta.env.VITE_MATSYA_API_BASE_URL || "http://localhost:8020";

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<DhanStatus | null>(null);
  const [demoStatus, setDemoStatus] = useState<PaperTradingStatus | null>(null);
  const [form, setForm] = useState<FormState>({ dhanClientId: "", accessToken: "", expiryTime: "", validateWithDhan: true });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const statusTone = useMemo(() => toneForStatus(status?.token_state), [status]);

  useEffect(() => {
    void loadHealth();
    void loadStatus();
    void loadDemoStatus();
  }, []);

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed with ${response.status}`);
    return payload as T;
  }

  async function loadHealth() {
    try { setHealth(await request<Health>("/api/matsya/health")); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to reach Matsya API."); }
  }

  async function loadStatus() {
    try { setStatus(await request<DhanStatus>("/api/matsya/dhan/status")); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to load Dhan status."); }
  }

  async function loadDemoStatus() {
    try { setDemoStatus(await request<PaperTradingStatus>("/api/matsya/demo/paper-trading/status?limit=100")); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to load paper trading status."); }
  }

  async function saveToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const nextStatus = await request<DhanStatus>("/api/matsya/dhan/token", {
        method: "POST",
        body: JSON.stringify({
          dhan_client_id: form.dhanClientId.trim(),
          access_token: form.accessToken.trim(),
          expiry_time: form.expiryTime ? new Date(form.expiryTime).toISOString() : null,
          validate_with_dhan: form.validateWithDhan,
        }),
      });
      setStatus(nextStatus);
      setForm({ dhanClientId: "", accessToken: "", expiryTime: "", validateWithDhan: true });
      setMessage("Dhan token saved in Matsya. The token field was cleared.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save Dhan token.");
    } finally { setBusy(false); }
  }

  async function refreshStatus() {
    setBusy(true); setError(""); setMessage("");
    try {
      setStatus(await request<DhanStatus>("/api/matsya/dhan/status/refresh", { method: "POST" }));
      setMessage("Dhan status refreshed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to refresh Dhan status.");
    } finally { setBusy(false); }
  }

  async function renewToken() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<{ renewed: boolean; status: DhanStatus; message: string }>("/api/matsya/dhan/renew", { method: "POST" });
      setStatus(result.status);
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to renew Dhan token.");
    } finally { setBusy(false); }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div><p className="eyebrow">Matsya setup</p><h1>Matsya Dhan Setup</h1></div>
        <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}><Wifi size={18} />API {health?.status ?? "checking"}</div>
      </header>

      <section className="layout">
        <div className="panel">
          <div className="panel-heading">
            <div><p className="eyebrow">Status</p><h2>Dhan token status</h2></div>
            <div className={`pill ${statusTone}`}>{statusTone === "ok" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}{status?.token_state ?? "unknown"}</div>
          </div>
          <dl className="status-list">
            <StatusRow label="Matsya API" value={health?.app ?? "-"} />
            <StatusRow label="Has token" value={status?.has_token ? "Yes" : "No"} />
            <StatusRow label="Dhan Client ID" value={status?.dhan_client_id ?? "-"} />
            <StatusRow label="Expiry" value={formatDate(status?.expiry_time)} />
            <StatusRow label="Data plan" value={status?.data_plan ?? "-"} />
            <StatusRow label="Data validity" value={status?.data_validity ?? "-"} />
            <StatusRow label="Last checked" value={formatDate(status?.last_status_check_at)} />
            <StatusRow label="Last renew" value={formatDate(status?.last_renew_success_at)} />
          </dl>
          {status?.last_error ? <p className="error">{status.last_error}</p> : null}
          {message ? <p className="success">{message}</p> : null}
          {error ? <p className="error">{error}</p> : null}
          <div className="button-row">
            <button onClick={refreshStatus} disabled={busy || !status?.has_token}><RefreshCcw size={17} />Refresh Status</button>
            <button className="secondary" onClick={renewToken} disabled={busy || !status?.has_token}><Shield size={17} />Renew Token</button>
          </div>
        </div>

        <form className="panel" onSubmit={saveToken}>
          <div className="panel-heading"><div><p className="eyebrow">Credentials</p><h2>Store Dhan access</h2></div><Database size={22} /></div>
          <label>Dhan Client ID<input value={form.dhanClientId} onChange={(event) => setForm({ ...form, dhanClientId: event.target.value })} autoComplete="off" required /></label>
          <label>Dhan Access Token<input type="password" value={form.accessToken} onChange={(event) => setForm({ ...form, accessToken: event.target.value })} autoComplete="off" required /></label>
          <label>Expiry time optional<input type="datetime-local" value={form.expiryTime} onChange={(event) => setForm({ ...form, expiryTime: event.target.value })} /></label>
          <label className="check-row"><input type="checkbox" checked={form.validateWithDhan} onChange={(event) => setForm({ ...form, validateWithDhan: event.target.checked })} />Validate with Dhan before saving</label>
          <button type="submit" disabled={busy}><Save size={17} />Save / Validate</button>
        </form>
      </section>

      <DemoTraderPanel status={demoStatus} busy={busy} reload={loadDemoStatus} />

      <section className="panel future-panel">
        <div className="panel-heading"><div><p className="eyebrow">Future Matsya jobs</p><h2>Raw data actions</h2></div></div>
        <div className="button-row"><button disabled>Import Instruments</button><button disabled>Import Universe</button><button disabled>Fetch OHLCV</button></div>
      </section>
    </main>
  );
}

function DemoTraderPanel({ status, busy, reload }: { status: PaperTradingStatus | null; busy: boolean; reload: () => void }) {
  const summary = status?.summary;
  return (
    <section className="panel demo-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Forward paper trading</p><h2>Strategy Portfolio</h2></div>
        <button className="secondary" onClick={reload} disabled={busy}><RefreshCcw size={17} />Refresh</button>
      </div>
      <div className="demo-grid">
        <div><p className="eyebrow">Total account state</p><dl className="status-list"><StatusRow label="Strategies" value={formatDemo(summary?.strategy_count)} /><StatusRow label="Latest dates" value={summary?.latest_dates?.join(", ") || "-"} /><StatusRow label="Total cash" value={formatDemo(summary?.total_cash)} /><StatusRow label="Open positions" value={formatDemo(summary?.total_open_positions)} /><StatusRow label="Pending orders" value={formatDemo(summary?.total_pending_orders)} /><StatusRow label="Closed trades" value={formatDemo(summary?.total_closed_trades)} /></dl></div>
        <div><p className="eyebrow">Forward validation</p><dl className="status-list"><StatusRow label="Mode" value={status?.mode === "forward_paper_walk_forward" ? "Walk-forward paper only" : formatDemo(status?.mode)} /><StatusRow label="Leakage guard" value={status?.leakage_guard ?? "-"} /><StatusRow label="Watch candidates latest" value={formatDemo(summary?.total_watch_candidates_latest)} /><StatusRow label="Final signals latest" value={formatDemo(summary?.total_signals_latest)} /><StatusRow label="Pending orders created latest" value={formatDemo(summary?.total_orders_placed_latest)} /></dl></div>
      </div>
      {(status?.strategies ?? []).map((strategy) => (
        <StrategyPanel key={strategy.strategy_id} strategy={strategy} />
      ))}
    </section>
  );
}

function StrategyPanel({ strategy }: { strategy: PaperStrategyStatus }) {
  const latest = strategy.latest ?? null;
  const healthOk = latest?.matsya_token_state === "active" && Number(latest?.symbols_loaded ?? 0) === 500 && Number(latest?.fetch_failures ?? 0) === 0;
  const isSideways = strategy.strategy_id === "uptrend_sideways";
  return (
    <section className="panel-mini strategy-block">
      <div className="panel-heading">
        <div><p className="eyebrow">Individual strategy</p><h2>{strategy.name}</h2></div>
        <div className={`pill ${healthOk ? "ok" : "warn"}`}>{healthOk ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}{healthOk ? "healthy" : "needs review"}</div>
      </div>
      <div className="demo-grid">
        <div><p className="eyebrow">Paper account</p><dl className="status-list"><StatusRow label="Date" value={formatDemo(latest?.date)} /><StatusRow label="Broker" value={formatDemo(latest?.broker)} /><StatusRow label="Equity" value={formatDemo(latest?.equity)} /><StatusRow label="Cash" value={formatDemo(strategy.account.cash)} /><StatusRow label="Open positions" value={formatDemo(strategy.account.open_positions_count)} /><StatusRow label="Pending orders" value={formatDemo(strategy.account.pending_orders_count)} /></dl></div>
        <div><p className="eyebrow">Run health</p><dl className="status-list"><StatusRow label="Token" value={formatDemo(latest?.matsya_token_state)} /><StatusRow label="Latest candle" value={formatDemo(latest?.matsya_latest_candle_date)} /><StatusRow label="Symbols loaded" value={formatDemo(latest?.symbols_loaded)} /><StatusRow label="Fetch failures" value={formatDemo(latest?.fetch_failures)} /><StatusRow label="Watch candidates" value={formatDemo(latest?.watch_candidates)} /><StatusRow label="Final signals" value={formatDemo(latest?.[strategy.signal_count_key])} /><StatusRow label="Pending orders created" value={formatDemo(latest?.orders_placed)} /></dl></div>
      </div>
      <DemoTable title="Pending Orders" rows={strategy.pending_orders} columns={isSideways ? ["symbol", "signal_date", "target_allocation", "base_duration", "base_range_max", "base_high", "base_low", "target_price"] : ["symbol", "signal_date", "target_allocation", "liquidity_cap", "down_market_capture_60d"]} />
      <DemoTable title="Open Positions" rows={strategy.open_positions} columns={isSideways ? ["symbol", "entry_date", "shares", "entry_price", "base_high", "base_low", "target_price", "bars_held"] : ["symbol", "entry_date", "shares", "entry_price", "stop_price", "target_price", "bars_held"]} />
      <DemoTable title="Closed Trades" rows={strategy.closed_trades} columns={["symbol", "entry_date", "exit_date", "reason", "shares", "pnl_value", "pnl_pct", "realized_move_pct"]} />
      <DemoTable title="Latest Signals" rows={strategy.signals} columns={isSideways ? ["symbol", "as_of_date", "status", "base_duration", "base_range_max", "base_high", "base_low", "latest_close", "move_from_base_high_pct", "move_from_base_low_pct", "target_price"] : ["symbol", "as_of_date", "confirmation_date", "down_market_capture_60d", "liquidity_cap"]} />
      <DemoTable title="Watch Candidates" rows={strategy.watch_candidates} columns={isSideways ? ["symbol", "as_of_date", "status", "base_duration", "base_range_max", "base_high", "base_low", "latest_close", "move_from_base_high_pct", "move_from_base_low_pct"] : ["symbol", "as_of_date", "watch_reason", "crash_date", "days_since_crash", "reaction_high_price", "higher_low_price", "latest_close", "move_from_reaction_high_pct", "move_from_crash_low_pct", "move_from_higher_low_pct"]} />
      <DemoTable title="Daily Reports" rows={strategy.daily_reports} columns={isSideways ? ["date", "equity", "open_positions", "pending_orders", "watch_candidates", "breakout_signals", "orders_placed", "fetch_failures"] : ["date", "equity", "open_positions", "pending_orders", "watch_candidates", "eligible_signals", "orders_placed", "fetch_failures"]} />
      <div className="file-grid"><div><p className="eyebrow">Files</p><div className="file-title"><FileText size={18} /> {strategy.output_dir}</div><dl className="status-list">{Object.entries(strategy.files ?? {}).map(([name, meta]) => <StatusRow key={name} label={name.replaceAll("_", " ")} value={meta.exists ? `${formatDemo(meta.size_bytes)} bytes` : "missing"} />)}</dl></div></div>
    </section>
  );
}

function DemoTable({ title, rows, columns }: { title: string; rows: DemoRow[]; columns: string[] }) {
  return <div className="demo-table-block"><p className="eyebrow">{title}</p><div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.length === 0 ? <tr><td colSpan={columns.length}>No rows.</td></tr> : rows.map((row, index) => <tr key={`${title}-${index}`}>{columns.map((column) => <td key={column}>{formatDemo(row[column], column)}</td>)}</tr>)}</tbody></table></div></div>;
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div className="status-row"><dt>{label}</dt><dd>{value}</dd></div>;
}

function toneForStatus(state?: TokenState): "ok" | "warn" | "bad" {
  if (state === "active" || state === "expiring_soon") return "ok";
  if (state === "missing" || state === "unknown") return "warn";
  return "bad";
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatDemo(value: string | number | boolean | null | undefined, key = ""): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return isPercentColumn(key) ? formatPercent(value) : Math.abs(value) < 1 && value !== 0 ? value.toFixed(4) : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
  const parsed = Number(value);
  if (!Number.isNaN(parsed) && value.trim() !== "") return isPercentColumn(key) ? formatPercent(parsed) : Math.abs(parsed) < 1 && parsed !== 0 ? parsed.toFixed(4) : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(parsed);
  return value;
}

function isPercentColumn(key: string): boolean {
  return key.endsWith("_pct") || key.endsWith("_return") || key.includes("return_");
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

createRoot(document.getElementById("root")!).render(<App />);
