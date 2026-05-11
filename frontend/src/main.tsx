import { StrictMode, useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import { createRoot } from "react-dom/client";
import { Database, FolderSearch, RefreshCcw, Search, Upload } from "lucide-react";
import "./styles.css";

type ImportFileResult = {
  filename: string;
  status: string;
  trade_date?: string | null;
  row_count: number;
  error: string;
  file_id?: number | null;
  existing_file_id?: number | null;
};

type ImportStatus = {
  generated_at: string;
  target_sessions: number;
  inbox_path: string;
  published_session_count: number;
  coverage_percent: number;
  latest_published_date?: string | null;
  next_missing_date?: string | null;
  next_missing_filename?: string | null;
  rejected_file_count: number;
  schema_error_count: number;
  row_count: number;
  symbol_count: number;
  recent_files: {
    id: number;
    original_filename: string;
    trade_date: string;
    status: string;
    row_count: number;
    error: string;
    uploaded_at: string;
  }[];
  recent_dates: {
    trade_date: string;
    status: string;
    row_count: number;
    error: string;
    updated_at: string;
    published_at?: string | null;
  }[];
};

type Coverage = {
  generated_at: string;
  target_sessions: number;
  published_session_count: number;
  coverage_percent: number;
  latest_published_date?: string | null;
  row_count: number;
  symbol_count: number;
  series_counts: Record<string, number>;
};

type BhavcopyRow = {
  trade_date: string;
  symbol: string;
  series: string;
  prev_close: number;
  open_price: number;
  high_price: number;
  low_price: number;
  last_price: number;
  close_price: number;
  avg_price: number;
  traded_quantity: number;
  turnover_lacs: number;
  no_of_trades: number;
  delivery_qty?: number | null;
  delivery_percent?: number | null;
};

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  configuredApiBaseUrl && configuredApiBaseUrl.length > 0
    ? configuredApiBaseUrl
    : `${window.location.protocol}//${window.location.hostname}:8000`;

function App() {
  const [status, setStatus] = useState<ImportStatus | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [importResults, setImportResults] = useState<ImportFileResult[]>([]);
  const [symbol, setSymbol] = useState("RELIANCE");
  const [rows, setRows] = useState<BhavcopyRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const coverageWidth = useMemo(() => Math.min(coverage?.coverage_percent ?? 0, 100), [coverage?.coverage_percent]);

  async function loadStatus() {
    try {
      const [statusResponse, coverageResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/bhavcopy/import/status`),
        fetch(`${apiBaseUrl}/api/bhavcopy/coverage`),
      ]);
      if (!statusResponse.ok) throw new Error(await readError(statusResponse));
      if (!coverageResponse.ok) throw new Error(await readError(coverageResponse));
      setStatus(await statusResponse.json());
      setCoverage(await coverageResponse.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load bhavcopy status.");
    }
  }

  async function scanFolder() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/bhavcopy/import/scan`, { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setImportResults(data.files ?? []);
      setMessage(
        `Scan accepted ${formatNumber(data.accepted_count)} file(s), skipped ${formatNumber(
          data.duplicate_count,
        )} duplicate(s), published ${formatNumber(data.published_dates_count)} date(s).`,
      );
      await loadStatus();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to scan folder.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadSelected(files = uploadFiles) {
    if (files.length === 0) {
      setMessage("Choose bhavcopy CSV files first.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));
      const response = await fetch(`${apiBaseUrl}/api/bhavcopy/import/upload`, { method: "POST", body: formData });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setImportResults(data.files ?? []);
      setUploadFiles([]);
      setMessage(
        `Upload accepted ${formatNumber(data.accepted_count)} file(s), skipped ${formatNumber(
          data.duplicate_count,
        )} duplicate(s), published ${formatNumber(data.published_dates_count)} date(s).`,
      );
      await loadStatus();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to upload files.");
    } finally {
      setBusy(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files).filter((file) => file.name.toLowerCase().endsWith(".csv"));
    setUploadFiles(files);
    if (files.length > 0) {
      uploadSelected(files);
    }
  }

  async function loadRows(nextSymbol = symbol) {
    const trimmed = nextSymbol.trim();
    setSymbol(nextSymbol);
    if (!trimmed) {
      setRows([]);
      return;
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/bhavcopy/rows?symbol=${encodeURIComponent(trimmed)}&limit=30`);
      if (!response.ok) throw new Error(await readError(response));
      setRows(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load rows.");
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Full Bhavcopy Only</p>
          <h1>Bhavcopy Import</h1>
        </div>
        <button className="secondary" onClick={loadStatus} disabled={busy}>
          <RefreshCcw size={17} />
          Refresh
        </button>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Coverage</p>
            <h2>Stored Trading Sessions</h2>
          </div>
          <Database size={22} />
        </div>

        <div className="progress-track" aria-label="Coverage progress">
          <span style={{ width: `${coverageWidth}%` }} />
        </div>

        <dl className="status-list compact">
          <StatusRow label="Published sessions" value={formatNumber(coverage?.published_session_count)} />
          <StatusRow label="Target sessions" value={formatNumber(coverage?.target_sessions)} />
          <StatusRow label="Coverage" value={formatPercent(coverage?.coverage_percent)} />
          <StatusRow label="Latest date" value={coverage?.latest_published_date ?? "-"} />
          <StatusRow label="Rows" value={formatNumber(coverage?.row_count)} />
          <StatusRow label="Symbols" value={formatNumber(coverage?.symbol_count)} />
          <StatusRow label="Rejected files" value={formatNumber(status?.rejected_file_count)} />
          <StatusRow label="Schema errors" value={formatNumber(status?.schema_error_count)} />
        </dl>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Import</p>
            <h2>Bhavcopy Files</h2>
          </div>
          <FolderSearch size={22} />
        </div>

        <label>
          Server import folder
          <input value={status?.inbox_path ?? "-"} readOnly />
        </label>

        <div className="request-box">
          <p className="eyebrow">Next Requested File</p>
          <strong>{status?.next_missing_filename ?? "Upload any Full Bhavcopy file to begin"}</strong>
          <span>
            {status?.next_missing_date
              ? `Requested date: ${status.next_missing_date}. If you upload a different valid Full Bhavcopy, it will still be saved under its actual file date.`
              : "The app will start asking for one missing date after the first valid file is stored."}
          </span>
        </div>

        <div className="button-row">
          <button onClick={scanFolder} disabled={busy}>
            <FolderSearch size={17} />
            Scan folder
          </button>
          <button className="secondary" onClick={loadStatus} disabled={busy}>
            <RefreshCcw size={17} />
            Check status
          </button>
        </div>

        <label className="drop-zone" onDrop={handleDrop} onDragOver={(event) => event.preventDefault()}>
          <Upload size={20} />
          <span>{uploadFiles.length > 0 ? `${uploadFiles.length} file(s) selected` : "Drop bhavcopy CSV files here"}</span>
          <input
            type="file"
            multiple
            accept=".csv"
            onChange={(event) => setUploadFiles(Array.from(event.target.files ?? []))}
          />
        </label>

        <div className="button-row">
          <button className="secondary" onClick={() => uploadSelected()} disabled={busy || uploadFiles.length === 0}>
            <Upload size={17} />
            Upload selected files
          </button>
        </div>

        {importResults.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Date</th>
                  <th>Rows</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {importResults.map((item) => (
                  <tr key={`${item.filename}-${item.file_id ?? item.existing_file_id ?? item.status}`}>
                    <td>{item.filename}</td>
                    <td>{item.status}</td>
                    <td>{item.trade_date ?? "-"}</td>
                    <td>{formatNumber(item.row_count)}</td>
                    <td>{item.error || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Inspect</p>
            <h2>Stored Rows</h2>
          </div>
          <Search size={22} />
        </div>

        <label>
          Symbol
          <div className="search-row">
            <input value={symbol} onChange={(event) => loadRows(event.target.value)} placeholder="RELIANCE" />
            <button type="button" className="secondary" onClick={() => loadRows()} disabled={busy}>
              <Search size={17} />
            </button>
          </div>
        </label>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Symbol</th>
                <th>Series</th>
                <th>Open</th>
                <th>High</th>
                <th>Low</th>
                <th>Close</th>
                <th>Volume</th>
                <th>Delivery %</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={9}>No rows loaded.</td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={`${row.trade_date}-${row.symbol}-${row.series}`}>
                    <td>{row.trade_date}</td>
                    <td>{row.symbol}</td>
                    <td>{row.series}</td>
                    <td>{formatPrice(row.open_price)}</td>
                    <td>{formatPrice(row.high_price)}</td>
                    <td>{formatPrice(row.low_price)}</td>
                    <td>{formatPrice(row.close_price)}</td>
                    <td>{formatNumber(row.traded_quantity)}</td>
                    <td>{formatPercent(row.delivery_percent)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Recent</p>
            <h2>Imported Dates</h2>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Status</th>
                <th>Rows</th>
                <th>Published</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {!status || status.recent_dates.length === 0 ? (
                <tr>
                  <td colSpan={5}>No dates imported yet.</td>
                </tr>
              ) : (
                status.recent_dates.map((item) => (
                  <tr key={item.trade_date}>
                    <td>{item.trade_date}</td>
                    <td>{item.status}</td>
                    <td>{formatNumber(item.row_count)}</td>
                    <td>{formatDate(item.published_at)}</td>
                    <td>{item.error || "-"}</td>
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
