import json
from typing import Any

from app.store import TokenStore
from app.timezone import now_utc


SNAPSHOT_VERSION = 1


class LearningStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_decision_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_signal_hit_id INTEGER NOT NULL UNIQUE,
                    signal_id TEXT NOT NULL,
                    source_run_id INTEGER,
                    instrument_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    trigger_date TEXT NOT NULL,
                    snapshot_version INTEGER NOT NULL,
                    candle_count INTEGER NOT NULL,
                    context_json TEXT NOT NULL,
                    feature_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_trade_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL UNIQUE,
                    order_id INTEGER NOT NULL,
                    source_signal_hit_id INTEGER,
                    decision_snapshot_id INTEGER,
                    legacy_review_id INTEGER,
                    instrument_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_date TEXT,
                    exit_price REAL,
                    exit_reason TEXT NOT NULL DEFAULT '',
                    holding_sessions INTEGER NOT NULL DEFAULT 0,
                    max_favorable_price REAL,
                    max_favorable_percent REAL,
                    max_adverse_price REAL,
                    max_adverse_percent REAL,
                    target_hit INTEGER NOT NULL DEFAULT 0,
                    stop_hit INTEGER NOT NULL DEFAULT 0,
                    time_exit INTEGER NOT NULL DEFAULT 0,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    realized_pnl_percent REAL NOT NULL DEFAULT 0,
                    outcome_label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_snapshots_symbol_date
                ON learning_decision_snapshots(symbol, trigger_date)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_outcomes_signal
                ON learning_trade_outcomes(source_signal_hit_id, id DESC)
                """
            )
            ensure_columns(conn, "demo_orders", {"decision_snapshot_id": "INTEGER"})
            ensure_columns(conn, "demo_positions", {"decision_snapshot_id": "INTEGER"})

    def ensure_snapshot_for_hit(
        self,
        hit_id: int,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.snapshot_for_hit(hit_id)
        if existing:
            return existing

        hit = self._signal_hit(hit_id)
        if hit is None:
            raise ValueError("Drishti signal hit was not found.")

        snapshot_context = context or self._build_snapshot_context(hit)
        features = snapshot_context.get("computed_features") or {}
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO learning_decision_snapshots (
                    source_signal_hit_id, signal_id, source_run_id, instrument_id,
                    symbol, isin, security_id, trigger_date, snapshot_version,
                    candle_count, context_json, feature_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(hit["id"]),
                    hit["signal_id"],
                    hit["run_id"],
                    hit["instrument_id"],
                    hit["symbol"],
                    hit["isin"],
                    hit["security_id"],
                    hit["trigger_date"],
                    SNAPSHOT_VERSION,
                    int(features.get("candle_count") or len(snapshot_context.get("recent_candles") or [])),
                    json.dumps(snapshot_context, sort_keys=True),
                    json.dumps(features, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        return self.snapshot_for_hit(hit_id) or {}

    def snapshot_for_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM learning_decision_snapshots
                WHERE source_signal_hit_id = ?
                """,
                (hit_id,),
            ).fetchone()
        return snapshot_row_to_dict(row) if row else None

    def upsert_trade_outcome(self, position: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = position.get("decision_snapshot_id")
        if snapshot_id is None and position.get("source_signal_hit_id") is not None:
            snapshot = self.ensure_snapshot_for_hit(int(position["source_signal_hit_id"]))
            snapshot_id = snapshot.get("id")

        path = self._position_path(position)
        entry_price = float(position["entry_price"])
        max_favorable_price = max((float(candle["high"]) for candle in path), default=entry_price)
        max_adverse_price = min((float(candle["low"]) for candle in path), default=entry_price)
        max_favorable_percent = ((max_favorable_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        max_adverse_percent = ((max_adverse_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        target_price = optional_float(position.get("target_price"))
        stop_loss = optional_float(position.get("stop_loss"))
        target_hit = bool(target_price is not None and any(float(candle["high"]) >= target_price for candle in path))
        stop_hit = bool(stop_loss is not None and any(float(candle["low"]) <= stop_loss for candle in path))
        exit_reason = str(position.get("exit_reason") or "")
        outcome_label = label_outcome(position, target_hit=target_hit, stop_hit=stop_hit)
        timestamp = now_utc().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_trade_outcomes (
                    position_id, order_id, source_signal_hit_id, decision_snapshot_id,
                    legacy_review_id, instrument_id, symbol, isin, security_id, status,
                    entry_date, entry_price, exit_date, exit_price, exit_reason,
                    holding_sessions, max_favorable_price, max_favorable_percent,
                    max_adverse_price, max_adverse_percent, target_hit, stop_hit,
                    time_exit, realized_pnl, realized_pnl_percent, outcome_label,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(position_id) DO UPDATE SET
                    decision_snapshot_id = excluded.decision_snapshot_id,
                    legacy_review_id = excluded.legacy_review_id,
                    status = excluded.status,
                    exit_date = excluded.exit_date,
                    exit_price = excluded.exit_price,
                    exit_reason = excluded.exit_reason,
                    holding_sessions = excluded.holding_sessions,
                    max_favorable_price = excluded.max_favorable_price,
                    max_favorable_percent = excluded.max_favorable_percent,
                    max_adverse_price = excluded.max_adverse_price,
                    max_adverse_percent = excluded.max_adverse_percent,
                    target_hit = excluded.target_hit,
                    stop_hit = excluded.stop_hit,
                    time_exit = excluded.time_exit,
                    realized_pnl = excluded.realized_pnl,
                    realized_pnl_percent = excluded.realized_pnl_percent,
                    outcome_label = excluded.outcome_label,
                    updated_at = excluded.updated_at
                """,
                (
                    position["id"],
                    position["order_id"],
                    position.get("source_signal_hit_id"),
                    snapshot_id,
                    position.get("legacy_review_id"),
                    position["instrument_id"],
                    position["symbol"],
                    position["isin"],
                    position["security_id"],
                    position["status"],
                    position["entry_date"],
                    entry_price,
                    position.get("exit_date"),
                    optional_float(position.get("exit_price")),
                    exit_reason,
                    int(position.get("holding_sessions") or 0),
                    max_favorable_price,
                    max_favorable_percent,
                    max_adverse_price,
                    max_adverse_percent,
                    1 if target_hit else 0,
                    1 if stop_hit else 0,
                    1 if exit_reason == "TIME_EXIT" else 0,
                    float(position.get("realized_pnl") or 0),
                    float(position.get("realized_pnl_percent") or 0),
                    outcome_label,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM learning_trade_outcomes WHERE position_id = ?",
                (position["id"],),
            ).fetchone()
        return trade_outcome_row_to_dict(row)

    def latest_snapshots(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_decision_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 500),),
            ).fetchall()
        return [snapshot_row_to_dict(row) for row in rows]

    def latest_trade_outcomes(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM learning_trade_outcomes
                ORDER BY id DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 500),),
            ).fetchall()
        return [trade_outcome_row_to_dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            snapshots = conn.execute("SELECT COUNT(*) AS count FROM learning_decision_snapshots").fetchone()
            outcomes = conn.execute("SELECT COUNT(*) AS count FROM learning_trade_outcomes").fetchone()
            labels = conn.execute(
                """
                SELECT outcome_label, COUNT(*) AS count
                FROM learning_trade_outcomes
                GROUP BY outcome_label
                """
            ).fetchall()
        return {
            "decision_snapshot_count": int(snapshots["count"] or 0),
            "trade_outcome_count": int(outcomes["count"] or 0),
            "outcome_counts": {row["outcome_label"]: int(row["count"] or 0) for row in labels},
        }

    def _signal_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM drishti_signal_hits WHERE id = ?", (hit_id,)).fetchone()
        return dict(row) if row else None

    def _candles_until_trigger(self, instrument_id: int, trigger_date: str, limit: int = 80) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND trading_date <= ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument_id, trigger_date, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def _position_path(self, position: dict[str, Any]) -> list[dict[str, Any]]:
        end_date = position.get("exit_date") or position.get("latest_candle_date") or position.get("entry_date")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ?
                  AND trading_date >= ?
                  AND trading_date <= ?
                ORDER BY trading_date
                """,
                (position["instrument_id"], position["entry_date"], end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def _build_snapshot_context(self, hit: dict[str, Any]) -> dict[str, Any]:
        candles = self._candles_until_trigger(int(hit["instrument_id"]), hit["trigger_date"])
        highs = [float(candle["high"]) for candle in candles]
        lows = [float(candle["low"]) for candle in candles]
        closes = [float(candle["close"]) for candle in candles]
        volumes = [float(candle["volume"]) for candle in candles]
        trigger_close = float(hit["trigger_close"])
        avg_volume_20 = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
        low_45 = min(lows[-45:]) if len(lows) >= 45 else (min(lows) if lows else float(hit["anchor_low"]))
        high_45 = max(highs[-45:]) if len(highs) >= 45 else (max(highs) if highs else float(hit["trigger_high"]))
        latest_close = closes[-1] if closes else trigger_close
        return {
            "snapshot_type": "drishti_decision",
            "review_mode": "alert_time_only_no_future_candles",
            "signal": {
                "hit_id": hit["id"],
                "signal_id": hit["signal_id"],
                "symbol": hit["symbol"],
                "company_name": hit["company_name"],
                "industry": hit["industry"],
                "isin": hit["isin"],
                "security_id": hit["security_id"],
                "anchor_date": hit["anchor_date"],
                "trigger_date": hit["trigger_date"],
                "anchor_low": float(hit["anchor_low"]),
                "anchor_high": float(hit["anchor_high"]),
                "anchor_close": float(hit["anchor_close"]),
                "trigger_low": float(hit["trigger_low"]),
                "trigger_close": trigger_close,
                "volume_ratio_1d": float(hit["volume_ratio_1d"]),
                "volume_vs_sma": float(hit["volume_vs_sma"]),
            },
            "computed_features": {
                "candle_count": len(candles),
                "latest_close": latest_close,
                "low_45": low_45,
                "high_45": high_45,
                "move_from_45d_low_percent": ((trigger_close - low_45) / low_45) * 100 if low_45 > 0 else 0,
                "distance_to_45d_high_percent": ((high_45 - trigger_close) / high_45) * 100 if high_45 > 0 else 0,
                "avg_volume_20": avg_volume_20,
                "trigger_volume_vs_20d_avg": float(hit["trigger_volume"]) / avg_volume_20
                if avg_volume_20 > 0
                else 0,
            },
            "recent_candles": [
                {
                    "date": candle["trading_date"],
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"]),
                }
                for candle in candles[-30:]
            ],
        }


def ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not table:
        return
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def label_outcome(position: dict[str, Any], target_hit: bool, stop_hit: bool) -> str:
    status = str(position.get("status") or "")
    if status != "closed":
        return "open"
    exit_reason = str(position.get("exit_reason") or "")
    if exit_reason == "TARGET":
        return "winner"
    if exit_reason == "STOP_LOSS":
        return "failure"
    if target_hit and not stop_hit:
        return "winner"
    if stop_hit and not target_hit:
        return "failure"
    realized_percent = float(position.get("realized_pnl_percent") or 0)
    if realized_percent > 0:
        return "neutral_positive"
    if realized_percent < 0:
        return "neutral_negative"
    return "neutral"


def snapshot_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "signal_id": row["signal_id"],
        "source_run_id": row["source_run_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "trigger_date": row["trigger_date"],
        "snapshot_version": row["snapshot_version"],
        "candle_count": row["candle_count"],
        "context": json.loads(row["context_json"] or "{}"),
        "features": json.loads(row["feature_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def trade_outcome_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "position_id": row["position_id"],
        "order_id": row["order_id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"],
        "legacy_review_id": row["legacy_review_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "status": row["status"],
        "entry_date": row["entry_date"],
        "entry_price": row["entry_price"],
        "exit_date": row["exit_date"],
        "exit_price": row["exit_price"],
        "exit_reason": row["exit_reason"],
        "holding_sessions": row["holding_sessions"],
        "max_favorable_price": row["max_favorable_price"],
        "max_favorable_percent": row["max_favorable_percent"],
        "max_adverse_price": row["max_adverse_price"],
        "max_adverse_percent": row["max_adverse_percent"],
        "target_hit": bool(row["target_hit"]),
        "stop_hit": bool(row["stop_hit"]),
        "time_exit": bool(row["time_exit"]),
        "realized_pnl": row["realized_pnl"],
        "realized_pnl_percent": row["realized_pnl_percent"],
        "outcome_label": row["outcome_label"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
