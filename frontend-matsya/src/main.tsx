import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Database,
  RefreshCcw,
  Save,
  Settings,
  Shield,
  Target,
  TrendingUp,
  Wallet,
  Wifi,
} from "lucide-react";
import "./styles.css";

type TokenState = "missing" | "active" | "expiring_soon" | "expired" | "renew_failed" | "config_error" | "unknown";
type DemoRow = Record<string, string | number | boolean | null>;
type ViewId = "overview" | string;

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

type PaperAccount = {
  cash: number;
  starting_equity: number;
  equity: number;
  open_value: number;
  cost_basis: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  return_pct: number;
  exposure_pct: number;
  pending_orders_count: number;
  open_positions_count: number;
  closed_trades_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  average_win_pct: number;
  average_loss_pct: number;
  profit_factor?: number | null;
  max_drawdown_pct: number;
};

type PaperStrategyStatus = {
  strategy_id: string;
  name: string;
  output_dir: string;
  latest: DemoRow | null;
  account: PaperAccount;
  pending_orders: DemoRow[];
  open_positions: DemoRow[];
  closed_trades: DemoRow[];
  order_ledger: DemoRow[];
  signals: DemoRow[];
  watch_candidates: DemoRow[];
  daily_reports: DemoRow[];
  signal_count_key: string;
  schedule?: string | null;
  last_run_at?: string | null;
  fetch_failures: { as_of_date?: string; symbols_requested?: number; symbols_loaded?: number; fetch_failures?: Record<string, string> };
  files: Record<string, { exists: boolean; path: string; size_bytes: number; updated_at?: number | null }>;
};

type PaperTradingStatus = {
  mode: string;
  leakage_guard: string;
  summary: {
    strategy_count: number;
    latest_dates: string[];
    starting_equity: number;
    total_equity: number;
    total_cash: number;
    total_open_value: number;
    total_cost_basis: number;
    total_realized_pnl: number;
    total_unrealized_pnl: number;
    total_pnl: number;
    total_return_pct: number;
    total_pending_orders: number;
    total_open_positions: number;
    total_closed_trades: number;
    total_signals_latest: number;
    total_watch_candidates_latest: number;
    total_orders_placed_latest: number;
  };
  strategies: PaperStrategyStatus[];
};

type OhlcvResponse = {
  symbol: string;
  candles: Array<{ trading_date: string; close: number }>;
};

const API_BASE = import.meta.env.VITE_MATSYA_API_BASE_URL || "http://localhost:8020";

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<DhanStatus | null>(null);
  const [demoStatus, setDemoStatus] = useState<PaperTradingStatus | null>(null);
  const [form, setForm] = useState<FormState>({ dhanClientId: "", accessToken: "", expiryTime: "", validateWithDhan: true });
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [lastDashboardRefresh, setLastDashboardRefresh] = useState<Date | null>(null);
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
    setDemoBusy(true);
    try {
      const next = await request<PaperTradingStatus>("/api/matsya/demo/paper-trading/status?limit=100");
      setDemoStatus(await enrichOpenPositions(next, request));
      setLastDashboardRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load paper trading status.");
    } finally {
      setDemoBusy(false);
    }
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
        <div>
          <p className="eyebrow">Matsya trading lab</p>
          <h1>Demo Portfolio</h1>
          <p className="subtitle">Forward-only paper trading, with strategy performance and risk in one view.</p>
        </div>
        <div className="header-pills">
          <div className="pill demo"><Shield size={17} />Demo only</div>
          <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}><Wifi size={17} />API {health?.status ?? "checking"}</div>
        </div>
      </header>

      {error ? <p className="error notice">{error}</p> : null}

      <DemoTraderPanel
        status={demoStatus}
        busy={demoBusy}
        reload={loadDemoStatus}
        refreshedAt={lastDashboardRefresh}
      />

      <details className="panel settings-panel">
        <summary><span><Settings size={19} />System &amp; Dhan settings</span><small>Token, API and maintenance controls</small></summary>
        <div className="settings-content">
          <section className="settings-card">
            <div className="panel-heading">
              <div><p className="eyebrow">Matsya Dhan Setup</p><h2>Dhan token status</h2></div>
              <div className={`pill ${statusTone}`}>{statusTone === "ok" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}{status?.token_state ?? "unknown"}</div>
            </div>
            <dl className="status-list">
              <StatusRow label="Matsya API" value={health?.app ?? "-"} />
              <StatusRow label="Has token" value={status?.has_token ? "Yes" : "No"} />
              <StatusRow label="Dhan Client ID" value={status?.dhan_client_id ?? "-"} />
              <StatusRow label="Expiry" value={formatDate(status?.expiry_time)} />
              <StatusRow label="Data plan" value={status?.data_plan ?? "-"} />
              <StatusRow label="Data validity" value={status?.data_validity ?? "-"} />
              <StatusRow label="Last checked" value={formatDate(status?.last_status_check_at)} />
              <StatusRow label="Last renewal" value={formatDate(status?.last_renew_success_at)} />
            </dl>
            {status?.last_error ? <p className="error">{status.last_error}</p> : null}
            {message ? <p className="success">{message}</p> : null}
            <div className="button-row">
              <button onClick={refreshStatus} disabled={busy || !status?.has_token}><RefreshCcw size={17} />Refresh status</button>
              <button className="secondary" onClick={renewToken} disabled={busy || !status?.has_token}><Shield size={17} />Renew token</button>
            </div>
          </section>

          <form className="settings-card" onSubmit={saveToken}>
            <div className="panel-heading"><div><p className="eyebrow">Credentials</p><h2>Store Dhan access</h2></div><Database size={22} /></div>
            <label>Dhan Client ID<input value={form.dhanClientId} onChange={(event) => setForm({ ...form, dhanClientId: event.target.value })} autoComplete="off" required /></label>
            <label>Dhan Access Token<input type="password" value={form.accessToken} onChange={(event) => setForm({ ...form, accessToken: event.target.value })} autoComplete="off" required /></label>
            <label>Expiry time optional<input type="datetime-local" value={form.expiryTime} onChange={(event) => setForm({ ...form, expiryTime: event.target.value })} /></label>
            <label className="check-row"><input type="checkbox" checked={form.validateWithDhan} onChange={(event) => setForm({ ...form, validateWithDhan: event.target.checked })} />Validate with Dhan before saving</label>
            <button type="submit" disabled={busy}><Save size={17} />Save / Validate</button>
          </form>
        </div>
        <section className="maintenance-card">
          <div><p className="eyebrow">Reserved maintenance jobs</p><h3>Raw data actions</h3></div>
          <div className="button-row"><button disabled>Import Instruments</button><button disabled>Import Universe</button><button disabled>Fetch OHLCV</button></div>
        </section>
      </details>
    </main>
  );
}

function DemoTraderPanel({ status, busy, reload, refreshedAt }: { status: PaperTradingStatus | null; busy: boolean; reload: () => void; refreshedAt: Date | null }) {
  const [activeView, setActiveView] = useState<ViewId>("overview");
  const summary = status?.summary;
  const strategies = status?.strategies ?? [];
  const selected = strategies.find((strategy) => strategy.strategy_id === activeView);
  const allOpenPositions = strategies.flatMap((strategy) => strategy.open_positions);
  const allClosedTrades = strategies.flatMap((strategy) => strategy.closed_trades);
  const portfolioReports = aggregatePortfolioReports(strategies);

  return (
    <section className="dashboard">
      <div className="dashboard-heading">
        <div>
          <p className="eyebrow">Forward paper trading</p>
          <h2>Strategy portfolio</h2>
          <p className="section-note">Two independent ₹1 lakh paper ledgers. Totals below combine them for analysis only.</p>
        </div>
        <div className="refresh-block">
          <span>Updated {refreshedAt ? formatTime(refreshedAt) : "-"}</span>
          <button className="secondary" onClick={reload} disabled={busy}><RefreshCcw className={busy ? "spin" : ""} size={17} />Refresh</button>
        </div>
      </div>

      <nav className="view-tabs" aria-label="Dashboard views">
        <button className={activeView === "overview" ? "active" : ""} onClick={() => setActiveView("overview")}>Portfolio overview</button>
        {strategies.map((strategy) => (
          <button key={strategy.strategy_id} className={activeView === strategy.strategy_id ? "active" : ""} onClick={() => setActiveView(strategy.strategy_id)}>{shortStrategyName(strategy)}</button>
        ))}
      </nav>

      {activeView === "overview" ? (
        <>
          <div className="metric-grid portfolio-metrics">
            <MetricCard label="Starting capital" value={formatCurrency(summary?.starting_equity)} icon={<Wallet size={19} />} />
            <MetricCard label="Current equity" value={formatCurrency(summary?.total_equity)} sub={formatSignedPercent(summary?.total_return_pct)} tone={toneForNumber(summary?.total_pnl)} icon={<TrendingUp size={19} />} />
            <MetricCard label="Total P&L" value={formatSignedCurrency(summary?.total_pnl)} sub={`${formatSignedCurrency(summary?.total_realized_pnl)} realized`} tone={toneForNumber(summary?.total_pnl)} icon={<BarChart3 size={19} />} />
            <MetricCard label="Capital deployed" value={formatCurrency(summary?.total_open_value)} sub={`${summary?.total_open_positions ?? 0} open positions`} icon={<Target size={19} />} />
            <MetricCard label="Available cash" value={formatCurrency(summary?.total_cash)} sub={`${summary?.total_pending_orders ?? 0} pending orders`} icon={<Wallet size={19} />} />
            <MetricCard label="Today’s opportunity set" value={`${formatCount(summary?.total_signals_latest)} signals`} sub={`${formatCount(summary?.total_watch_candidates_latest)} watch candidates`} icon={<Activity size={19} />} />
          </div>

          <div className="overview-grid">
            <EquityCurve reports={portfolioReports} title="Combined equity curve" />
            <section className="insight-card">
              <p className="eyebrow">Validation contract</p>
              <h3>What these numbers mean</h3>
              <div className="validation-list">
                <div><CheckCircle2 size={17} /><span>Walk-forward paper execution only</span></div>
                <div><CheckCircle2 size={17} /><span>{status?.leakage_guard ?? "Date-locked candles"}</span></div>
                <div><CheckCircle2 size={17} /><span>Entries fill at the next session open</span></div>
              </div>
              <p className="muted">This is a research ledger, not a broker balance and not a live-order screen.</p>
            </section>
          </div>

          <div className="strategy-summary-grid">
            {strategies.map((strategy) => <StrategySummary key={strategy.strategy_id} strategy={strategy} onOpen={() => setActiveView(strategy.strategy_id)} />)}
          </div>

          <DemoTable
            title="All open positions"
            description="Latest mark-to-market is estimated from Matsya’s most recent stored close."
            rows={allOpenPositions}
            columns={["strategy", "symbol", "entry_date", "shares", "entry_price", "current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct", "target_price", "distance_to_target_pct", "bars_held"]}
            emptyMessage="No open paper positions."
          />
          <DemoTable
            title="Recently closed trades"
            rows={allClosedTrades.slice(-20).reverse()}
            columns={["strategy", "symbol", "entry_date", "exit_date", "reason", "shares", "pnl_value", "pnl_pct", "bars_held"]}
            emptyMessage="No completed paper trades yet."
          />
        </>
      ) : selected ? <StrategyPanel strategy={selected} /> : null}
    </section>
  );
}

function StrategySummary({ strategy, onOpen }: { strategy: PaperStrategyStatus; onOpen: () => void }) {
  const account = strategy.account;
  const healthy = strategyHealthOk(strategy);
  return (
    <button className="strategy-summary" onClick={onOpen}>
      <span className="strategy-summary-top"><strong>{strategy.name}</strong><span className={`health-dot ${healthy ? "ok" : "warn"}`}>{healthy ? "Run healthy" : "Needs review"}</span></span>
      <span className="strategy-summary-value">{formatCurrency(account.equity)}</span>
      <span className={`strategy-summary-return ${toneForNumber(account.total_pnl)}`}>{formatSignedCurrency(account.total_pnl)} · {formatSignedPercent(account.return_pct)}</span>
      <span className="strategy-summary-meta">{account.open_positions_count} open · {strategy.signals.length} signals loaded · {strategy.watch_candidates.length} watches loaded</span>
    </button>
  );
}

