import { StrictMode, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, Clock, Database, RefreshCcw, Save, Search, Shield, Wifi } from "lucide-react";
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

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  configuredApiBaseUrl && configuredApiBaseUrl.length > 0
    ? configuredApiBaseUrl
    : `${window.location.protocol}//${window.location.hostname}:8000`;

function App() {
  const [status, setStatus] = useState<TokenStatus | null>(null);
  const [instrumentStatus, setInstrumentStatus] = useState<InstrumentStatus | null>(null);
  const [instrumentResults, setInstrumentResults] = useState<InstrumentItem[]>([]);
  const [instrumentQuery, setInstrumentQuery] = useState("");
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
    const timer = window.setInterval(() => loadStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, []);

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
