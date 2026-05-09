from typing import Any

from app.config import Settings
from app.historical_data import historical_window
from app.index_universe import NIFTY_500_INDEX_NAME
from app.store import TokenStore
from app.timezone import now_utc


class RangeMoverService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.token_store = token_store

    def _connect(self):
        return self.token_store._connect()

    def nifty_500_range_movers(self, threshold_percent: float = 5.0, limit: int = 500) -> dict[str, Any]:
        window = historical_window(self.settings)
        from_date = window.from_date.isoformat()
        to_date_exclusive = window.to_date_exclusive.isoformat()
        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT id FROM historical_fetch_runs
                WHERE universe_name = ?
                  AND status IN ('completed', 'completed_with_errors')
                  AND from_date = ?
                  AND to_date_exclusive = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (NIFTY_500_INDEX_NAME, from_date, to_date_exclusive),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT
                    ic.company_name,
                    ic.industry,
                    ic.symbol,
                    ic.isin,
                    i.security_id,
                    i.id AS instrument_id,
                    dc.trading_date,
                    dc.low,
                    dc.high
                FROM index_constituents ic
                JOIN instruments i ON i.active = 1
                  AND i.exchange_id = 'NSE'
                  AND i.segment = 'E'
                  AND i.instrument = 'EQUITY'
                  AND i.isin = ic.isin
                JOIN daily_candles dc ON dc.instrument_id = i.id
                  AND dc.trading_date >= ?
                  AND dc.trading_date < ?
                WHERE ic.index_name = ? AND ic.active = 1
                ORDER BY ic.symbol, dc.trading_date
                """,
                (from_date, to_date_exclusive, NIFTY_500_INDEX_NAME),
            ).fetchall()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            instrument_id = int(row["instrument_id"])
            current = grouped.setdefault(
                instrument_id,
                {
                    "symbol": row["symbol"],
                    "company_name": row["company_name"],
                    "industry": row["industry"],
                    "isin": row["isin"],
                    "security_id": row["security_id"],
                    "candle_count": 0,
                    "candles": [],
                },
            )
            current["candle_count"] += 1
            current["candles"].append(
                {
                    "trading_date": row["trading_date"],
                    "low": float(row["low"]),
                    "high": float(row["high"]),
                }
            )

        items = []
        for item in grouped.values():
            best_move = best_upward_move(item["candles"])
            if best_move is None or best_move["move_percent"] < threshold_percent:
                continue
            item.pop("candles")
            items.append({**item, **best_move})

        items.sort(key=lambda value: value["move_percent"], reverse=True)
        return {
            "generated_at": now_utc(),
            "historical_run_id": run["id"] if run else None,
            "from_date": from_date,
            "to_date_exclusive": to_date_exclusive,
            "threshold_percent": threshold_percent,
            "total_scanned": len(grouped),
            "match_count": len(items),
            "items": items[: min(max(limit, 1), 500)],
        }


def best_upward_move(candles: list[dict[str, Any]]) -> dict[str, Any] | None:
    lowest_low = None
    lowest_low_date = None
    best = None

    for candle in candles:
        high = candle["high"]
        low = candle["low"]
        trading_date = candle["trading_date"]

        if lowest_low is not None and lowest_low > 0:
            move_percent = ((high - lowest_low) / lowest_low) * 100
            if best is None or move_percent > best["move_percent"]:
                best = {
                    "lowest_low": lowest_low,
                    "lowest_low_date": lowest_low_date,
                    "highest_high": high,
                    "highest_high_date": trading_date,
                    "move_percent": move_percent,
                    "range_amount": high - lowest_low,
                }

        if lowest_low is None or low < lowest_low:
            lowest_low = low
            lowest_low_date = trading_date

    return best
