from typing import Any

from app.config import Settings
from app.store import TokenStore
from app.timezone import now_utc


class DemoAutomationStore:
    """Museum status store for the retired demo automation runtime."""

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

    def record_disabled_run(self, historical_status: dict[str, Any] | None = None) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        historical_status_name = str((historical_status or {}).get("status") or "")
        historical_run_id = historical_status_id(historical_status)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO demo_automation_runs (
                    status, reason, historical_status, historical_run_id,
                    fresh_hit_count, ai_reviewed_count, enter_count,
                    orders_created_count, skipped_count, started_at, completed_at
                )
                VALUES ('disabled', ?, ?, ?, 0, 0, 0, 0, 0, ?, ?)
                """,
                (
                    "Demo automation is retired from active runtime.",
                    historical_status_name,
                    historical_run_id,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM demo_automation_runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return automation_run_row_to_dict(row)


class DemoAutomationService:
    """Retired demo automation facade.

    The old service connected Drishti, watchlist monitoring, and demo order creation.
    It is intentionally disabled until a new design is approved.
    """

    def __init__(
        self,
        settings: Settings,
        token_store: TokenStore,
        *args: Any,
        store: DemoAutomationStore | None = None,
        **kwargs: Any,
    ) -> None:
        self.settings = settings
        self.store = store or DemoAutomationStore(token_store)

    def latest_status(self) -> dict[str, Any] | None:
        return self.store.latest_run()

    async def run_once(self, historical_status: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.store.record_disabled_run(historical_status)


def historical_status_id(historical_status: dict[str, Any] | None) -> int | None:
    raw_id = (historical_status or {}).get("id")
    return int(raw_id) if raw_id is not None else None


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
        "algo_analyzed_count": row["ai_reviewed_count"],
        "ai_reviewed_count": row["ai_reviewed_count"],
        "enter_count": row["enter_count"],
        "orders_created_count": row["orders_created_count"],
        "skipped_count": row["skipped_count"],
        "error": row["error"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }
