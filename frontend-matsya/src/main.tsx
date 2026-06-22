import { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, CheckCircle2, Database, RefreshCcw, Save, Shield, Wifi } from "lucide-react";
import "./styles.css";

type TokenState = "missing" | "active" | "expiring_soon" | "expired" | "renew_failed" | "config_error" | "unknown";

type Health = {
  status: string;
  app: string;
};

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

const API_BASE = import.meta.env.VITE_MATSYA_API_BASE_URL || "http://localhost:8020";

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<DhanStatus | null>(null);
  const [form, setForm] = useState<FormState>({
    dhanClientId: "",
    accessToken: "",
    expiryTime: "",
    validateWithDhan: true,
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const statusTone = useMemo(() => toneForStatus(status?.token_state), [status]);

  useEffect(() => {
    void loadHealth();
    void loadStatus();
  }, []);

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `Request failed with ${response.status}`);
    }
    return payload as T;
  }

  async function loadHealth() {
    try {
      setHealth(await request<Health>("/api/matsya/health"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach Matsya API.");
    }
  }

  async function loadStatus() {
    try {
      setStatus(await request<DhanStatus>("/api/matsya/dhan/status"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load Dhan status.");
    }
  }

  async function saveToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
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
    } finally {
      setBusy(false);
    }
  }

  async function refreshStatus() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setStatus(await request<DhanStatus>("/api/matsya/dhan/status/refresh", { method: "POST" }));
      setMessage("Dhan status refreshed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to refresh Dhan status.");
    } finally {
      setBusy(false);
    }
  }

  async function renewToken() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await request<{ renewed: boolean; status: DhanStatus; message: string }>("/api/matsya/dhan/renew", {
        method: "POST",
      });
      setStatus(result.status);
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to renew Dhan token.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Matsya setup</p>
          <h1>Matsya Dhan Setup</h1>
        </div>
        <div className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>
          <Wifi size={18} />
          API {health?.status ?? "checking"}
        </div>
      </header>

      <section className="layout">
        <div className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Status</p>
              <h2>Dhan token status</h2>
            </div>
            <div className={`pill ${statusTone}`}>
              {statusTone === "ok" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
              {status?.token_state ?? "unknown"}
            </div>
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
            <button onClick={refreshStatus} disabled={busy || !status?.has_token}>
              <RefreshCcw size={17} />
              Refresh Status
            </button>
            <button className="secondary" onClick={renewToken} disabled={busy || !status?.has_token}>
              <Shield size={17} />
              Renew Token
            </button>
          </div>
        </div>

        <form className="panel" onSubmit={saveToken}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Credentials</p>
              <h2>Store Dhan access</h2>
            </div>
            <Database size={22} />
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
            Dhan Access Token
            <input
              type="password"
              value={form.accessToken}
              onChange={(event) => setForm({ ...form, accessToken: event.target.value })}
              autoComplete="off"
              required
            />
          </label>

          <label>
            Expiry time optional
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
            Validate with Dhan before saving
          </label>

          <button type="submit" disabled={busy}>
            <Save size={17} />
            Save / Validate
          </button>
        </form>
      </section>

      <section className="panel future-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Future Matsya jobs</p>
            <h2>Raw data actions</h2>
          </div>
        </div>
        <div className="button-row">
          <button disabled>Import Instruments</button>
          <button disabled>Import Universe</button>
          <button disabled>Fetch OHLCV</button>
        </div>
      </section>
    </main>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function toneForStatus(state?: TokenState): "ok" | "warn" | "bad" {
  if (state === "active" || state === "expiring_soon") return "ok";
  if (state === "missing" || state === "unknown") return "warn";
  return "bad";
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

createRoot(document.getElementById("root")!).render(<App />);