function StrategyPanel({ strategy }: { strategy: PaperStrategyStatus }) {
  const latest = strategy.latest ?? null;
  const account = strategy.account;
  const healthy = strategyHealthOk(strategy);
  const isSideways = strategy.strategy_id === "uptrend_sideways";
  const openColumns = isSideways
    ? ["symbol", "entry_date", "shares", "entry_price", "current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct", "base_low", "target_price", "distance_to_target_pct", "bars_held"]
    : ["symbol", "entry_date", "shares", "entry_price", "current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct", "stop_price", "target_price", "distance_to_target_pct", "bars_held"];
  const signalColumns = isSideways
    ? ["symbol", "as_of_date", "status", "latest_close", "base_high", "move_from_base_high_pct", "target_price"]
    : ["symbol", "as_of_date", "status", "latest_close", "reaction_high_price", "higher_low_price", "target_price"];
  const watchColumns = isSideways
    ? ["symbol", "as_of_date", "status", "latest_close", "base_high", "move_from_base_high_pct", "pre_structure_return_60d", "target_price"]
    : ["symbol", "as_of_date", "watch_reason", "latest_close", "reaction_high_price", "distance_to_reaction_high_pct", "liquidity_pass"];

  return (
    <section className="strategy-detail">
      <div className="strategy-title-row">
        <div><p className="eyebrow">Individual paper ledger</p><h2>{strategy.name}</h2></div>
        <div className={`pill ${healthy ? "ok" : "warn"}`}>{healthy ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}{healthy ? "Run healthy" : "Needs review"}</div>
      </div>

      <div className="schedule-strip">
        <span><CalendarClock size={17} /><strong>Schedule:</strong> {strategy.schedule ?? "-"}</span>
        <span><Activity size={17} /><strong>Last run:</strong> {formatDate(strategy.last_run_at)}</span>
        <span><Database size={17} /><strong>Market data:</strong> {formatDemo(latest?.matsya_latest_candle_date)}</span>
      </div>

      <div className="metric-grid">
        <MetricCard label="Equity" value={formatCurrency(account.equity)} sub={`${formatSignedPercent(account.return_pct)} total return`} tone={toneForNumber(account.total_pnl)} />
        <MetricCard label="Total P&L" value={formatSignedCurrency(account.total_pnl)} sub={`${formatSignedCurrency(account.realized_pnl)} realized`} tone={toneForNumber(account.total_pnl)} />
        <MetricCard label="Unrealized P&L" value={formatSignedCurrency(account.unrealized_pnl)} sub={`${formatPercent(account.exposure_pct)} exposure`} tone={toneForNumber(account.unrealized_pnl)} />
        <MetricCard label="Win rate" value={formatPercent(account.win_rate)} sub={`${account.wins} wins · ${account.losses} losses`} />
        <MetricCard label="Max drawdown" value={formatSignedPercent(account.max_drawdown_pct)} sub={`${account.closed_trades_count} closed trades`} tone={toneForNumber(account.max_drawdown_pct)} />
        <MetricCard label="Available cash" value={formatCurrency(account.cash)} sub={`${account.open_positions_count} open · ${account.pending_orders_count} pending`} />
      </div>

      <div className="overview-grid">
        <EquityCurve reports={strategy.daily_reports} title="Ledger equity" />
        <section className="insight-card">
          <p className="eyebrow">Run health, not performance</p>
          <h3>{healthy ? "Latest run completed cleanly" : "Latest run needs attention"}</h3>
          <dl className="status-list compact">
            <StatusRow label="Report date" value={formatDemo(latest?.date)} />
            <StatusRow label="Token" value={formatDemo(latest?.matsya_token_state)} />
            <StatusRow label="Symbols loaded" value={formatDemo(latest?.symbols_loaded)} />
            <StatusRow label="Fetch failures" value={formatDemo(latest?.fetch_failures)} />
            <StatusRow label="Signals latest" value={formatDemo(latest?.[strategy.signal_count_key])} />
            <StatusRow label="Orders created latest" value={formatDemo(latest?.orders_placed)} />
          </dl>
        </section>
      </div>

      <DemoTable title="Open positions" description="Current prices are latest stored closes; unrealized P&L is indicative before exit friction." rows={strategy.open_positions} columns={openColumns} emptyMessage="No open paper positions." />
      <DemoTable title="New signals" description="Date-locked candidates that satisfied the strategy’s entry rules." rows={strategy.signals.slice(-30).reverse()} columns={signalColumns} emptyMessage="No qualifying signals in the loaded window." />
      <DemoTable title="Watch candidates" description="Research watchlist only—not orders and not trade recommendations." rows={strategy.watch_candidates.slice(-30).reverse()} columns={watchColumns} emptyMessage="No watch candidates in the loaded window." />
      <DemoTable title="Pending entry orders" rows={strategy.pending_orders} columns={isSideways ? ["symbol", "signal_date", "target_allocation", "base_high", "base_low", "target_price"] : ["symbol", "signal_date", "target_allocation", "liquidity_cap", "down_market_capture_60d"]} emptyMessage="No orders waiting for the next session open." />
      <DemoTable title="Order history" rows={strategy.order_ledger.slice(-30).reverse()} columns={isSideways ? ["symbol", "signal_date", "target_allocation", "base_duration", "base_range_max", "base_high", "base_low", "target_price"] : ["symbol", "signal_date", "target_allocation", "liquidity_cap", "down_market_capture_60d"]} emptyMessage="No paper entry orders have been created." />
      <DemoTable title="Closed trades" rows={strategy.closed_trades.slice(-30).reverse()} columns={["symbol", "entry_date", "exit_date", "reason", "shares", "entry_price", "exit_price", "pnl_value", "pnl_pct", "bars_held"]} emptyMessage="No completed paper trades yet." />
    </section>
  );
}

