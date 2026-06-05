import json
from typing import Any

from app.config import Settings
from app.demo_trading import DemoTradingService
from app.store import TokenStore
from app.timezone import now_utc


CANDIDATE_ACTIVE = "active"
CANDIDATE_ENTERED = "entered"
CANDIDATE_IGNORED = "ignored"
CANDIDATE_EXPIRED = "expired"
CANDIDATE_INVALIDATED = "invalidated"
ENTRY_WAIT_PULLBACK = "wait_pullback"
ENTRY_WAIT_BREAKOUT = "wait_breakout"
ENTRY_ENTER_NOW = "enter_now"
ENTRY_IGNORE = "ignore"


class WatchlistStore:
    def __init__(self, token_store: TokenStore, settings: Settings) -> None:
        self.token_store = token_store
        self.settings = settings
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_signal_hit_id INTEGER NOT NULL UNIQUE,
                    decision_snapshot_id INTEGER,
                    analysis_review_id INTEGER,
                    source_signal_id TEXT NOT NULL,
                    source_run_id INTEGER,
                    instrument_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    trigger_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    entry_rule TEXT NOT NULL,
                    entry_low REAL,
                    entry_high REAL,
                    breakout_price REAL,
                    stop_loss REAL,
                    target_1 REAL,
                    target_2 REAL,
                    trailing_stop_loss REAL,
                    risk_reward REAL,
                    invalidation_price REAL,
                    expires_after_date TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    features_json TEXT NOT NULL DEFAULT '{}',
                    entered_order_id INTEGER,
                    closed_reason TEXT NOT NULL DEFAULT '',
                    last_checked_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist_candidates(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist_candidates(symbol)")

    def upsert_from_review(self, hit: dict[str, Any], review: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        decision = str(review.get("decision") or "IGNORE")
        status = CANDIDATE_IGNORED if decision == "IGNORE" else CANDIDATE_ACTIVE
        entry_rule = entry_rule_for_review(review, features)
        expires_after_date = expiry_date_for_hit(hit, max_sessions=self.settings.watchlist_entry_expiry_sessions)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlist_candidates (
                    source_signal_hit_id, decision_snapshot_id, analysis_review_id,
                    source_signal_id, source_run_id, instrument_id, company_name, industry,
                    symbol, isin, security_id, trigger_date, status, decision, confidence,
                    entry_rule, entry_low, entry_high, breakout_price, stop_loss, target_1,
                    target_2, trailing_stop_loss, risk_reward, invalidation_price,
                    expires_after_date, summary, features_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_signal_hit_id) DO UPDATE SET
                    decision_snapshot_id = excluded.decision_snapshot_id,
                    analysis_review_id = excluded.analysis_review_id,
                    status = CASE
                        WHEN watchlist_candidates.status IN ('entered', 'expired', 'invalidated')
                        THEN watchlist_candidates.status
                        ELSE excluded.status
                    END,
                    decision = excluded.decision,
                    confidence = excluded.confidence,
                    entry_rule = excluded.entry_rule,
                    entry_low = excluded.entry_low,
                    entry_high = excluded.entry_high,
                    breakout_price = excluded.breakout_price,
                    stop_loss = excluded.stop_loss,
                    target_1 = excluded.target_1,
                    target_2 = excluded.target_2,
                    trailing_stop_loss = excluded.trailing_stop_loss,
                    risk_reward = excluded.risk_reward,
                    invalidation_price = excluded.invalidation_price,
                    expires_after_date = excluded.expires_after_date,
                    summary = excluded.summary,
                    features_json = excluded.features_json,
                    updated_at = excluded.updated_at
                """,
                (
                    hit["id"],
                    review.get("decision_snapshot_id"),
                    review.get("id"),
                    hit["signal_id"],
                    hit["run_id"],
                    hit["instrument_id"],
                    hit["company_name"],
                    hit["industry"],
                    hit["symbol"],
                    hit["isin"],
                    hit["security_id"],
                    hit["trigger_date"],
                    status,
                    decision,
                    float(review.get("confidence") or 0),
                    entry_rule,
                    review.get("entry_low"),
                    review.get("entry_high"),
                    features.get("breakout_price"),
                    review.get("stop_loss"),
                    review.get("target_1"),
                    review.get("target_2"),
                    review.get("trailing_stop_loss"),
                    review.get("risk_reward"),
                    review.get("stop_loss"),
                    expires_after_date,
                    review.get("summary") or "",
                    json.dumps(features, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        return self.candidate_for_hit(int(hit["id"])) or {}

    def active_candidates(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM watchlist_candidates
                WHERE status = ?
                ORDER BY trigger_date, id
                LIMIT ?
                """,
                (CANDIDATE_ACTIVE, min(max(limit, 1), 1000)),
            ).fetchall()
        return [candidate_row_to_dict(row) for row in rows]

    def latest_candidates(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM watchlist_candidates
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 500)),
            ).fetchall()
        return [candidate_row_to_dict(row) for row in rows]

    def candidate_for_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM watchlist_candidates WHERE source_signal_hit_id = ?",
                (hit_id,),
            ).fetchone()
        return candidate_row_to_dict(row) if row else None

    def signal_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM drishti_signal_hits WHERE id = ?", (hit_id,)).fetchone()
        return dict(row) if row else None

    def first_candle_after(self, instrument_id: int, after_date: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND trading_date > ?
                ORDER BY trading_date
                LIMIT 1
                """,
                (instrument_id, after_date),
            ).fetchone()
        return dict(row) if row else None

    def mark_entered(self, candidate_id: int, order_id: int, candle_date: str) -> dict[str, Any]:
        return self._close_candidate(candidate_id, CANDIDATE_ENTERED, "ENTRY_TRIGGERED", candle_date, order_id)

    def mark_invalidated(self, candidate_id: int, candle_date: str) -> dict[str, Any]:
        return self._close_candidate(candidate_id, CANDIDATE_INVALIDATED, "INVALIDATION_HIT", candle_date)

    def mark_expired(self, candidate_id: int, candle_date: str) -> dict[str, Any]:
        return self._close_candidate(candidate_id, CANDIDATE_EXPIRED, "ENTRY_WINDOW_EXPIRED", candle_date)

    def update_checked(self, candidate_id: int, candle_date: str) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE watchlist_candidates
                SET last_checked_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (candle_date, timestamp, candidate_id),
            )
            row = conn.execute("SELECT * FROM watchlist_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return candidate_row_to_dict(row)

    def _close_candidate(
        self,
        candidate_id: int,
        status: str,
        reason: str,
        candle_date: str,
        order_id: int | None = None,
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE watchlist_candidates
                SET status = ?, closed_reason = ?, entered_order_id = COALESCE(?, entered_order_id),
                    last_checked_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, reason, order_id, candle_date, timestamp, candidate_id),
            )
            row = conn.execute("SELECT * FROM watchlist_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return candidate_row_to_dict(row)


class WatchlistService:
    def __init__(self, settings: Settings, token_store: TokenStore, demo_trading_service: DemoTradingService) -> None:
        self.settings = settings
        self.store = WatchlistStore(token_store, settings)
        self.demo_trading_service = demo_trading_service

    def latest(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.latest_candidates(status=status, limit=limit)

    def upsert_from_review(self, hit_id: int, review: dict[str, Any]) -> dict[str, Any]:
        hit = self.store.signal_hit(hit_id)
        if not hit:
            raise ValueError("Drishti signal hit was not found.")
        features = (((review.get("raw_response") or {}).get("features")) or {}).copy()
        features.setdefault("breakout_price", hit["trigger_high"])
        return self.store.upsert_from_review(hit, review, features)

    def upsert_review_for_hit(self, hit: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        features = (((review.get("raw_response") or {}).get("features")) or {}).copy()
        features.setdefault("breakout_price", hit["trigger_high"])
        return self.store.upsert_from_review(hit, review, features)

    def monitor_entries(self) -> dict[str, Any]:
        entered: list[dict[str, Any]] = []
        expired: list[dict[str, Any]] = []
        invalidated: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []

        for candidate in self.store.active_candidates():
            candle = self.store.first_candle_after(
                int(candidate["instrument_id"]),
                candidate.get("last_checked_date") or candidate["trigger_date"],
            )
            if candle is None:
                waiting.append(candidate)
                continue

            if str(candle["trading_date"]) > str(candidate["expires_after_date"]):
                expired.append(self.store.mark_expired(int(candidate["id"]), str(candle["trading_date"])))
                continue

            invalidation_price = optional_float(candidate.get("invalidation_price"))
            if invalidation_price is not None and float(candle["low"]) <= invalidation_price:
                invalidated.append(self.store.mark_invalidated(int(candidate["id"]), str(candle["trading_date"])))
                continue

            if self._entry_triggered(candidate, candle):
                entry_low, entry_high, target_price = self._order_plan_for_entry(candidate, candle)
                order_result = self.demo_trading_service.place_order_from_drishti_hit(
                    int(candidate["source_signal_hit_id"]),
                    risk_reward=optional_float(candidate.get("risk_reward")),
                    stop_loss=optional_float(candidate.get("stop_loss")),
                    target_price=target_price,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    trailing_stop_loss=optional_float(candidate.get("trailing_stop_loss")),
                    ai_review_id=candidate.get("analysis_review_id"),
                    fill_after_date=str(candle["trading_date"]),
                )
                order = order_result.get("order") or {}
                entered.append(
                    self.store.mark_entered(
                        int(candidate["id"]),
                        int(order.get("id") or 0),
                        str(candle["trading_date"]),
                    )
                )
                continue

            waiting.append(self.store.update_checked(int(candidate["id"]), str(candle["trading_date"])))

        return {
            "entered": entered,
            "expired": expired,
            "invalidated": invalidated,
            "waiting": waiting,
        }

    def _order_plan_for_entry(
        self,
        candidate: dict[str, Any],
        candle: dict[str, Any],
    ) -> tuple[float | None, float | None, float | None]:
        entry_low = optional_float(candidate.get("entry_low"))
        entry_high = optional_float(candidate.get("entry_high"))
        target_price = optional_float(candidate.get("target_1"))
        if candidate.get("entry_rule") != ENTRY_WAIT_BREAKOUT:
            return entry_low, entry_high, target_price

        breakout_price = optional_float(candidate.get("breakout_price"))
        confirmation_close = float(candle["close"])
        effective_entry_low = breakout_price if breakout_price is not None else entry_low
        effective_entry_high = max(
            value
            for value in [
                entry_high,
                confirmation_close * 1.02,
                (breakout_price * 1.02) if breakout_price is not None else None,
            ]
            if value is not None
        )
        return effective_entry_low, effective_entry_high, None

    def _entry_triggered(self, candidate: dict[str, Any], candle: dict[str, Any]) -> bool:
        rule = candidate.get("entry_rule")
        if rule == ENTRY_ENTER_NOW:
            return True
        if rule == ENTRY_WAIT_PULLBACK:
            entry_low = optional_float(candidate.get("entry_low"))
            entry_high = optional_float(candidate.get("entry_high"))
            return entry_low is not None and entry_high is not None and float(candle["low"]) <= entry_high and float(candle["high"]) >= entry_low
        if rule == ENTRY_WAIT_BREAKOUT:
            breakout_price = optional_float(candidate.get("breakout_price"))
            return (
                breakout_price is not None
                and float(candle["close"]) > breakout_price
                and candle_close_strength(candle) >= self.settings.watchlist_breakout_min_close_strength
            )
        return False


def entry_rule_for_review(review: dict[str, Any], features: dict[str, Any]) -> str:
    decision = str(review.get("decision") or "IGNORE")
    if decision == "IGNORE":
        return ENTRY_IGNORE
    if decision == "ENTER":
        return ENTRY_ENTER_NOW
    recent_return = float(features.get("recent_return_5d_percent") or 0)
    risk_percent = float(features.get("risk_percent") or 0)
    if recent_return > 8 or risk_percent > 10:
        return ENTRY_WAIT_PULLBACK
    return ENTRY_WAIT_BREAKOUT


def expiry_date_for_hit(hit: dict[str, Any], max_sessions: int) -> str:
    trigger_date = str(hit["trigger_date"])
    with_dummy_weekends = max_sessions * 2
    from datetime import date, timedelta

    return (date.fromisoformat(trigger_date) + timedelta(days=with_dummy_weekends)).isoformat()


def candidate_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"],
        "analysis_review_id": row["analysis_review_id"],
        "source_signal_id": row["source_signal_id"],
        "source_run_id": row["source_run_id"],
        "instrument_id": row["instrument_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "trigger_date": row["trigger_date"],
        "status": row["status"],
        "decision": row["decision"],
        "confidence": row["confidence"],
        "entry_rule": row["entry_rule"],
        "entry_low": row["entry_low"],
        "entry_high": row["entry_high"],
        "breakout_price": row["breakout_price"],
        "stop_loss": row["stop_loss"],
        "target_1": row["target_1"],
        "target_2": row["target_2"],
        "trailing_stop_loss": row["trailing_stop_loss"],
        "risk_reward": row["risk_reward"],
        "invalidation_price": row["invalidation_price"],
        "expires_after_date": row["expires_after_date"],
        "summary": row["summary"],
        "features": json.loads(row["features_json"] or "{}"),
        "entered_order_id": row["entered_order_id"],
        "closed_reason": row["closed_reason"],
        "last_checked_date": row["last_checked_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candle_close_strength(candle: dict[str, Any]) -> float:
    high = float(candle["high"])
    low = float(candle["low"])
    candle_range = high - low
    if candle_range <= 0:
        return 0.5
    return (float(candle["close"]) - low) / candle_range
