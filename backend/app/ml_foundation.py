import json
from typing import Any

from app.config import Settings
from app.store import TokenStore
from app.timezone import now_utc


ML_MODEL_NAME = "stock_opportunity_ohlcv_v1"
ML_LABEL_NAME = "hit_7pct_before_down_3pct_20d"
ML_INPUT_WINDOW_SESSIONS = 60
ML_FUTURE_WINDOW_SESSIONS = 20
ML_TARGET_PERCENT = 7.0
ML_STOP_PERCENT = 3.0
ML_UNIVERSE_NAME = "NIFTY_500"
ML_RANKING_SCORE = "P(WIN) - P(LOSS)"
ML_TRAINABLE_OUTCOMES = ["WIN", "LOSS", "TIMEOUT"]
ML_EXCLUDED_OUTCOMES = ["AMBIGUOUS"]

ACTIVE_JOB_STATUSES = {"running", "paused"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def ml_v1_contract() -> dict[str, Any]:
    return {
        "model_name": ML_MODEL_NAME,
        "label_name": ML_LABEL_NAME,
        "input_window_sessions": ML_INPUT_WINDOW_SESSIONS,
        "future_window_sessions": ML_FUTURE_WINDOW_SESSIONS,
        "target_percent": ML_TARGET_PERCENT,
        "stop_percent": ML_STOP_PERCENT,
        "universe_name": ML_UNIVERSE_NAME,
        "prediction_timing": "after_sample_date_close",
        "future_scan": "starts_next_trading_session_after_sample_date",
        "data_source": "saved_local_dhan_daily_ohlcv_only",
        "ranking_score": ML_RANKING_SCORE,
        "trainable_outcomes": ML_TRAINABLE_OUTCOMES,
        "excluded_outcomes": ML_EXCLUDED_OUTCOMES,
        "forbidden_v1_features": [
            "RSI",
            "MACD",
            "EMA",
            "SMA",
            "ATR",
            "support_resistance",
            "candlestick_pattern_names",
            "Drishti",
            "reversal_rules",
            "regime_as_ml_input",
            "Gemini_or_AI_review",
            "demo_trading_automation",
            "live_order_logic",
        ],
    }


class MLFoundationStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ml_training_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    model_version TEXT,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    current_instrument_id INTEGER,
                    current_symbol TEXT NOT NULL DEFAULT '',
                    total_instruments INTEGER NOT NULL DEFAULT 0,
                    processed_instruments INTEGER NOT NULL DEFAULT 0,
                    generated_samples INTEGER NOT NULL DEFAULT 0,
                    trainable_samples INTEGER NOT NULL DEFAULT 0,
                    excluded_samples INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    paused_at TEXT,
                    resumed_at TEXT,
                    completed_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ml_model_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    label_name TEXT NOT NULL,
                    input_window_sessions INTEGER NOT NULL,
                    future_window_sessions INTEGER NOT NULL,
                    target_percent REAL NOT NULL,
                    stop_percent REAL NOT NULL,
                    train_from_date TEXT,
                    train_to_date TEXT,
                    validation_from_date TEXT,
                    validation_to_date TEXT,
                    test_from_date TEXT,
                    test_to_date TEXT,
                    universe_name TEXT NOT NULL,
                    instruments_count INTEGER NOT NULL DEFAULT 0,
                    sample_counts_json TEXT NOT NULL DEFAULT '{}',
                    feature_config_json TEXT NOT NULL DEFAULT '{}',
                    label_config_json TEXT NOT NULL DEFAULT '{}',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(model_name, model_version)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_status ON ml_training_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_model_registry_model ON ml_model_registry(model_name, is_active)")

    def latest_job(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ml_training_jobs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return training_job_row_to_dict(row) if row else None

    def active_job(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ml_training_jobs
                WHERE status IN ('running', 'paused')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return training_job_row_to_dict(row) if row else None

    def create_training_job(self, config: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ml_training_jobs (
                    model_name, status, phase, config_json,
                    started_at, created_at, updated_at
                )
                VALUES (?, 'running', 'idle', ?, ?, ?, ?)
                """,
                (
                    ML_MODEL_NAME,
                    json.dumps(config, sort_keys=True),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM ml_training_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return training_job_row_to_dict(row)

    def update_job_status(self, job_id: int, status: str, phase: str | None = None) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        fields = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, timestamp]
        if phase is not None:
            fields.append("phase = ?")
            values.append(phase)
        if status == "paused":
            fields.append("paused_at = ?")
            values.append(timestamp)
        elif status == "running":
            fields.append("resumed_at = ?")
            values.append(timestamp)
        elif status in TERMINAL_JOB_STATUSES:
            fields.append("completed_at = ?")
            values.append(timestamp)
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE ml_training_jobs SET {', '.join(fields)} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM ml_training_jobs WHERE id = ?", (job_id,)).fetchone()
        return training_job_row_to_dict(row)

    def active_model(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ml_model_registry
                WHERE is_active = 1
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return model_registry_row_to_dict(row) if row else None

    def list_models(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ml_model_registry
                ORDER BY id DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 500),),
            ).fetchall()
        return [model_registry_row_to_dict(row) for row in rows]

    def model_by_id(self, model_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ml_model_registry WHERE id = ?", (model_id,)).fetchone()
        return model_registry_row_to_dict(row) if row else None


class MLFoundationService:
    def __init__(self, settings: Settings, store: MLFoundationStore) -> None:
        self.settings = settings
        self.store = store

    def status(self) -> dict[str, Any]:
        models = self.store.list_models(limit=1)
        return {
            "status": "not_started" if self.store.latest_job() is None and not models else "ready",
            "contract": ml_v1_contract(),
            "current_job": self.store.latest_job(),
            "active_model": self.store.active_model(),
            "model_count": len(self.store.list_models(limit=500)),
            "training_available": False,
            "message": "ML foundation is active. One-symbol local sample generation is available; model training is not implemented in this phase.",
        }

    def start_training(self) -> dict[str, Any]:
        active = self.store.active_job()
        if active is not None:
            raise ValueError("An ML training job is already running or paused.")
        return self.store.create_training_job(ml_v1_contract())

    def pause_training(self) -> dict[str, Any]:
        active = self.store.active_job()
        if active is None or active["status"] != "running":
            raise ValueError("No running ML training job exists.")
        return self.store.update_job_status(active["id"], "paused", "idle")

    def resume_training(self) -> dict[str, Any]:
        active = self.store.active_job()
        if active is None or active["status"] != "paused":
            raise ValueError("No paused ML training job exists.")
        return self.store.update_job_status(active["id"], "running", "idle")

    def cancel_training(self) -> dict[str, Any]:
        active = self.store.active_job()
        if active is None:
            raise ValueError("No running or paused ML training job exists.")
        return self.store.update_job_status(active["id"], "cancelled", "idle")

    def training_status(self) -> dict[str, Any]:
        return {"current_job": self.store.latest_job(), "contract": ml_v1_contract()}

    def models(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_models(limit)

    def model(self, model_id: int) -> dict[str, Any] | None:
        return self.store.model_by_id(model_id)


def training_job_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["config"] = json.loads(data.pop("config_json") or "{}")
    return data


def model_registry_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["is_active"] = bool(data["is_active"])
    data["sample_counts"] = json.loads(data.pop("sample_counts_json") or "{}")
    data["feature_config"] = json.loads(data.pop("feature_config_json") or "{}")
    data["label_config"] = json.loads(data.pop("label_config_json") or "{}")
    data["metrics"] = json.loads(data.pop("metrics_json") or "{}")
    return data
