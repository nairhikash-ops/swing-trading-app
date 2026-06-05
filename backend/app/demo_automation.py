import logging
from typing import Any

from app.ai_credentials import GEMINI_PROVIDER
from app.ai_reviews import AiSignalReviewService
from app.config import Settings
from app.demo_trading import DemoTradingService
from app.discipline import LocalDisciplineReviewService
from app.drishti import DrishtiSignalService
from app.learning import LearningStore
from app.store import TokenStore
from app.timezone import now_utc
from app.watchlist import WatchlistService


logger = logging.getLogger(__name__)

READY_HISTORICAL_STATUSES = {"completed", "completed_with_errors", "up_to_date"}
TERMINAL_AI_STATUSES = {"completed", "failed", "quota_limited"}


class DemoAutomationStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_automation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    historical_status TEXT NOT NULL DEFAULT '',
                    historical_run_id INTEGER,
                    drishti_run_id INTEGER,
                    latest_trading_date TEXT,
                    fresh_hit_count INTEGER NOT NULL DEFAULT 0,
                    ai_reviewed_count INTEGER NOT NULL DEFAULT 0,
                    enter_count INTEGER NOT NULL DEFAULT 0,
                    orders_created_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )

    def latest_nifty_500_candle_date(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(dc.trading_date) AS latest_date
                FROM daily_candles dc
                JOIN instruments i ON i.id = dc.instrument_id
                JOIN index_constituents c ON c.isin = i.isin
                WHERE c.index_name = 'NIFTY_500'
                  AND c.active = 1
                  AND i.active = 1
                """
            ).fetchone()
        return str(row["latest_date"]) if row and row["latest_date"] else None

    def latest_nifty_500_trading_dates(self, limit: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT dc.trading_date
                FROM daily_candles dc
                JOIN instruments i ON i.id = dc.instrument_id
                JOIN index_constituents c ON c.isin = i.isin
                WHERE c.index_name = 'NIFTY_500'
                  AND c.active = 1
                  AND i.active = 1
                GROUP BY dc.trading_date
                ORDER BY dc.trading_date DESC
                LIMIT ?
                """,
                (min(max(limit, 1), 30),),
            ).fetchall()
        return [str(row["trading_date"]) for row in rows]

    def start_run(self, historical_status: dict[str, Any] | None) -> int:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO demo_automation_runs (
                    status, historical_status, historical_run_id, started_at
                )
                VALUES ('running', ?, ?, ?)
                """,
                (
                    str((historical_status or {}).get("status") or ""),
                    historical_status_id(historical_status),
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, result: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE demo_automation_runs
                SET status = ?, reason = ?, historical_status = ?, historical_run_id = ?,
                    drishti_run_id = ?, latest_trading_date = ?, fresh_hit_count = ?,
                    ai_reviewed_count = ?, enter_count = ?, orders_created_count = ?,
                    skipped_count = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    result.get("status", ""),
                    result.get("reason", ""),
                    result.get("historical_status", ""),
                    result.get("historical_run_id"),
                    result.get("drishti_run_id"),
                    result.get("latest_trading_date"),
                    int(result.get("fresh_hit_count") or 0),
                    int(result.get("ai_reviewed_count") or 0),
                    int(result.get("enter_count") or 0),
                    int(result.get("orders_created_count") or 0),
                    int(result.get("skipped_count") or 0),
                    result.get("error", ""),
                    timestamp,
                    run_id,
                ),
            )
            row = conn.execute("SELECT * FROM demo_automation_runs WHERE id = ?", (run_id,)).fetchone()
        return automation_run_row_to_dict(row)

    def latest_run(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM demo_automation_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return automation_run_row_to_dict(row) if row else None


class DemoAutomationService:
    def __init__(
        self,
        settings: Settings,
        token_store: TokenStore,
        drishti_signal_service: DrishtiSignalService,
        ai_signal_review_service: AiSignalReviewService,
        demo_trading_service: DemoTradingService,
        store: DemoAutomationStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or DemoAutomationStore(token_store)
        self.drishti_signal_service = drishti_signal_service
        self.ai_signal_review_service = ai_signal_review_service
        self.demo_trading_service = demo_trading_service
        self.learning_store = LearningStore(token_store)
        self.local_discipline_review_service = LocalDisciplineReviewService(settings, token_store)
        self.watchlist_service = WatchlistService(settings, token_store, demo_trading_service)

    def latest_status(self) -> dict[str, Any] | None:
        return self.store.latest_run()

    async def run_once(self, historical_status: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = self.store.start_run(historical_status)
        historical_status_name = str((historical_status or {}).get("status") or "")
        base_result: dict[str, Any] = {
            "status": "skipped",
            "reason": "",
            "historical_status": historical_status_name,
            "historical_run_id": historical_status_id(historical_status),
            "drishti_run_id": None,
            "latest_trading_date": None,
            "fresh_hit_count": 0,
            "ai_reviewed_count": 0,
            "enter_count": 0,
            "orders_created_count": 0,
            "skipped_count": 0,
            "error": "",
        }
        try:
            self.demo_trading_service.refresh()
            opening_watchlist_result = self.watchlist_service.monitor_entries()
            base_result["orders_created_count"] += len(opening_watchlist_result["entered"])
            if not self.settings.demo_automation_enabled:
                base_result["reason"] = "Demo automation is disabled."
                return self.store.finish_run(run_id, base_result)
            if not historical_ready(historical_status):
                base_result["reason"] = "Historical data is not ready for automated demo trading."
                return self.store.finish_run(run_id, base_result)

            latest_trading_date = self.store.latest_nifty_500_candle_date()
            base_result["latest_trading_date"] = latest_trading_date
            if not latest_trading_date:
                base_result["reason"] = "No Nifty 500 candle data is available."
                return self.store.finish_run(run_id, base_result)

            report = self.drishti_signal_service.refresh_nifty_500_signal_01()
            base_result["drishti_run_id"] = report.get("run_id")
            review_dates = set(
                self.store.latest_nifty_500_trading_dates(
                    self.settings.demo_automation_signal_review_window_sessions + 1
                )
            )
            fresh_hits = sorted(
                [
                    item
                    for item in report.get("items", [])
                    if item.get("trigger_date") in review_dates and self._needs_initial_review(item)
                ],
                key=lambda item: (float(item.get("volume_vs_sma") or 0), float(item.get("volume_ratio_1d") or 0)),
                reverse=True,
            )
            base_result["fresh_hit_count"] = len(fresh_hits)
            if not fresh_hits:
                base_result["status"] = "ok"
                base_result["reason"] = "No untracked Drishti Signal 1 hits inside the confirmation window."
                return self.store.finish_run(run_id, base_result)

            for hit in fresh_hits:
                self.learning_store.ensure_snapshot_for_hit(int(hit["id"]))

            for hit in fresh_hits[: self.settings.demo_automation_max_ai_reviews_per_run]:
                review = await self._review_hit(int(hit["id"]))
                if review is None:
                    base_result["skipped_count"] += 1
                    continue
                if review.get("status") == "quota_limited":
                    base_result["ai_reviewed_count"] += 1
                    self.watchlist_service.upsert_review_for_hit(hit, review)
                    base_result["skipped_count"] += 1
                    break
                if review.get("status") != "completed":
                    base_result["ai_reviewed_count"] += 1
                    self.watchlist_service.upsert_review_for_hit(hit, review)
                    base_result["skipped_count"] += 1
                    continue
                base_result["ai_reviewed_count"] += 1
                if review.get("decision") != "ENTER":
                    self.watchlist_service.upsert_review_for_hit(hit, review)
                    if review.get("decision") == "IGNORE":
                        base_result["skipped_count"] += 1
                    continue
                base_result["enter_count"] += 1
                self.watchlist_service.upsert_review_for_hit(hit, review)
                order_result = self.demo_trading_service.place_order_from_drishti_hit(
                    int(hit["id"]),
                    risk_reward=optional_float(review.get("risk_reward")),
                    stop_loss=optional_float(review.get("stop_loss")),
                    target_price=optional_float(review.get("target_1")),
                    entry_low=optional_float(review.get("entry_low")),
                    entry_high=optional_float(review.get("entry_high")),
                    trailing_stop_loss=optional_float(review.get("trailing_stop_loss")),
                    ai_review_id=int(review["id"]),
                )
                if order_result.get("order"):
                    base_result["orders_created_count"] += 1
                    candidate = self.watchlist_service.store.candidate_for_hit(int(hit["id"]))
                    if candidate:
                        self.watchlist_service.store.mark_entered(
                            int(candidate["id"]),
                            int(order_result["order"]["id"]),
                            str(hit["trigger_date"]),
                        )

            if len(fresh_hits) > self.settings.demo_automation_max_ai_reviews_per_run:
                base_result["skipped_count"] += len(fresh_hits) - self.settings.demo_automation_max_ai_reviews_per_run
            closing_watchlist_result = self.watchlist_service.monitor_entries()
            base_result["orders_created_count"] += len(closing_watchlist_result["entered"])
            base_result["status"] = "ok"
            base_result["reason"] = "Automation cycle completed."
            return self.store.finish_run(run_id, base_result)
        except Exception as exc:
            logger.exception("Demo automation failed.")
            base_result["status"] = "failed"
            base_result["error"] = str(exc)[:1000]
            return self.store.finish_run(run_id, base_result)

    def _needs_initial_review(self, hit: dict[str, Any]) -> bool:
        hit_id = int(hit["id"])
        candidate = self.watchlist_service.store.candidate_for_hit(hit_id)
        if candidate is not None:
            return False
        identity_candidate = self.watchlist_service.store.candidate_for_signal_identity(
            str(hit["signal_id"]),
            int(hit["instrument_id"]),
            str(hit["trigger_date"]),
        )
        if identity_candidate is not None:
            return False
        order = self.demo_trading_service.store.order_for_signal_hit(hit_id)
        if order is not None:
            return False
        identity_order = self.demo_trading_service.store.order_for_signal_identity(
            str(hit["signal_id"]),
            int(hit["instrument_id"]),
            str(hit["trigger_date"]),
        )
        return identity_order is None

    async def _review_hit(self, hit_id: int) -> dict[str, Any] | None:
        review_service = (
            self.ai_signal_review_service
            if self.settings.demo_automation_review_engine.strip().lower() == GEMINI_PROVIDER
            else self.local_discipline_review_service
        )
        latest_review = review_service.latest_review_for_hit(hit_id)
        if latest_review and (
            latest_review.get("status") == "completed" or not self.settings.demo_automation_retry_failed_ai_reviews
        ):
            return latest_review
        return await review_service.review_drishti_hit(hit_id)


def historical_ready(historical_status: dict[str, Any] | None) -> bool:
    if not historical_status:
        return False
    if str(historical_status.get("status") or "") not in READY_HISTORICAL_STATUSES:
        return False
    return int(historical_status.get("failed_count") or 0) == 0


def historical_status_id(historical_status: dict[str, Any] | None) -> int | None:
    raw_id = (historical_status or {}).get("id")
    return int(raw_id) if raw_id is not None else None


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def automation_run_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "reason": row["reason"],
        "historical_status": row["historical_status"],
        "historical_run_id": row["historical_run_id"],
        "drishti_run_id": row["drishti_run_id"],
        "latest_trading_date": row["latest_trading_date"],
        "fresh_hit_count": row["fresh_hit_count"],
        "ai_reviewed_count": row["ai_reviewed_count"],
        "enter_count": row["enter_count"],
        "orders_created_count": row["orders_created_count"],
        "skipped_count": row["skipped_count"],
        "error": row["error"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }
