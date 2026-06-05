import json
from typing import Any

from app.store import TokenStore
from app.timezone import now_utc


class TradingJournalStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_trade_journal_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    setup_notes TEXT NOT NULL DEFAULT '',
                    management_notes TEXT NOT NULL DEFAULT '',
                    mistake_notes TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def journal(self, status: str = "", symbol: str = "", limit: int = 200) -> dict[str, Any]:
        filters: list[str] = []
        params: list[Any] = []
        normalized_status = status.strip().lower()
        normalized_symbol = symbol.strip().upper()
        if normalized_status:
            filters.append(
                """
                (
                    LOWER(COALESCE(p.status, o.status)) = ?
                    OR LOWER(o.status) = ?
                    OR LOWER(COALESCE(l.outcome_label, '')) = ?
                    OR LOWER(COALESCE(p.exit_reason, '')) = ?
                )
                """
            )
            params.extend([normalized_status, normalized_status, normalized_status, normalized_status])
        if normalized_symbol:
            filters.append("(UPPER(o.symbol) LIKE ? OR UPPER(o.company_name) LIKE ?)")
            params.extend([f"%{normalized_symbol}%", f"%{normalized_symbol}%"])

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(min(max(limit, 1), 500))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    o.id AS order_id,
                    o.source_signal_hit_id,
                    o.decision_snapshot_id,
                    o.ai_review_id,
                    o.source_signal_id,
                    o.source_run_id,
                    o.instrument_id,
                    o.company_name,
                    o.industry,
                    o.symbol,
                    o.isin,
                    o.security_id,
                    o.side,
                    o.quantity,
                    o.order_type,
                    o.status AS order_status,
                    o.trigger_date,
                    o.requested_price,
                    o.fill_after_date,
                    o.filled_date,
                    o.filled_price,
                    o.entry_low,
                    o.entry_high,
                    o.stop_loss,
                    o.target_price,
                    o.trailing_stop_loss,
                    o.risk_reward,
                    o.rejection_reason,
                    o.created_at AS order_created_at,
                    o.updated_at AS order_updated_at,
                    p.id AS position_id,
                    p.status AS position_status,
                    p.entry_date,
                    p.entry_price,
                    p.risk_amount,
                    p.latest_candle_date,
                    p.latest_close,
                    p.holding_sessions,
                    p.unrealized_pnl,
                    p.unrealized_pnl_percent,
                    p.exit_date,
                    p.exit_price,
                    p.exit_reason,
                    p.realized_pnl,
                    p.realized_pnl_percent,
                    l.outcome_label,
                    l.max_favorable_price,
                    l.max_favorable_percent,
                    l.max_adverse_price,
                    l.max_adverse_percent,
                    l.target_hit,
                    l.stop_hit,
                    l.time_exit,
                    r.provider AS review_provider,
                    r.model AS review_model,
                    r.decision AS review_decision,
                    r.confidence AS review_confidence,
                    r.summary AS review_summary,
                    r.wait_until AS review_wait_until,
                    r.invalidation AS review_invalidation,
                    wc.status AS watchlist_status,
                    wc.decision AS watchlist_decision,
                    wc.entry_rule AS watchlist_entry_rule,
                    wc.summary AS watchlist_summary,
                    n.setup_notes,
                    n.management_notes,
                    n.mistake_notes,
                    n.tags_json,
                    n.updated_at AS notes_updated_at
                FROM demo_orders o
                LEFT JOIN demo_positions p ON p.order_id = o.id
                LEFT JOIN learning_trade_outcomes l ON l.position_id = p.id
                LEFT JOIN ai_signal_reviews r ON r.id = o.ai_review_id
                LEFT JOIN watchlist_candidates wc ON wc.entered_order_id = o.id
                LEFT JOIN demo_trade_journal_notes n ON n.order_id = o.id
                {where_sql}
                ORDER BY COALESCE(p.entry_date, o.filled_date, o.created_at) DESC, o.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        items = [journal_row_to_dict(row) for row in rows]
        return {"summary": journal_summary(items), "items": items}

    def upsert_notes(
        self,
        order_id: int,
        setup_notes: str = "",
        management_notes: str = "",
        mistake_notes: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        normalized_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})
        with self._connect() as conn:
            order = conn.execute("SELECT id FROM demo_orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                raise ValueError("Demo order was not found.")
            conn.execute(
                """
                INSERT INTO demo_trade_journal_notes (
                    order_id, setup_notes, management_notes, mistake_notes, tags_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    setup_notes = excluded.setup_notes,
                    management_notes = excluded.management_notes,
                    mistake_notes = excluded.mistake_notes,
                    tags_json = excluded.tags_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order_id,
                    setup_notes,
                    management_notes,
                    mistake_notes,
                    json.dumps(normalized_tags, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        item = next((row for row in self.journal(limit=500)["items"] if row["order_id"] == order_id), None)
        if item is None:
            raise ValueError("Demo order was not found.")
        return item


def journal_row_to_dict(row) -> dict[str, Any]:
    position_status = row["position_status"]
    status = position_status or row["order_status"]
    entry_price = optional_float(row["entry_price"]) or optional_float(row["filled_price"])
    latest_close = optional_float(row["latest_close"])
    exit_price = optional_float(row["exit_price"])
    realized_pnl = float(row["realized_pnl"] or 0)
    unrealized_pnl = float(row["unrealized_pnl"] or 0)
    active_pnl = realized_pnl if status == "closed" else unrealized_pnl
    pnl_percent = float(row["realized_pnl_percent"] or 0) if status == "closed" else float(row["unrealized_pnl_percent"] or 0)
    risk_amount = optional_float(row["risk_amount"])
    if risk_amount is None and entry_price is not None:
        risk_amount = max(entry_price - float(row["stop_loss"]), 0)
    risk_capital = (risk_amount or 0) * float(row["quantity"] or 0)
    r_multiple = active_pnl / risk_capital if risk_capital > 0 else None
    tags = json.loads(row["tags_json"] or "[]") if row["tags_json"] else []
    return {
        "order_id": row["order_id"],
        "position_id": row["position_id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"],
        "ai_review_id": row["ai_review_id"],
        "source_signal_id": row["source_signal_id"],
        "source_run_id": row["source_run_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "side": row["side"],
        "quantity": row["quantity"],
        "status": status,
        "order_status": row["order_status"],
        "position_status": row["position_status"],
        "trigger_date": row["trigger_date"],
        "requested_price": row["requested_price"],
        "fill_after_date": row["fill_after_date"],
        "filled_date": row["filled_date"],
        "filled_price": row["filled_price"],
        "entry_date": row["entry_date"],
        "entry_price": entry_price,
        "entry_low": row["entry_low"],
        "entry_high": row["entry_high"],
        "stop_loss": row["stop_loss"],
        "target_price": row["target_price"],
        "trailing_stop_loss": row["trailing_stop_loss"],
        "risk_amount": risk_amount,
        "risk_reward": row["risk_reward"],
        "latest_candle_date": row["latest_candle_date"],
        "latest_close": latest_close,
        "holding_sessions": row["holding_sessions"] or 0,
        "exit_date": row["exit_date"],
        "exit_price": exit_price,
        "exit_reason": row["exit_reason"] or "",
        "rejection_reason": row["rejection_reason"] or "",
        "realized_pnl": realized_pnl,
        "realized_pnl_percent": row["realized_pnl_percent"] or 0,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_percent": row["unrealized_pnl_percent"] or 0,
        "pnl": active_pnl,
        "pnl_percent": pnl_percent,
        "r_multiple": r_multiple,
        "outcome_label": row["outcome_label"] or ("open" if status == "open" else ""),
        "max_favorable_price": row["max_favorable_price"],
        "max_favorable_percent": row["max_favorable_percent"],
        "max_adverse_price": row["max_adverse_price"],
        "max_adverse_percent": row["max_adverse_percent"],
        "target_hit": bool(row["target_hit"]) if row["target_hit"] is not None else False,
        "stop_hit": bool(row["stop_hit"]) if row["stop_hit"] is not None else False,
        "time_exit": bool(row["time_exit"]) if row["time_exit"] is not None else False,
        "review_provider": row["review_provider"],
        "review_model": row["review_model"],
        "review_decision": row["review_decision"],
        "review_confidence": row["review_confidence"],
        "review_summary": row["review_summary"] or "",
        "review_wait_until": row["review_wait_until"] or "",
        "review_invalidation": row["review_invalidation"] or "",
        "watchlist_status": row["watchlist_status"],
        "watchlist_decision": row["watchlist_decision"],
        "watchlist_entry_rule": row["watchlist_entry_rule"],
        "watchlist_summary": row["watchlist_summary"] or "",
        "setup_notes": row["setup_notes"] or "",
        "management_notes": row["management_notes"] or "",
        "mistake_notes": row["mistake_notes"] or "",
        "tags": tags if isinstance(tags, list) else [],
        "notes_updated_at": row["notes_updated_at"],
        "order_created_at": row["order_created_at"],
        "order_updated_at": row["order_updated_at"],
    }


def journal_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [item for item in items if item["status"] == "closed"]
    open_items = [item for item in items if item["status"] == "open"]
    winners = [item for item in closed if item["outcome_label"] == "winner" or item["exit_reason"] == "TARGET"]
    failures = [item for item in closed if item["outcome_label"] == "failure" or item["exit_reason"] == "STOP_LOSS"]
    r_values = [float(item["r_multiple"]) for item in closed if item.get("r_multiple") is not None]
    return {
        "total_trades": len(items),
        "pending_orders": sum(1 for item in items if item["status"] == "pending_entry"),
        "rejected_orders": sum(1 for item in items if item["status"] == "rejected"),
        "open_positions": len(open_items),
        "closed_positions": len(closed),
        "winners": len(winners),
        "failures": len(failures),
        "neutral": max(len(closed) - len(winners) - len(failures), 0),
        "realized_pnl": sum(float(item["realized_pnl"] or 0) for item in items),
        "unrealized_pnl": sum(float(item["unrealized_pnl"] or 0) for item in open_items),
        "average_r": sum(r_values) / len(r_values) if r_values else 0,
        "win_rate_percent": (len(winners) / len(closed)) * 100 if closed else 0,
    }


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
