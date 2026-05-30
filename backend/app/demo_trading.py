from typing import Any

from app.config import Settings
from app.learning import LearningStore
from app.store import TokenStore
from app.timezone import now_utc


ORDER_PENDING_ENTRY = "pending_entry"
ORDER_FILLED = "filled"
ORDER_REJECTED = "rejected"
POSITION_OPEN = "open"
POSITION_CLOSED = "closed"
SIDE_LONG = "long"


class DemoTradingStore:
    def __init__(self, token_store: TokenStore, settings: Settings) -> None:
        self.token_store = token_store
        self.settings = settings
        self._init_db()
        self.ensure_account()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_accounts (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    currency TEXT NOT NULL DEFAULT 'INR',
                    cash_balance REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_signal_hit_id INTEGER,
                    decision_snapshot_id INTEGER,
                    ai_review_id INTEGER,
                    source_signal_id TEXT NOT NULL,
                    source_run_id INTEGER,
                    instrument_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_date TEXT NOT NULL,
                    requested_price REAL NOT NULL,
                    fill_after_date TEXT NOT NULL,
                    filled_date TEXT,
                    filled_price REAL,
                    entry_low REAL,
                    entry_high REAL,
                    stop_loss REAL NOT NULL,
                    target_price REAL,
                    trailing_stop_loss REAL,
                    risk_reward REAL NOT NULL,
                    rejection_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_signal_hit_id, side)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    source_signal_hit_id INTEGER,
                    decision_snapshot_id INTEGER,
                    ai_review_id INTEGER,
                    instrument_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_low REAL,
                    entry_high REAL,
                    stop_loss REAL NOT NULL,
                    target_price REAL NOT NULL,
                    trailing_stop_loss REAL,
                    risk_amount REAL NOT NULL,
                    risk_reward REAL NOT NULL,
                    status TEXT NOT NULL,
                    latest_candle_date TEXT,
                    latest_close REAL,
                    holding_sessions INTEGER NOT NULL DEFAULT 0,
                    unrealized_pnl REAL NOT NULL DEFAULT 0,
                    unrealized_pnl_percent REAL NOT NULL DEFAULT 0,
                    exit_date TEXT,
                    exit_price REAL,
                    exit_reason TEXT NOT NULL DEFAULT '',
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    realized_pnl_percent REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            ensure_columns(
                conn,
                "demo_orders",
                {
                    "decision_snapshot_id": "INTEGER",
                    "ai_review_id": "INTEGER",
                    "entry_low": "REAL",
                    "entry_high": "REAL",
                    "trailing_stop_loss": "REAL",
                },
            )
            ensure_columns(
                conn,
                "demo_positions",
                {
                    "decision_snapshot_id": "INTEGER",
                    "ai_review_id": "INTEGER",
                    "entry_low": "REAL",
                    "entry_high": "REAL",
                    "trailing_stop_loss": "REAL",
                },
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_orders_status ON demo_orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_positions_status ON demo_positions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_positions_symbol ON demo_positions(symbol)")
        self.learning_store = LearningStore(self.token_store)

    def ensure_account(self) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO demo_accounts (id, cash_balance, realized_pnl, created_at, updated_at)
                VALUES (1, ?, 0, ?, ?)
                """,
                (self.settings.demo_initial_cash, timestamp, timestamp),
            )

    def signal_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM drishti_signal_hits WHERE id = ?", (hit_id,)).fetchone()
        return dict(row) if row else None

    def order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM demo_orders WHERE id = ?", (order_id,)).fetchone()
        return order_row_to_dict(row) if row else None

    def order_for_signal_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM demo_orders
                WHERE source_signal_hit_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (hit_id,),
            ).fetchone()
        return order_row_to_dict(row) if row else None

    def position_for_order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM demo_positions WHERE order_id = ?", (order_id,)).fetchone()
        return position_row_to_dict(row) if row else None

    def insert_order_from_hit(
        self,
        hit: dict[str, Any],
        quantity: float,
        risk_reward: float,
        stop_loss: float | None = None,
        target_price: float | None = None,
        entry_low: float | None = None,
        entry_high: float | None = None,
        trailing_stop_loss: float | None = None,
        ai_review_id: int | None = None,
        fill_after_date: str | None = None,
    ) -> int:
        timestamp = now_utc().isoformat()
        effective_stop_loss = stop_loss if stop_loss is not None else hit["anchor_low"]
        snapshot = self.learning_store.ensure_snapshot_for_hit(int(hit["id"]))
        effective_fill_after_date = fill_after_date or hit["trigger_date"]
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO demo_orders (
                    source_signal_hit_id, decision_snapshot_id, ai_review_id,
                    source_signal_id, source_run_id, instrument_id,
                    company_name, industry, symbol, isin, security_id, side, quantity, order_type,
                    status, trigger_date, requested_price, fill_after_date, entry_low, entry_high,
                    stop_loss, target_price, trailing_stop_loss, risk_reward,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'next_session_open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hit["id"],
                    snapshot.get("id"),
                    ai_review_id,
                    hit["signal_id"],
                    hit["run_id"],
                    hit["instrument_id"],
                    hit["company_name"],
                    hit["industry"],
                    hit["symbol"],
                    hit["isin"],
                    hit["security_id"],
                    SIDE_LONG,
                    quantity,
                    ORDER_PENDING_ENTRY,
                    hit["trigger_date"],
                    hit["trigger_close"],
                    effective_fill_after_date,
                    entry_low,
                    entry_high,
                    effective_stop_loss,
                    target_price,
                    trailing_stop_loss,
                    risk_reward,
                    timestamp,
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def pending_orders(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM demo_orders
                WHERE status = ?
                ORDER BY id
                """,
                (ORDER_PENDING_ENTRY,),
            ).fetchall()
        return [order_row_to_dict(row) for row in rows]

    def open_positions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM demo_positions
                WHERE status = ?
                ORDER BY entry_date, id
                """,
                (POSITION_OPEN,),
            ).fetchall()
        return [position_row_to_dict(row) for row in rows]

    def reset_ledger(self) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            order_count = conn.execute("SELECT COUNT(*) AS count FROM demo_orders").fetchone()["count"]
            position_count = conn.execute("SELECT COUNT(*) AS count FROM demo_positions").fetchone()["count"]
            conn.execute("DELETE FROM demo_positions")
            conn.execute("DELETE FROM demo_orders")
            conn.execute(
                """
                UPDATE demo_accounts
                SET cash_balance = ?, realized_pnl = 0, updated_at = ?
                WHERE id = 1
                """,
                (self.settings.demo_initial_cash, timestamp),
            )
        return {
            "deleted_orders": int(order_count or 0),
            "deleted_positions": int(position_count or 0),
            "summary": self.summary(),
        }

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

    def candles_for_position(self, position: dict[str, Any]) -> list[dict[str, Any]]:
        latest_date = position.get("latest_candle_date")
        if latest_date:
            where_date = "trading_date > ?"
            date_param = latest_date
        else:
            where_date = "trading_date >= ?"
            date_param = position["entry_date"]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND {where_date}
                ORDER BY trading_date
                """,
                (position["instrument_id"], date_param),
            ).fetchall()
        return [dict(row) for row in rows]

    def reject_order(self, order_id: int, reason: str) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE demo_orders
                SET status = ?, rejection_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (ORDER_REJECTED, reason, timestamp, order_id),
            )
        return self.order(order_id) or {}

    def fill_order(self, order: dict[str, Any], candle: dict[str, Any], target_price: float, risk_amount: float) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        cost = float(order["quantity"]) * float(candle["open"])
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM demo_accounts WHERE id = 1").fetchone()
            cash_balance = float(account["cash_balance"]) if account else 0
            if cost > cash_balance:
                conn.execute(
                    """
                    UPDATE demo_orders
                    SET status = ?, rejection_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (ORDER_REJECTED, "Insufficient demo cash for next-session fill.", timestamp, order["id"]),
                )
                return order_row_to_dict(conn.execute("SELECT * FROM demo_orders WHERE id = ?", (order["id"],)).fetchone())

            conn.execute(
                """
                UPDATE demo_accounts
                SET cash_balance = cash_balance - ?, updated_at = ?
                WHERE id = 1
                """,
                (cost, timestamp),
            )
            conn.execute(
                """
                UPDATE demo_orders
                SET status = ?, filled_date = ?, filled_price = ?, target_price = ?, updated_at = ?
                WHERE id = ?
                """,
                (ORDER_FILLED, candle["trading_date"], candle["open"], target_price, timestamp, order["id"]),
            )
            conn.execute(
                """
                INSERT INTO demo_positions (
                    order_id, source_signal_hit_id, decision_snapshot_id, ai_review_id, instrument_id, company_name, industry, symbol,
                    isin, security_id, side, quantity, entry_date, entry_price, entry_low, entry_high,
                    stop_loss, target_price, trailing_stop_loss, risk_amount, risk_reward, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["id"],
                    order["source_signal_hit_id"],
                    order.get("decision_snapshot_id"),
                    order.get("ai_review_id"),
                    order["instrument_id"],
                    order["company_name"],
                    order["industry"],
                    order["symbol"],
                    order["isin"],
                    order["security_id"],
                    order["side"],
                    order["quantity"],
                    candle["trading_date"],
                    candle["open"],
                    order.get("entry_low"),
                    order.get("entry_high"),
                    order["stop_loss"],
                    target_price,
                    order.get("trailing_stop_loss"),
                    risk_amount,
                    order["risk_reward"],
                    POSITION_OPEN,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM demo_orders WHERE id = ?", (order["id"],)).fetchone()
        return order_row_to_dict(row)

    def update_position_mark(self, position_id: int, candle: dict[str, Any], holding_sessions: int) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            position = conn.execute("SELECT * FROM demo_positions WHERE id = ?", (position_id,)).fetchone()
            quantity = float(position["quantity"])
            entry_price = float(position["entry_price"])
            latest_close = float(candle["close"])
            unrealized_pnl = (latest_close - entry_price) * quantity
            unrealized_pnl_percent = ((latest_close - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            conn.execute(
                """
                UPDATE demo_positions
                SET latest_candle_date = ?, latest_close = ?, holding_sessions = ?,
                    unrealized_pnl = ?, unrealized_pnl_percent = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    candle["trading_date"],
                    latest_close,
                    holding_sessions,
                    unrealized_pnl,
                    unrealized_pnl_percent,
                    timestamp,
                    position_id,
                ),
            )
            row = conn.execute("SELECT * FROM demo_positions WHERE id = ?", (position_id,)).fetchone()
        return position_row_to_dict(row)

    def close_position(
        self,
        position_id: int,
        candle: dict[str, Any],
        holding_sessions: int,
        exit_price: float,
        exit_reason: str,
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            position = conn.execute("SELECT * FROM demo_positions WHERE id = ?", (position_id,)).fetchone()
            quantity = float(position["quantity"])
            entry_price = float(position["entry_price"])
            realized_pnl = (exit_price - entry_price) * quantity
            realized_pnl_percent = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            conn.execute(
                """
                UPDATE demo_accounts
                SET cash_balance = cash_balance + ?, realized_pnl = realized_pnl + ?, updated_at = ?
                WHERE id = 1
                """,
                (exit_price * quantity, realized_pnl, timestamp),
            )
            conn.execute(
                """
                UPDATE demo_positions
                SET status = ?, latest_candle_date = ?, latest_close = ?, holding_sessions = ?,
                    unrealized_pnl = 0, unrealized_pnl_percent = 0, exit_date = ?, exit_price = ?,
                    exit_reason = ?, realized_pnl = ?, realized_pnl_percent = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    POSITION_CLOSED,
                    candle["trading_date"],
                    candle["close"],
                    holding_sessions,
                    candle["trading_date"],
                    exit_price,
                    exit_reason,
                    realized_pnl,
                    realized_pnl_percent,
                    timestamp,
                    position_id,
                ),
            )
            row = conn.execute("SELECT * FROM demo_positions WHERE id = ?", (position_id,)).fetchone()
        return position_row_to_dict(row)

    def list_orders(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM demo_orders
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 500)),
            ).fetchall()
        return [order_row_to_dict(row) for row in rows]

    def list_positions(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM demo_positions
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 500)),
            ).fetchall()
        return [position_row_to_dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM demo_accounts WHERE id = 1").fetchone()
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'pending_entry' THEN 1 ELSE 0 END) AS pending_orders,
                    SUM(CASE WHEN status = 'filled' THEN 1 ELSE 0 END) AS filled_orders,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_orders
                FROM demo_orders
                """
            ).fetchone()
            position_counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_positions,
                    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_positions,
                    COALESCE(SUM(CASE WHEN status = 'open' THEN quantity * COALESCE(latest_close, entry_price) ELSE 0 END), 0)
                        AS open_market_value,
                    COALESCE(SUM(CASE WHEN status = 'open' THEN unrealized_pnl ELSE 0 END), 0)
                        AS unrealized_pnl
                FROM demo_positions
                """
            ).fetchone()

        cash_balance = float(account["cash_balance"]) if account else 0.0
        open_market_value = float(position_counts["open_market_value"] or 0)
        realized_pnl = float(account["realized_pnl"]) if account else 0.0
        unrealized_pnl = float(position_counts["unrealized_pnl"] or 0)
        return {
            "currency": account["currency"] if account else "INR",
            "cash_balance": cash_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "open_market_value": open_market_value,
            "equity_value": cash_balance + open_market_value,
            "pending_orders": int(counts["pending_orders"] or 0),
            "filled_orders": int(counts["filled_orders"] or 0),
            "rejected_orders": int(counts["rejected_orders"] or 0),
            "open_positions": int(position_counts["open_positions"] or 0),
            "closed_positions": int(position_counts["closed_positions"] or 0),
            "updated_at": account["updated_at"] if account else now_utc().isoformat(),
        }


class DemoTradingService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.store = DemoTradingStore(token_store, settings)

    def place_order_from_drishti_hit(
        self,
        hit_id: int,
        quantity: float | None = None,
        risk_reward: float | None = None,
        stop_loss: float | None = None,
        target_price: float | None = None,
        entry_low: float | None = None,
        entry_high: float | None = None,
        trailing_stop_loss: float | None = None,
        ai_review_id: int | None = None,
        fill_after_date: str | None = None,
    ) -> dict[str, Any]:
        hit = self.store.signal_hit(hit_id)
        if hit is None:
            raise ValueError("Drishti signal hit was not found.")

        existing = self.store.order_for_signal_hit(hit_id)
        if existing:
            self.refresh()
            return {
                "order": self.store.order(int(existing["id"])) or existing,
                "position": self.store.position_for_order(int(existing["id"])),
                "summary": self.store.summary(),
            }

        order_id = self.store.insert_order_from_hit(
            hit=hit,
            quantity=quantity or self.settings.demo_default_quantity,
            risk_reward=risk_reward or self.settings.demo_default_risk_reward,
            stop_loss=stop_loss,
            target_price=target_price,
            entry_low=entry_low,
            entry_high=entry_high,
            trailing_stop_loss=trailing_stop_loss,
            ai_review_id=ai_review_id,
            fill_after_date=fill_after_date,
        )
        self.refresh()
        return {
            "order": self.store.order(order_id) or {},
            "position": self.store.position_for_order(order_id),
            "summary": self.store.summary(),
        }

    def refresh(self) -> dict[str, Any]:
        filled_orders: list[dict[str, Any]] = []
        rejected_orders: list[dict[str, Any]] = []
        updated_positions: list[dict[str, Any]] = []
        closed_positions: list[dict[str, Any]] = []

        for order in self.store.pending_orders():
            candle = self.store.first_candle_after(int(order["instrument_id"]), str(order["fill_after_date"]))
            if candle is None:
                continue
            entry_price = float(candle["open"])
            entry_low = optional_float(order.get("entry_low"))
            entry_high = optional_float(order.get("entry_high"))
            if entry_low is not None and entry_price < entry_low:
                rejected_orders.append(
                    self.store.reject_order(int(order["id"]), "Next-session open was below the AI entry range.")
                )
                continue
            if entry_high is not None and entry_price > entry_high:
                rejected_orders.append(
                    self.store.reject_order(int(order["id"]), "Next-session open was above the AI entry range.")
                )
                continue
            stop_loss = float(order["stop_loss"])
            risk_amount = entry_price - stop_loss
            if risk_amount <= 0:
                rejected_orders.append(
                    self.store.reject_order(int(order["id"]), "Next-session entry is not above the signal stop loss.")
                )
                continue
            target_price = optional_float(order.get("target_price")) or entry_price + risk_amount * float(order["risk_reward"])
            filled = self.store.fill_order(order, candle, target_price, risk_amount)
            if filled["status"] == ORDER_REJECTED:
                rejected_orders.append(filled)
                continue
            filled_orders.append(filled)

        for position in self.store.open_positions():
            result = self._process_position(position)
            if not result:
                continue
            self.store.learning_store.upsert_trade_outcome(result)
            if result["status"] == POSITION_CLOSED:
                closed_positions.append(result)
            else:
                updated_positions.append(result)

        return {
            "filled_orders": filled_orders,
            "rejected_orders": rejected_orders,
            "updated_positions": updated_positions,
            "closed_positions": closed_positions,
            "summary": self.store.summary(),
        }

    def _process_position(self, position: dict[str, Any]) -> dict[str, Any] | None:
        current = position
        for candle in self.store.candles_for_position(position):
            holding_sessions = int(current["holding_sessions"]) + 1
            stop_loss = float(current["stop_loss"])
            target_price = float(current["target_price"])
            low = float(candle["low"])
            high = float(candle["high"])
            if low <= stop_loss:
                return self.store.close_position(int(current["id"]), candle, holding_sessions, stop_loss, "STOP_LOSS")
            if high >= target_price:
                return self.store.close_position(int(current["id"]), candle, holding_sessions, target_price, "TARGET")
            if holding_sessions >= self.settings.demo_max_holding_sessions:
                return self.store.close_position(
                    int(current["id"]),
                    candle,
                    holding_sessions,
                    float(candle["close"]),
                    "TIME_EXIT",
                )
            current = self.store.update_position_mark(int(current["id"]), candle, holding_sessions)
        return current if current != position else None

    def summary(self) -> dict[str, Any]:
        return self.store.summary()

    def orders(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_orders(status=status, limit=limit)

    def positions(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_positions(status=status, limit=limit)

    def reset_ledger(self) -> dict[str, Any]:
        return self.store.reset_ledger()


def ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
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


def order_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"] if "decision_snapshot_id" in row.keys() else None,
        "ai_review_id": row["ai_review_id"] if "ai_review_id" in row.keys() else None,
        "source_signal_id": row["source_signal_id"],
        "source_run_id": row["source_run_id"],
        "instrument_id": row["instrument_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "side": row["side"],
        "quantity": row["quantity"],
        "order_type": row["order_type"],
        "status": row["status"],
        "trigger_date": row["trigger_date"],
        "requested_price": row["requested_price"],
        "fill_after_date": row["fill_after_date"],
        "filled_date": row["filled_date"],
        "filled_price": row["filled_price"],
        "entry_low": row["entry_low"] if "entry_low" in row.keys() else None,
        "entry_high": row["entry_high"] if "entry_high" in row.keys() else None,
        "stop_loss": row["stop_loss"],
        "target_price": row["target_price"],
        "trailing_stop_loss": row["trailing_stop_loss"] if "trailing_stop_loss" in row.keys() else None,
        "risk_reward": row["risk_reward"],
        "rejection_reason": row["rejection_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def position_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"] if "decision_snapshot_id" in row.keys() else None,
        "ai_review_id": row["ai_review_id"] if "ai_review_id" in row.keys() else None,
        "instrument_id": row["instrument_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "side": row["side"],
        "quantity": row["quantity"],
        "entry_date": row["entry_date"],
        "entry_price": row["entry_price"],
        "entry_low": row["entry_low"] if "entry_low" in row.keys() else None,
        "entry_high": row["entry_high"] if "entry_high" in row.keys() else None,
        "stop_loss": row["stop_loss"],
        "target_price": row["target_price"],
        "trailing_stop_loss": row["trailing_stop_loss"] if "trailing_stop_loss" in row.keys() else None,
        "risk_amount": row["risk_amount"],
        "risk_reward": row["risk_reward"],
        "status": row["status"],
        "latest_candle_date": row["latest_candle_date"],
        "latest_close": row["latest_close"],
        "holding_sessions": row["holding_sessions"],
        "unrealized_pnl": row["unrealized_pnl"],
        "unrealized_pnl_percent": row["unrealized_pnl_percent"],
        "exit_date": row["exit_date"],
        "exit_price": row["exit_price"],
        "exit_reason": row["exit_reason"],
        "realized_pnl": row["realized_pnl"],
        "realized_pnl_percent": row["realized_pnl_percent"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