function MetricCard({ label, value, sub, tone = "", icon }: { label: string; value: string; sub?: string; tone?: string; icon?: ReactNode }) {
  return (
    <article className="metric-card">
      <div className="metric-label"><span>{label}</span>{icon}</div>
      <strong className={tone}>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </article>
  );
}

function EquityCurve({ reports, title }: { reports: DemoRow[]; title: string }) {
  const values = reports.map((row) => Number(row.equity)).filter((value) => Number.isFinite(value) && value > 0);
  const width = 560;
  const height = 150;
  const padding = 12;
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const range = Math.max(max - min, max * 0.002, 1);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? width / 2 : padding + index * ((width - padding * 2) / (values.length - 1));
    const y = height - padding - ((value - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");
  return (
    <section className="chart-card">
      <div className="chart-heading"><div><p className="eyebrow">Performance</p><h3>{title}</h3></div><div className="chart-value"><strong>{formatCurrency(values.at(-1))}</strong><span>{values.length} report days</span></div></div>
      {values.length ? (
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} from ${formatCurrency(values[0])} to ${formatCurrency(values.at(-1))}`}>
          <defs><linearGradient id={`equity-${title.replaceAll(" ", "-")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1c8a68" stopOpacity="0.28" /><stop offset="100%" stopColor="#1c8a68" stopOpacity="0" /></linearGradient></defs>
          <polyline className="equity-area" points={`${padding},${height - padding} ${points} ${width - padding},${height - padding}`} fill={`url(#equity-${title.replaceAll(" ", "-")})`} />
          <polyline className="equity-line" points={points} />
        </svg>
      ) : <div className="empty-chart">Equity history will appear after the first paper report.</div>}
      <div className="chart-axis"><span>{formatDemo(reports[0]?.date)}</span><span>{formatDemo(reports.at(-1)?.date)}</span></div>
    </section>
  );
}

function DemoTable({ title, description, rows, columns, emptyMessage }: { title: string; description?: string; rows: DemoRow[]; columns: string[]; emptyMessage: string }) {
  const mobileTitleColumn = columns.includes("symbol") ? "symbol" : columns[0];
  const mobileContextColumn = columns.includes("strategy") ? "strategy" : columns.find((column) => ["as_of_date", "signal_date", "entry_date", "exit_date"].includes(column));
  const mobileHighlightColumns = mobileColumns(columns).filter((column) => column !== mobileTitleColumn && column !== mobileContextColumn);
  const mobileDetailColumns = columns.filter((column) => column !== mobileTitleColumn && column !== mobileContextColumn && !mobileHighlightColumns.includes(column));
  return (
    <section className="table-card">
      <div className="table-heading"><div><h3>{title}</h3>{description ? <p>{description}</p> : null}</div><span className="row-count">{rows.length} rows</span></div>
      <div className="table-wrap">
        <table>
          <thead><tr>{columns.map((column) => <th key={column}>{columnLabel(column)}</th>)}</tr></thead>
          <tbody>{rows.length === 0 ? <tr><td className="empty-row" colSpan={columns.length}>{emptyMessage}</td></tr> : rows.map((row, index) => <tr key={`${title}-${String(row.symbol ?? index)}-${index}`}>{columns.map((column) => <td key={column} className={cellTone(column, row[column])}>{formatDemo(row[column], column)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <div className="mobile-table-list">
        {rows.length === 0 ? <p className="mobile-empty-row">{emptyMessage}</p> : rows.map((row, index) => (
          <article className="mobile-row-card" key={`mobile-${title}-${String(row.symbol ?? index)}-${index}`}>
            <div className="mobile-row-heading">
              <div>
                {mobileContextColumn ? <span>{formatDemo(row[mobileContextColumn], mobileContextColumn)}</span> : null}
                <strong>{formatDemo(row[mobileTitleColumn], mobileTitleColumn)}</strong>
              </div>
              {columns.includes("status") ? <span className="mobile-status">{formatDemo(row.status, "status")}</span> : null}
            </div>
            <dl className="mobile-row-highlights">
              {mobileHighlightColumns.map((column) => <MobileDatum key={column} column={column} value={row[column]} />)}
            </dl>
            {mobileDetailColumns.length ? (
              <details className="mobile-row-details">
                <summary>All details</summary>
                <dl>{mobileDetailColumns.map((column) => <MobileDatum key={column} column={column} value={row[column]} />)}</dl>
              </details>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function MobileDatum({ column, value }: { column: string; value: DemoRow[string] }) {
  return <div><dt>{columnLabel(column)}</dt><dd className={cellTone(column, value)}>{formatDemo(value, column)}</dd></div>;
}

function mobileColumns(columns: string[]): string[] {
  const priority = [
    "current_price", "latest_close", "market_value", "unrealized_pnl", "unrealized_pnl_pct",
    "pnl_value", "pnl_pct", "target_price", "distance_to_target_pct", "entry_price", "target_allocation",
    "as_of_date", "signal_date", "entry_date", "exit_date", "reason", "watch_reason", "shares",
  ];
  return priority.filter((column) => columns.includes(column)).slice(0, 4);
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div className="status-row"><dt>{label}</dt><dd>{value}</dd></div>;
}

async function enrichOpenPositions(status: PaperTradingStatus, request: <T>(path: string, options?: RequestInit) => Promise<T>): Promise<PaperTradingStatus> {
  const symbols = Array.from(new Set(status.strategies.flatMap((strategy) => strategy.open_positions.map((row) => String(row.symbol || "")).filter(Boolean))));
  const quotes = new Map<string, number>();
  await Promise.all(symbols.map(async (symbol) => {
    try {
      const result = await request<OhlcvResponse>(`/api/matsya/market-data/ohlcv/latest?symbol=${encodeURIComponent(symbol)}&days=1`);
      const close = Number(result.candles.at(-1)?.close);
      if (Number.isFinite(close) && close > 0) quotes.set(symbol, close);
    } catch {
      // A missing quote should not hide the rest of the paper dashboard.
    }
  }));
  return {
    ...status,
    strategies: status.strategies.map((strategy) => ({
      ...strategy,
      open_positions: strategy.open_positions.map((row) => enrichPosition(row, quotes.get(String(row.symbol || "")))),
    })),
  };
}

function enrichPosition(row: DemoRow, currentPrice?: number): DemoRow {
  if (!currentPrice) return row;
  const shares = Number(row.shares || 0);
  const entryPrice = Number(row.entry_price || 0);
  const invested = Number(row.invested_value || shares * entryPrice);
  const marketValue = shares * currentPrice;
  const target = Number(row.target_price || 0);
  return {
    ...row,
    current_price: currentPrice,
    market_value: marketValue,
    unrealized_pnl: marketValue - invested,
    unrealized_pnl_pct: invested > 0 ? marketValue / invested - 1 : 0,
    distance_to_target_pct: target > 0 ? target / currentPrice - 1 : null,
  };
}

function aggregatePortfolioReports(strategies: PaperStrategyStatus[]): DemoRow[] {
  const dates = new Map<string, number>();
  for (const strategy of strategies) {
    for (const report of strategy.daily_reports) {
      const date = String(report.date || "");
      const equity = Number(report.equity || 0);
      if (date && equity > 0) dates.set(date, (dates.get(date) || 0) + equity);
    }
  }
  return Array.from(dates, ([date, equity]) => ({ date, equity })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function strategyHealthOk(strategy: PaperStrategyStatus): boolean {
  const latest = strategy.latest;
  return latest?.matsya_token_state === "active" && Number(latest?.symbols_loaded ?? 0) === 500 && Number(latest?.fetch_failures ?? 0) === 0;
}

function shortStrategyName(strategy: PaperStrategyStatus): string {
  return strategy.strategy_id === "v8_demo" ? "V8 reversal" : "Uptrend sideways";
}

function toneForStatus(state?: TokenState): "ok" | "warn" | "bad" {
  if (state === "active" || state === "expiring_soon") return "ok";
  if (state === "missing" || state === "unknown") return "warn";
  return "bad";
}

function toneForNumber(value?: number | null): string {
  if (!value) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function cellTone(key: string, value: DemoRow[string]): string {
  if (["pnl_value", "pnl_pct", "unrealized_pnl", "unrealized_pnl_pct", "realized_move_pct"].includes(key)) return toneForNumber(Number(value || 0));
  if (key === "status") return "status-cell";
  return "";
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(parsed);
}

function formatTime(value: Date): string {
  return new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Asia/Kolkata" }).format(value);
}

function formatDemo(value: string | number | boolean | null | undefined, key = ""): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isNaN(numeric) && String(value).trim() !== "") {
    if (isPercentColumn(key)) return formatPercent(numeric);
    if (isCurrencyColumn(key)) return formatCurrency(numeric);
    return Math.abs(numeric) < 1 && numeric !== 0 ? numeric.toFixed(4) : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(numeric);
  }
  return String(value).replaceAll("_", " ");
}

function formatCurrency(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
}

function formatSignedCurrency(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const formatted = formatCurrency(Math.abs(value));
  return value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted;
}

function formatPercent(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(2)}%`;
}

function formatSignedPercent(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${value > 0 ? "+" : ""}${formatPercent(value)}`;
}

function formatCount(value?: number | null): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value ?? 0);
}

function isPercentColumn(key: string): boolean {
  return key.endsWith("_pct") || key.endsWith("_return") || key.includes("return_") || key === "base_range_max";
}

function isCurrencyColumn(key: string): boolean {
  return ["equity", "cash", "open_value", "cost_basis", "target_allocation", "entry_price", "exit_price", "current_price", "market_value", "invested_value", "pnl_value", "unrealized_pnl", "base_high", "base_low", "target_price", "stop_price", "latest_close", "reaction_high_price", "higher_low_price"].includes(key);
}

function columnLabel(key: string): string {
  const labels: Record<string, string> = {
    as_of_date: "As of",
    signal_date: "Signal date",
    entry_date: "Entry date",
    exit_date: "Exit date",
    target_allocation: "Allocation",
    current_price: "Latest close",
    market_value: "Market value",
    unrealized_pnl: "Unrealized P&L",
    unrealized_pnl_pct: "Unrealized %",
    pnl_value: "Realized P&L",
    pnl_pct: "Return",
    distance_to_target_pct: "To target",
    move_from_base_high_pct: "From base high",
    pre_structure_return_60d: "Prior 60d return",
    down_market_capture_60d: "Down capture 60d",
    base_range_max: "Max base range",
    bars_held: "Sessions held",
  };
  return labels[key] || key.replaceAll("_", " ");
}

createRoot(document.getElementById("root")!).render(<App />);
