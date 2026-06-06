import json
from typing import Any, Literal

from app.candlesticks import classify_candles
from app.index_universe import NIFTY_500_INDEX_NAME
from app.regime import classify_regime_series
from app.store import TokenStore
from app.support_resistance import (
    DEFAULT_PIVOT_LEFT,
    DEFAULT_PIVOT_RIGHT,
    SupportResistanceStore,
    detect_support_resistance,
)
from app.timezone import now_utc


OpportunityStage = Literal[
    "downtrend_only",
    "near_support",
    "indecision_near_support",
    "support_reclaim",
    "bullish_reversal_watch",
    "confirmed_reversal",
    "entry_watch",
    "ignore",
]
SuggestedNextAction = Literal[
    "watch_only",
    "wait_for_confirmation",
    "wait_for_breakout",
    "wait_for_pullback",
    "ready_for_drishti_review",
    "ignore",
]

STRONG_BULLISH_REVERSAL_SCORE = 45.0
BEARISH_REVERSAL_BLOCKERS = {
    "shooting_star",
    "dark_cloud_cover",
    "bearish_harami",
    "bearish_engulfing",
    "evening_star",
    "evening_doji_star",
    "tweezer_top_reversal",
}


class ReversalOpportunityService:
    def __init__(
        self,
        token_store: TokenStore | None,
        store: SupportResistanceStore | None = None,
        persistence_store: "ReversalOpportunityStore | None" = None,
    ) -> None:
        self.store = store or SupportResistanceStore(token_store)
        self.persistence_store = persistence_store or (
            ReversalOpportunityStore(token_store) if token_store is not None else None
        )

    def scan_nifty_500(
        self,
        limit: int = 500,
        include_watch_only: bool = True,
        min_score: float = 0,
        min_entry_quality_score: float = 0,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for instrument in self.store.nifty_500_instruments(limit=500):
            candles = self.store.candles_for_instrument(int(instrument["id"]), limit=365)
            item = classify_reversal_opportunity(instrument, candles)
            if item is None:
                continue
            items.append(item)
        return filter_and_sort_items(
            items,
            limit=limit,
            include_watch_only=include_watch_only,
            min_score=min_score,
            min_entry_quality_score=min_entry_quality_score,
        )

    def scan_nifty_500_as_of(
        self,
        replay_date: str,
        limit: int = 500,
        include_watch_only: bool = False,
        min_score: float = 0,
        min_entry_quality_score: float = 55,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for instrument in self.store.nifty_500_instruments(limit=500):
            candles = self._candles_for_instrument_as_of(int(instrument["id"]), replay_date, limit=365)
            item = classify_reversal_opportunity(instrument, candles)
            if item is None:
                continue
            items.append(item)
        return filter_and_sort_items(
            items,
            limit=limit,
            include_watch_only=include_watch_only,
            min_score=min_score,
            min_entry_quality_score=min_entry_quality_score,
        )

    def refresh_nifty_500_snapshot(
        self,
        limit: int = 500,
        include_watch_only: bool = False,
        min_score: float = 0,
        min_entry_quality_score: float = 55,
    ) -> dict[str, Any]:
        items = self.scan_nifty_500(
            limit=limit,
            include_watch_only=include_watch_only,
            min_score=min_score,
            min_entry_quality_score=min_entry_quality_score,
        )
        run_date = latest_item_date(items)
        store = self._persistence()
        run_id = store.create_run(
            universe_name=NIFTY_500_INDEX_NAME,
            run_date=run_date,
            min_score=min_score,
            min_entry_quality_score=min_entry_quality_score,
            include_watch_only=include_watch_only,
            limit=limit,
            item_count=len(items),
        )
        store.insert_items(run_id, items)
        return store.snapshot_for_run(run_id, limit=max(limit, 1))

    def backfill_reversal_opportunities(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        sample_every_n_sessions: int = 5,
        limit_per_date: int = 500,
        min_score: float = 0,
        min_entry_quality_score: float = 55,
        include_watch_only: bool = False,
        max_dates: int = 60,
    ) -> dict[str, Any]:
        store = self._persistence()
        replay_dates = select_replay_dates(
            store.trading_sessions(),
            start_date=start_date,
            end_date=end_date,
            sample_every_n_sessions=sample_every_n_sessions,
            max_dates=max_dates,
        )
        run_ids: list[int] = []
        saved_items: list[dict[str, Any]] = []
        for replay_date in replay_dates:
            items = self.scan_nifty_500_as_of(
                replay_date,
                limit=limit_per_date,
                include_watch_only=include_watch_only,
                min_score=min_score,
                min_entry_quality_score=min_entry_quality_score,
            )
            run_id = store.create_run(
                universe_name=NIFTY_500_INDEX_NAME,
                run_date=replay_date,
                min_score=min_score,
                min_entry_quality_score=min_entry_quality_score,
                include_watch_only=include_watch_only,
                limit=limit_per_date,
                item_count=len(items),
                run_type="backfill",
                source="backfill",
            )
            run_ids.append(run_id)
            store.insert_items(run_id, items)
            for item in store.items_for_run(run_id, limit=max(limit_per_date, len(items), 1)):
                outcome = calculate_outcome(
                    item,
                    store.future_candles(int(item["instrument_id"]), str(item["signal_date"]), limit=10),
                )
                store.update_item_outcome(int(item["id"]), outcome)
                updated = store.item_by_id(int(item["id"]))
                if updated is not None:
                    saved_items.append(updated)
        return build_backfill_response(
            items=saved_items,
            run_ids=run_ids,
            replay_dates=replay_dates,
            sample_every_n_sessions=sample_every_n_sessions,
            min_entry_quality_score=min_entry_quality_score,
        )

    def backfill_summary(self, limit: int = 10000) -> dict[str, Any]:
        items = self._persistence().backfill_items(limit=limit)
        replay_dates = sorted({str(item["signal_date"]) for item in items})
        return build_backfill_response(
            items=items,
            run_ids=[],
            replay_dates=replay_dates,
            sample_every_n_sessions=0,
            min_entry_quality_score=0,
        )

    def latest_snapshot(
        self,
        limit: int = 100,
        min_entry_quality_score: float = 0,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        return self._persistence().latest_snapshot(
            universe_name=NIFTY_500_INDEX_NAME,
            limit=limit,
            min_entry_quality_score=min_entry_quality_score,
            stage=stage,
        )

    def history_for_symbol(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._persistence().history_for_symbol(symbol=symbol, limit=limit)

    def update_outcomes(self, limit: int = 1000) -> dict[str, Any]:
        store = self._persistence()
        candidates = store.items_for_outcome_refresh(limit=limit)
        updated_items: list[dict[str, Any]] = []
        status_counts = {
            "complete": 0,
            "partial": 0,
            "not_enough_future_candles": 0,
        }
        for item in candidates:
            future_candles = store.future_candles(int(item["instrument_id"]), str(item["signal_date"]), limit=10)
            outcome = calculate_outcome(item, future_candles)
            store.update_item_outcome(int(item["id"]), outcome)
            updated = store.item_by_id(int(item["id"]))
            if updated is not None:
                updated_items.append(updated)
            status = str(outcome["outcome_status"])
            if status in status_counts:
                status_counts[status] += 1
        return {
            "checked_count": len(candidates),
            "updated_count": len(updated_items),
            "complete_count": status_counts["complete"],
            "partial_count": status_counts["partial"],
            "not_enough_future_candles_count": status_counts["not_enough_future_candles"],
            "generated_at": now_utc(),
            "items": updated_items,
        }

    def _persistence(self) -> "ReversalOpportunityStore":
        if self.persistence_store is None:
            raise RuntimeError("Reversal opportunity persistence requires a TokenStore-backed service.")
        return self.persistence_store

    def _candles_for_instrument_as_of(
        self,
        instrument_id: int,
        replay_date: str,
        limit: int = 365,
    ) -> list[dict[str, Any]]:
        if hasattr(self.store, "candles_for_instrument_as_of"):
            return self.store.candles_for_instrument_as_of(instrument_id, replay_date, limit=limit)
        with self.store._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND trading_date <= ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument_id, replay_date, min(max(limit, 20), 365)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]


class ReversalOpportunityStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reversal_opportunity_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_name TEXT NOT NULL,
                    run_date TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    min_score REAL NOT NULL,
                    min_entry_quality_score REAL NOT NULL,
                    include_watch_only INTEGER NOT NULL,
                    limit_value INTEGER NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    run_type TEXT NOT NULL DEFAULT 'live',
                    source TEXT NOT NULL DEFAULT 'manual'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reversal_opportunity_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    signal_date TEXT NOT NULL,
                    latest_close REAL NOT NULL,
                    regime TEXT NOT NULL,
                    regime_confidence REAL NOT NULL,
                    opportunity_stage TEXT NOT NULL,
                    opportunity_score REAL NOT NULL,
                    entry_quality_score REAL NOT NULL,
                    suggested_next_action TEXT NOT NULL,
                    near_support INTEGER NOT NULL,
                    inside_support_zone INTEGER NOT NULL,
                    support_reclaim INTEGER NOT NULL,
                    quality_support_reclaim INTEGER NOT NULL,
                    support_distance_percent REAL,
                    support_strength REAL,
                    support_touch_count INTEGER,
                    support_recency_sessions INTEGER,
                    indecision_score REAL NOT NULL,
                    reversal_score REAL NOT NULL,
                    reversal_bias TEXT NOT NULL,
                    recent_indecision_date TEXT,
                    recent_reversal_date TEXT,
                    bullish_reversal_source_date TEXT,
                    confirmation_source TEXT,
                    reasons_json TEXT NOT NULL,
                    latest_patterns_json TEXT NOT NULL,
                    latest_reversal_patterns_json TEXT NOT NULL,
                    recent_patterns_json TEXT NOT NULL,
                    recent_reversal_patterns_json TEXT NOT NULL,
                    nearest_support_json TEXT,
                    outcome_1d_return_percent REAL,
                    outcome_3d_return_percent REAL,
                    outcome_5d_return_percent REAL,
                    outcome_10d_return_percent REAL,
                    max_favorable_10d_percent REAL,
                    max_adverse_10d_percent REAL,
                    support_broken_10d INTEGER,
                    outcome_status TEXT NOT NULL DEFAULT 'pending',
                    outcome_checked_at TEXT
                )
                """
            )
            ensure_columns(
                conn,
                "reversal_opportunity_runs",
                {
                    "run_type": "TEXT NOT NULL DEFAULT 'live'",
                    "source": "TEXT NOT NULL DEFAULT 'manual'",
                },
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reversal_opportunity_runs_universe
                ON reversal_opportunity_runs(universe_name, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reversal_opportunity_runs_type
                ON reversal_opportunity_runs(run_type, universe_name, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reversal_opportunity_items_run
                ON reversal_opportunity_items(run_id, entry_quality_score)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reversal_opportunity_items_symbol
                ON reversal_opportunity_items(symbol, signal_date)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reversal_opportunity_items_outcome
                ON reversal_opportunity_items(outcome_status, signal_date)
                """
            )

    def create_run(
        self,
        *,
        universe_name: str,
        run_date: str,
        min_score: float,
        min_entry_quality_score: float,
        include_watch_only: bool,
        limit: int,
        item_count: int,
        run_type: str = "live",
        source: str = "manual",
    ) -> int:
        generated_at = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reversal_opportunity_runs (
                    universe_name, run_date, generated_at, min_score,
                    min_entry_quality_score, include_watch_only, limit_value, item_count,
                    run_type, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    universe_name,
                    run_date,
                    generated_at,
                    float(min_score),
                    float(min_entry_quality_score),
                    1 if include_watch_only else 0,
                    int(limit),
                    int(item_count),
                    run_type,
                    source,
                ),
            )
            return int(cursor.lastrowid)

    def insert_items(self, run_id: int, items: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            for item in items:
                nearest_support = item.get("nearest_support")
                conn.execute(
                    """
                    INSERT INTO reversal_opportunity_items (
                        run_id, instrument_id, symbol, company_name, industry, isin,
                        security_id, signal_date, latest_close, regime, regime_confidence,
                        opportunity_stage, opportunity_score, entry_quality_score,
                        suggested_next_action, near_support, inside_support_zone,
                        support_reclaim, quality_support_reclaim, support_distance_percent,
                        support_strength, support_touch_count, support_recency_sessions,
                        indecision_score, reversal_score, reversal_bias,
                        recent_indecision_date, recent_reversal_date,
                        bullish_reversal_source_date, confirmation_source, reasons_json,
                        latest_patterns_json, latest_reversal_patterns_json,
                        recent_patterns_json, recent_reversal_patterns_json,
                        nearest_support_json, outcome_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        run_id,
                        int(item["instrument_id"]),
                        item["symbol"],
                        item["company_name"],
                        item["industry"],
                        item["isin"],
                        item["security_id"],
                        item["latest_date"],
                        float(item["latest_close"]),
                        item["regime"],
                        float(item["regime_confidence"]),
                        item["opportunity_stage"],
                        float(item["opportunity_score"]),
                        float(item["entry_quality_score"]),
                        item["suggested_next_action"],
                        bool_to_int(item["near_support"]),
                        bool_to_int(item["inside_support_zone"]),
                        bool_to_int(item["support_reclaim"]),
                        bool_to_int(item["quality_support_reclaim"]),
                        item.get("support_distance_percent"),
                        item.get("support_strength"),
                        item.get("support_touch_count"),
                        item.get("support_recency_sessions"),
                        float(item["indecision_score"]),
                        float(item["reversal_score"]),
                        item["reversal_bias"],
                        item.get("recent_indecision_date"),
                        item.get("recent_reversal_date"),
                        item.get("bullish_reversal_source_date"),
                        item.get("confirmation_source"),
                        json_dumps(item.get("reasons") or []),
                        json_dumps(item.get("latest_patterns") or []),
                        json_dumps(item.get("latest_reversal_patterns") or []),
                        json_dumps(item.get("recent_patterns") or []),
                        json_dumps(item.get("recent_reversal_patterns") or []),
                        json_dumps(nearest_support) if nearest_support is not None else None,
                    ),
                )

    def snapshot_for_run(
        self,
        run_id: int,
        *,
        limit: int = 100,
        min_entry_quality_score: float = 0,
        stage: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            run = conn.execute("SELECT * FROM reversal_opportunity_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"Reversal opportunity run {run_id} was not found.")
            rows = self._item_rows_for_run(
                conn,
                run_id=run_id,
                limit=limit,
                min_entry_quality_score=min_entry_quality_score,
                stage=stage,
            )
        return {**run_response(dict(run)), "items": [snapshot_item_response(dict(row)) for row in rows]}

    def latest_snapshot(
        self,
        *,
        universe_name: str,
        limit: int = 100,
        min_entry_quality_score: float = 0,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT * FROM reversal_opportunity_runs
                WHERE universe_name = ?
                  AND run_type = 'live'
                ORDER BY id DESC
                LIMIT 1
                """,
                (universe_name,),
            ).fetchone()
            if run is None:
                return None
            rows = self._item_rows_for_run(
                conn,
                run_id=int(run["id"]),
                limit=limit,
                min_entry_quality_score=min_entry_quality_score,
                stage=stage,
            )
        return {**run_response(dict(run)), "items": [snapshot_item_response(dict(row)) for row in rows]}

    def history_for_symbol(self, *, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT i.*, r.universe_name, r.run_date, r.generated_at
                FROM reversal_opportunity_items i
                JOIN reversal_opportunity_runs r ON r.id = i.run_id
                WHERE UPPER(i.symbol) = UPPER(?)
                ORDER BY i.signal_date DESC, i.id DESC
                LIMIT ?
                """,
                (symbol, min(max(limit, 1), 200)),
            ).fetchall()
        return [snapshot_item_response(dict(row)) for row in rows]

    def items_for_run(self, run_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM reversal_opportunity_items
                WHERE run_id = ?
                ORDER BY entry_quality_score DESC, opportunity_score DESC, symbol
                LIMIT ?
                """,
                (run_id, min(max(limit, 1), 1000)),
            ).fetchall()
        return [snapshot_item_response(dict(row)) for row in rows]

    def items_for_outcome_refresh(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM reversal_opportunity_items
                WHERE outcome_status IN ('pending', 'partial', 'not_enough_future_candles')
                ORDER BY signal_date, id
                LIMIT ?
                """,
                (min(max(limit, 1), 5000),),
            ).fetchall()
        return [snapshot_item_response(dict(row)) for row in rows]

    def future_candles(self, instrument_id: int, signal_date: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND trading_date > ?
                ORDER BY trading_date
                LIMIT ?
                """,
                (instrument_id, signal_date, min(max(limit, 1), 10)),
            ).fetchall()
        return [dict(row) for row in rows]

    def trading_sessions(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT trading_date
                FROM daily_candles
                ORDER BY trading_date
                """
            ).fetchall()
        return [str(row["trading_date"]) for row in rows]

    def update_item_outcome(self, item_id: int, outcome: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reversal_opportunity_items
                SET outcome_1d_return_percent = ?,
                    outcome_3d_return_percent = ?,
                    outcome_5d_return_percent = ?,
                    outcome_10d_return_percent = ?,
                    max_favorable_10d_percent = ?,
                    max_adverse_10d_percent = ?,
                    support_broken_10d = ?,
                    outcome_status = ?,
                    outcome_checked_at = ?
                WHERE id = ?
                """,
                (
                    outcome.get("outcome_1d_return_percent"),
                    outcome.get("outcome_3d_return_percent"),
                    outcome.get("outcome_5d_return_percent"),
                    outcome.get("outcome_10d_return_percent"),
                    outcome.get("max_favorable_10d_percent"),
                    outcome.get("max_adverse_10d_percent"),
                    bool_to_int(outcome.get("support_broken_10d")),
                    outcome["outcome_status"],
                    outcome["outcome_checked_at"],
                    item_id,
                ),
            )

    def item_by_id(self, item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reversal_opportunity_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        return snapshot_item_response(dict(row)) if row else None

    def backfill_items(self, *, limit: int = 10000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT i.*
                FROM reversal_opportunity_items i
                JOIN reversal_opportunity_runs r ON r.id = i.run_id
                WHERE r.run_type = 'backfill'
                ORDER BY i.signal_date DESC, i.entry_quality_score DESC, i.symbol
                LIMIT ?
                """,
                (min(max(limit, 1), 50000),),
            ).fetchall()
        return [snapshot_item_response(dict(row)) for row in rows]

    def _item_rows_for_run(
        self,
        conn,
        *,
        run_id: int,
        limit: int,
        min_entry_quality_score: float,
        stage: str | None,
    ):
        clauses = ["run_id = ?", "entry_quality_score >= ?"]
        params: list[Any] = [run_id, float(min_entry_quality_score)]
        if stage:
            clauses.append("opportunity_stage = ?")
            params.append(stage)
        params.append(min(max(limit, 1), 500))
        return conn.execute(
            f"""
            SELECT *
            FROM reversal_opportunity_items
            WHERE {" AND ".join(clauses)}
            ORDER BY entry_quality_score DESC, opportunity_score DESC, symbol
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()


def classify_reversal_opportunity(
    instrument: dict[str, Any],
    candles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(candles) < max(DEFAULT_PIVOT_LEFT + DEFAULT_PIVOT_RIGHT + 1, 5):
        return None

    regime_rows = classify_regime_series(candles)
    if not regime_rows:
        return None
    latest_regime = regime_rows[-1]
    if latest_regime["regime"] != "DOWNTREND":
        return None

    support_report = detect_support_resistance(candles)
    candle_items = classify_candles(candles)
    return build_opportunity_item(instrument, candles, latest_regime, support_report, candle_items)


def build_opportunity_item(
    instrument: dict[str, Any],
    candles: list[dict[str, Any]],
    latest_regime: dict[str, Any],
    support_report: dict[str, Any],
    candle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    current = candles[-1]
    latest_candle = candle_items[-1] if candle_items else {}
    sources = recent_signal_sources(candles, candle_items)
    indecision_score = float(sources["indecision_score"])
    bullish_reversal_score = float(sources["bullish_reversal_score"])
    latest_bearish = latest_has_bearish_evidence(latest_candle)
    reversal_bias = "bearish" if latest_bearish else latest_reversal_bias(latest_candle, sources["recent_items"])
    confirmed, confirmation_source = bullish_confirmation(
        candles,
        candle_items,
        bullish_reversal_score,
        latest_bearish=latest_bearish,
    )

    near_support = bool(support_report.get("near_support"))
    inside_support_zone = bool(support_report.get("inside_support_zone"))
    support_reclaim = bool(support_report.get("support_reclaim"))
    latest_close = float(current["close"])
    support_quality = support_quality_fields(support_report, latest_close, latest_bearish)
    quality_support_reclaim = bool(support_quality["quality_support_reclaim"])
    stage = classify_stage(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        indecision_score=indecision_score,
        reversal_bias=reversal_bias,
        reversal_score=bullish_reversal_score,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
    )
    score = opportunity_score(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        quality_support_reclaim=quality_support_reclaim,
        indecision_score=indecision_score,
        reversal_score=bullish_reversal_score if reversal_bias in ("bullish", "mixed") else 0,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
        support_strength=support_quality["support_strength"],
        support_touch_count=support_quality["support_touch_count"],
        support_recency_sessions=support_quality["support_recency_sessions"],
    )
    entry_score = entry_quality_score(
        candles=candles,
        reversal_bias=reversal_bias,
        reversal_score=bullish_reversal_score,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        quality_support_reclaim=quality_support_reclaim,
        support_strength=support_quality["support_strength"],
        support_touch_count=support_quality["support_touch_count"],
        support_recency_sessions=support_quality["support_recency_sessions"],
    )
    return {
        "instrument_id": instrument.get("id") or instrument.get("instrument_id"),
        "symbol": instrument.get("underlying_symbol") or instrument.get("symbol") or "",
        "company_name": instrument.get("company_name") or instrument.get("display_name") or "",
        "industry": instrument.get("industry") or "",
        "isin": instrument.get("isin") or "",
        "security_id": instrument.get("security_id") or "",
        "latest_date": current["trading_date"],
        "latest_close": float(current["close"]),
        "regime": latest_regime["regime"],
        "regime_confidence": float(latest_regime.get("confidence") or 0),
        "opportunity_stage": stage,
        "opportunity_score": score,
        "entry_quality_score": entry_score,
        "reasons": opportunity_reasons(
            support_report=support_report,
            latest_patterns=list(latest_candle.get("patterns") or []),
            latest_reversal_patterns=list(latest_candle.get("reversal_patterns") or []),
            indecision_score=indecision_score,
            reversal_bias=reversal_bias,
            reversal_score=bullish_reversal_score,
            confirmed=confirmed,
            latest_bearish=latest_bearish,
            quality_support_reclaim=quality_support_reclaim,
            support_quality=support_quality,
        ),
        "near_support": near_support,
        "inside_support_zone": inside_support_zone,
        "support_reclaim": support_reclaim,
        "quality_support_reclaim": quality_support_reclaim,
        "support_distance_percent": support_report.get("support_distance_percent"),
        "nearest_support": support_report.get("nearest_support"),
        "support_strength": support_quality["support_strength"],
        "support_touch_count": support_quality["support_touch_count"],
        "support_recency_sessions": support_quality["support_recency_sessions"],
        "latest_patterns": list(latest_candle.get("patterns") or []),
        "latest_reversal_patterns": list(latest_candle.get("reversal_patterns") or []),
        "recent_patterns": sources["recent_patterns"],
        "recent_reversal_patterns": sources["recent_reversal_patterns"],
        "recent_indecision_date": sources["recent_indecision_date"],
        "recent_reversal_date": sources["recent_reversal_date"],
        "bullish_reversal_source_date": sources["bullish_reversal_source_date"],
        "confirmation_source": confirmation_source,
        "indecision_score": round(indecision_score, 2),
        "reversal_score": round(bullish_reversal_score, 2),
        "reversal_bias": reversal_bias,
        "suggested_next_action": suggested_next_action(stage, entry_score, latest_bearish),
    }


def classify_stage(
    *,
    near_support: bool,
    inside_support_zone: bool,
    support_reclaim: bool,
    indecision_score: float,
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
) -> OpportunityStage:
    if confirmed and not latest_bearish:
        return "confirmed_reversal"
    if not latest_bearish and reversal_bias in ("bullish", "mixed") and reversal_score >= 35:
        return "bullish_reversal_watch"
    if support_reclaim:
        return "support_reclaim"
    if (near_support or inside_support_zone) and indecision_score > 0:
        return "indecision_near_support"
    if near_support or inside_support_zone:
        return "near_support"
    return "downtrend_only"


def opportunity_score(
    *,
    near_support: bool,
    inside_support_zone: bool,
    support_reclaim: bool,
    quality_support_reclaim: bool,
    indecision_score: float,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    support_strength: float | None,
    support_touch_count: int | None,
    support_recency_sessions: int | None,
) -> float:
    score = 20.0
    if near_support:
        score += 15
    if inside_support_zone:
        score += 20
    if support_reclaim:
        score += 15
    if quality_support_reclaim:
        score += 10
    score += min(max(indecision_score, 0), 100) * 0.15
    score += min(max(reversal_score, 0), 100) * 0.25
    if confirmed:
        score += 15
    if latest_bearish:
        score -= 25
    if support_strength is not None and support_strength < 40:
        score -= 10
    if support_touch_count == 1:
        score -= 8
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score -= 8
    if latest_bearish:
        score = min(score, 65)
    return round(min(max(score, 0), 100), 2)


def entry_quality_score(
    *,
    candles: list[dict[str, Any]],
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    near_support: bool,
    inside_support_zone: bool,
    quality_support_reclaim: bool,
    support_strength: float | None,
    support_touch_count: int | None,
    support_recency_sessions: int | None,
) -> float:
    score = 0.0
    close_above_prior_high = len(candles) >= 2 and float(candles[-1]["close"]) > float(candles[-2]["high"])
    if confirmed and not latest_bearish:
        score += 30
    if reversal_bias in ("bullish", "mixed") and not latest_bearish:
        score += 15
    if close_above_prior_high and not latest_bearish:
        score += 10
    if quality_support_reclaim:
        score += 20
    if inside_support_zone:
        score += 10
    elif near_support:
        score += 5
    if support_strength is not None:
        if support_strength >= 70:
            score += 15
        elif support_strength >= 40:
            score += 8
        else:
            score -= 20
    if support_touch_count == 1:
        score -= 15
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score -= 15
    if not latest_bearish:
        score += 10
    else:
        score -= 35
    if reversal_score <= 0 and not close_above_prior_high:
        score = min(score, 55)
    if support_strength is not None and support_strength < 40:
        score = min(score, 55)
    if support_touch_count == 1:
        score = min(score, 50)
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score = min(score, 55)
    if latest_bearish:
        score = min(score, 30)
    return round(min(max(score, 0), 100), 2)


def support_quality_fields(
    support_report: dict[str, Any],
    latest_close: float,
    latest_bearish: bool,
) -> dict[str, Any]:
    nearest_support = support_report.get("nearest_support") or {}
    support_strength = optional_float(nearest_support.get("strength"))
    support_touch_count = optional_int(nearest_support.get("touch_count"))
    support_recency_sessions = optional_int(nearest_support.get("recency_sessions"))
    mid_price = optional_float(nearest_support.get("mid_price"))
    close_reclaimed_mid = mid_price is not None and latest_close > mid_price
    quality_support_reclaim = (
        bool(support_report.get("support_reclaim"))
        and (bool(support_report.get("inside_support_zone")) or close_reclaimed_mid)
        and not latest_bearish
    )
    return {
        "quality_support_reclaim": quality_support_reclaim,
        "support_strength": support_strength,
        "support_touch_count": support_touch_count,
        "support_recency_sessions": support_recency_sessions,
    }


def recent_signal_sources(candles: list[dict[str, Any]], candle_items: list[dict[str, Any]]) -> dict[str, Any]:
    start = max(0, len(candle_items) - 3)
    recent_pairs = [(index, candle_items[index]) for index in range(start, len(candle_items))]
    recent_patterns = sorted(
        {
            pattern
            for _, item in recent_pairs
            for pattern in list(item.get("patterns") or [])
        }
    )
    recent_reversal_patterns = sorted(
        {
            pattern
            for _, item in recent_pairs
            for pattern in list(item.get("reversal_patterns") or [])
        }
    )
    indecision_source = max(
        recent_pairs,
        key=lambda pair: float(pair[1].get("indecision_score") or 0),
        default=None,
    )
    reversal_source = max(
        recent_pairs,
        key=lambda pair: float(pair[1].get("reversal_score") or 0),
        default=None,
    )
    bullish_source = max(
        (
            pair
            for pair in recent_pairs
            if pair[1].get("reversal_bias") in ("bullish", "mixed")
        ),
        key=lambda pair: float(pair[1].get("reversal_score") or 0),
        default=None,
    )
    indecision_score = float(indecision_source[1].get("indecision_score") or 0) if indecision_source else 0.0
    reversal_score = float(reversal_source[1].get("reversal_score") or 0) if reversal_source else 0.0
    bullish_reversal_score = float(bullish_source[1].get("reversal_score") or 0) if bullish_source else 0.0
    return {
        "recent_items": [item for _, item in recent_pairs],
        "recent_patterns": recent_patterns,
        "recent_reversal_patterns": recent_reversal_patterns,
        "indecision_score": indecision_score,
        "bullish_reversal_score": bullish_reversal_score,
        "recent_indecision_date": source_date(candles, indecision_source) if indecision_score > 0 else None,
        "recent_reversal_date": source_date(candles, reversal_source) if reversal_score > 0 else None,
        "bullish_reversal_source_date": (
            source_date(candles, bullish_source) if bullish_reversal_score > 0 else None
        ),
    }


def latest_has_bearish_evidence(latest_candle: dict[str, Any]) -> bool:
    if latest_candle.get("reversal_bias") == "bearish":
        return True
    latest_reversal_patterns = set(latest_candle.get("reversal_patterns") or [])
    return bool(latest_reversal_patterns & BEARISH_REVERSAL_BLOCKERS)


def source_date(candles: list[dict[str, Any]], source: tuple[int, dict[str, Any]] | None) -> str | None:
    if source is None:
        return None
    index, item = source
    return str(item.get("trading_date") or candles[index]["trading_date"])


def latest_reversal_bias(latest_candle: dict[str, Any], recent_candles: list[dict[str, Any]]) -> str:
    latest_bias = str(latest_candle.get("reversal_bias") or "none")
    if latest_bias in ("bullish", "mixed"):
        return latest_bias
    if latest_bias == "bearish":
        return "bearish"
    if any(
        item.get("reversal_bias") in ("bullish", "mixed")
        and float(item.get("reversal_score") or 0) > 0
        for item in recent_candles
    ):
        return "bullish"
    return latest_bias if latest_bias in ("bearish", "none") else "none"


def bullish_confirmation(
    candles: list[dict[str, Any]],
    candle_items: list[dict[str, Any]],
    bullish_reversal_score: float,
    latest_bearish: bool = False,
) -> tuple[bool, str | None]:
    if latest_bearish or bullish_reversal_score < STRONG_BULLISH_REVERSAL_SCORE or len(candles) < 2:
        return False, None
    latest_close = float(candles[-1]["close"])
    if latest_close > float(candles[-2]["high"]):
        return True, "latest_close_above_prior_high"
    start = max(0, len(candle_items) - 3)
    for index in range(start, len(candle_items) - 1):
        item = candle_items[index]
        if item.get("reversal_bias") not in ("bullish", "mixed"):
            continue
        if float(item.get("reversal_score") or 0) < STRONG_BULLISH_REVERSAL_SCORE:
            continue
        if latest_close > float(candles[index]["high"]):
            return True, "latest_close_above_bullish_reversal_high"
    return False, None


def opportunity_reasons(
    *,
    support_report: dict[str, Any],
    latest_patterns: list[str],
    latest_reversal_patterns: list[str],
    indecision_score: float,
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    quality_support_reclaim: bool,
    support_quality: dict[str, Any],
) -> list[str]:
    reasons = ["regime_downtrend"]
    if support_report.get("inside_support_zone"):
        reasons.append("inside_support_zone")
    elif support_report.get("near_support"):
        distance = support_report.get("support_distance_percent")
        reasons.append(f"near_support_{distance}%")
    if support_report.get("support_reclaim"):
        reasons.append("support_reclaim")
    if quality_support_reclaim:
        reasons.append("quality_support_reclaim")
    if latest_bearish:
        reasons.append("latest_bearish_reversal_evidence")
    if support_quality.get("support_strength") is not None and float(support_quality["support_strength"]) < 40:
        reasons.append("weak_support_strength")
    if support_quality.get("support_touch_count") == 1:
        reasons.append("single_touch_support")
    if (
        support_quality.get("support_recency_sessions") is not None
        and int(support_quality["support_recency_sessions"]) > 90
    ):
        reasons.append("old_support_zone")
    if indecision_score > 0:
        reasons.append("recent_indecision")
    if latest_patterns:
        reasons.append("latest_patterns:" + ",".join(latest_patterns))
    if reversal_bias in ("bullish", "mixed") and reversal_score > 0:
        reasons.append("bullish_reversal_watch")
    if latest_reversal_patterns:
        reasons.append("latest_reversal_patterns:" + ",".join(latest_reversal_patterns))
    if confirmed:
        reasons.append("latest_close_confirmed_above_reversal_high")
    if len(reasons) == 1:
        reasons.append("no_support_or_candle_clue")
    return reasons


def suggested_next_action(stage: str, entry_quality: float = 0, latest_bearish: bool = False) -> SuggestedNextAction:
    if latest_bearish and entry_quality < 30:
        return "ignore"
    if latest_bearish:
        return "wait_for_confirmation"
    if stage == "downtrend_only":
        return "watch_only"
    if stage in ("near_support", "indecision_near_support", "support_reclaim"):
        return "wait_for_confirmation"
    if stage == "bullish_reversal_watch":
        return "wait_for_breakout"
    if stage == "confirmed_reversal":
        if entry_quality < 55:
            return "wait_for_confirmation"
        return "ready_for_drishti_review"
    if stage == "entry_watch":
        return "wait_for_pullback"
    return "ignore"


def stage_rank(stage: str) -> int:
    ranks = {
        "confirmed_reversal": 0,
        "entry_watch": 1,
        "bullish_reversal_watch": 2,
        "support_reclaim": 3,
        "indecision_near_support": 4,
        "near_support": 5,
        "downtrend_only": 6,
        "ignore": 7,
    }
    return ranks.get(stage, 99)


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_and_sort_items(
    items: list[dict[str, Any]],
    *,
    limit: int,
    include_watch_only: bool,
    min_score: float,
    min_entry_quality_score: float,
) -> list[dict[str, Any]]:
    filtered = []
    for item in items:
        if not include_watch_only and item["suggested_next_action"] == "watch_only":
            continue
        if float(item["opportunity_score"]) < min_score:
            continue
        if float(item["entry_quality_score"]) < min_entry_quality_score:
            continue
        filtered.append(item)
    return sorted(
        filtered,
        key=lambda item: (
            -float(item["entry_quality_score"]),
            -float(item["opportunity_score"]),
            stage_rank(str(item["opportunity_stage"])),
            str(item["symbol"]),
        ),
    )[: min(max(limit, 1), 500)]


def latest_item_date(items: list[dict[str, Any]]) -> str:
    dates = [str(item.get("latest_date") or "") for item in items if item.get("latest_date")]
    if dates:
        return max(dates)
    return now_utc().date().isoformat()


def select_replay_dates(
    trading_sessions: list[str],
    *,
    start_date: str | None,
    end_date: str | None,
    sample_every_n_sessions: int,
    max_dates: int,
) -> list[str]:
    if len(trading_sessions) <= 10:
        return []
    safe_sessions = sorted(set(trading_sessions))[:-10]
    if start_date:
        safe_sessions = [session for session in safe_sessions if session >= start_date]
    if end_date:
        safe_sessions = [session for session in safe_sessions if session <= end_date]
    sample_step = max(int(sample_every_n_sessions), 1)
    max_count = min(max(int(max_dates), 1), 500)
    if start_date is None and end_date is None:
        safe_sessions = safe_sessions[-(max_count * sample_step) :]
    sampled = safe_sessions[::sample_step]
    return sampled[-max_count:]


def build_backfill_response(
    *,
    items: list[dict[str, Any]],
    run_ids: list[int],
    replay_dates: list[str],
    sample_every_n_sessions: int,
    min_entry_quality_score: float,
) -> dict[str, Any]:
    status_counts = {
        "complete": 0,
        "partial": 0,
        "not_enough_future_candles": 0,
    }
    for item in items:
        status = str(item.get("outcome_status") or "")
        if status in status_counts:
            status_counts[status] += 1
    return {
        "run_count": len(run_ids),
        "run_ids": run_ids,
        "item_count": len(items),
        "complete_count": status_counts["complete"],
        "partial_count": status_counts["partial"],
        "not_enough_future_candles_count": status_counts["not_enough_future_candles"],
        "date_range": {
            "start_date": replay_dates[0] if replay_dates else None,
            "end_date": replay_dates[-1] if replay_dates else None,
        },
        "sample_every_n_sessions": sample_every_n_sessions,
        "min_entry_quality_score": float(min_entry_quality_score),
        "stage_summary": group_backfill_items(items, lambda item: str(item["opportunity_stage"])),
        "entry_quality_summary": group_backfill_items(
            items,
            lambda item: entry_quality_bucket(float(item["entry_quality_score"])),
        ),
    }


def group_backfill_items(items: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(key_fn(item), []).append(item)
    return [
        {
            "group": key,
            "count": len(group_items),
            "average_1d_return_percent": average_metric(group_items, "outcome_1d_return_percent"),
            "average_3d_return_percent": average_metric(group_items, "outcome_3d_return_percent"),
            "average_5d_return_percent": average_metric(group_items, "outcome_5d_return_percent"),
            "average_10d_return_percent": average_metric(group_items, "outcome_10d_return_percent"),
            "average_max_favorable_10d_percent": average_metric(group_items, "max_favorable_10d_percent"),
            "average_max_adverse_10d_percent": average_metric(group_items, "max_adverse_10d_percent"),
            "support_broken_rate": support_broken_rate(group_items),
        }
        for key, group_items in sorted(groups.items())
    ]


def average_metric(items: list[dict[str, Any]], field: str) -> float | None:
    values = [float(item[field]) for item in items if item.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def support_broken_rate(items: list[dict[str, Any]]) -> float:
    values = [item.get("support_broken_10d") for item in items if item.get("support_broken_10d") is not None]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 4)


def entry_quality_bucket(score: float) -> str:
    if score >= 75:
        return "75_plus"
    if score >= 65:
        return "65_74"
    if score >= 55:
        return "55_64"
    return "under_55"


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def bool_to_int(value: Any) -> int:
    return 1 if bool(value) else 0


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def run_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "universe_name": row["universe_name"],
        "run_date": row["run_date"],
        "generated_at": row["generated_at"],
        "min_score": float(row["min_score"]),
        "min_entry_quality_score": float(row["min_entry_quality_score"]),
        "include_watch_only": bool(row["include_watch_only"]),
        "limit": int(row["limit_value"]),
        "item_count": int(row["item_count"]),
        "run_type": row.get("run_type") or "live",
        "source": row.get("source") or "manual",
    }


def snapshot_item_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "run_id": int(row["run_id"]),
        "instrument_id": int(row["instrument_id"]),
        "symbol": row["symbol"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "signal_date": row["signal_date"],
        "latest_close": float(row["latest_close"]),
        "regime": row["regime"],
        "regime_confidence": float(row["regime_confidence"]),
        "opportunity_stage": row["opportunity_stage"],
        "opportunity_score": float(row["opportunity_score"]),
        "entry_quality_score": float(row["entry_quality_score"]),
        "suggested_next_action": row["suggested_next_action"],
        "near_support": bool(row["near_support"]),
        "inside_support_zone": bool(row["inside_support_zone"]),
        "support_reclaim": bool(row["support_reclaim"]),
        "quality_support_reclaim": bool(row["quality_support_reclaim"]),
        "support_distance_percent": optional_float(row.get("support_distance_percent")),
        "support_strength": optional_float(row.get("support_strength")),
        "support_touch_count": optional_int(row.get("support_touch_count")),
        "support_recency_sessions": optional_int(row.get("support_recency_sessions")),
        "indecision_score": float(row["indecision_score"]),
        "reversal_score": float(row["reversal_score"]),
        "reversal_bias": row["reversal_bias"],
        "recent_indecision_date": row.get("recent_indecision_date"),
        "recent_reversal_date": row.get("recent_reversal_date"),
        "bullish_reversal_source_date": row.get("bullish_reversal_source_date"),
        "confirmation_source": row.get("confirmation_source"),
        "reasons": json_loads(row.get("reasons_json"), []),
        "latest_patterns": json_loads(row.get("latest_patterns_json"), []),
        "latest_reversal_patterns": json_loads(row.get("latest_reversal_patterns_json"), []),
        "recent_patterns": json_loads(row.get("recent_patterns_json"), []),
        "recent_reversal_patterns": json_loads(row.get("recent_reversal_patterns_json"), []),
        "nearest_support": json_loads(row.get("nearest_support_json"), None),
        "outcome_1d_return_percent": optional_float(row.get("outcome_1d_return_percent")),
        "outcome_3d_return_percent": optional_float(row.get("outcome_3d_return_percent")),
        "outcome_5d_return_percent": optional_float(row.get("outcome_5d_return_percent")),
        "outcome_10d_return_percent": optional_float(row.get("outcome_10d_return_percent")),
        "max_favorable_10d_percent": optional_float(row.get("max_favorable_10d_percent")),
        "max_adverse_10d_percent": optional_float(row.get("max_adverse_10d_percent")),
        "support_broken_10d": optional_bool(row.get("support_broken_10d")),
        "outcome_status": row["outcome_status"],
        "outcome_checked_at": row.get("outcome_checked_at"),
    }


def calculate_outcome(item: dict[str, Any], future_candles: list[dict[str, Any]]) -> dict[str, Any]:
    signal_close = float(item["latest_close"])
    support_zone_low = support_zone_low_from_item(item)
    highs = [float(candle["high"]) for candle in future_candles]
    lows = [float(candle["low"]) for candle in future_candles]
    outcome = {
        "outcome_1d_return_percent": nth_close_return(signal_close, future_candles, 1),
        "outcome_3d_return_percent": nth_close_return(signal_close, future_candles, 3),
        "outcome_5d_return_percent": nth_close_return(signal_close, future_candles, 5),
        "outcome_10d_return_percent": nth_close_return(signal_close, future_candles, 10),
        "max_favorable_10d_percent": round(percent_change(signal_close, max(highs)), 2) if highs else None,
        "max_adverse_10d_percent": round(percent_change(signal_close, min(lows)), 2) if lows else None,
        "support_broken_10d": (
            any(low < support_zone_low for low in lows) if support_zone_low is not None and lows else False
        ),
        "outcome_status": outcome_status(len(future_candles)),
        "outcome_checked_at": now_utc().isoformat(),
    }
    return outcome


def support_zone_low_from_item(item: dict[str, Any]) -> float | None:
    nearest_support = item.get("nearest_support")
    if isinstance(nearest_support, dict):
        return optional_float(nearest_support.get("zone_low"))
    return None


def nth_close_return(signal_close: float, future_candles: list[dict[str, Any]], sessions: int) -> float | None:
    if len(future_candles) < sessions:
        return None
    return round(percent_change(signal_close, float(future_candles[sessions - 1]["close"])), 2)


def percent_change(base: float, value: float) -> float:
    if base == 0:
        return 0.0
    return ((value - base) / base) * 100


def outcome_status(future_count: int) -> str:
    if future_count >= 10:
        return "complete"
    if future_count > 0:
        return "partial"
    return "not_enough_future_candles"
