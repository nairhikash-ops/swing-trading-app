from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.store import TokenStore
from app.timezone import now_utc


STATUS_ORDER = {"healthy": 0, "warning": 1, "blocked": 2}


@dataclass(frozen=True)
class Candle:
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class DataQualityService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.token_store = token_store

    def _connect(self):
        return self.token_store._connect()

    def report(self, status_filter: str = "exceptions", limit: int = 200) -> dict[str, Any]:
        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT * FROM historical_fetch_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if run is None:
                return empty_report()

            items = conn.execute(
                """
                SELECT * FROM historical_fetch_items
                WHERE run_id = ?
                ORDER BY company_name
                """,
                (run["id"],),
            ).fetchall()
            mapped_count = int(run["mapped_symbols"] or 0)
            min_coverage = max(1, int(mapped_count * self.settings.data_quality_session_coverage_ratio))
            session_rows = conn.execute(
                """
                SELECT trading_date, COUNT(DISTINCT instrument_id) AS coverage
                FROM daily_candles
                WHERE trading_date >= ? AND trading_date < ?
                  AND instrument_id IN (
                    SELECT instrument_id FROM historical_fetch_items
                    WHERE run_id = ? AND instrument_id IS NOT NULL
                  )
                GROUP BY trading_date
                HAVING coverage >= ?
                ORDER BY trading_date
                """,
                (run["from_date"], run["to_date_exclusive"], run["id"], min_coverage),
            ).fetchall()
            candle_rows = conn.execute(
                """
                SELECT hfi.id AS fetch_item_id, dc.trading_date, dc.open, dc.high, dc.low, dc.close, dc.volume
                FROM historical_fetch_items hfi
                JOIN daily_candles dc ON dc.instrument_id = hfi.instrument_id
                WHERE hfi.run_id = ?
                  AND dc.trading_date >= ? AND dc.trading_date < ?
                ORDER BY hfi.id, dc.trading_date
                """,
                (run["id"], run["from_date"], run["to_date_exclusive"]),
            ).fetchall()

        expected_sessions = [row["trading_date"] for row in session_rows]
        expected_set = set(expected_sessions)
        latest_expected = expected_sessions[-1] if expected_sessions else None
        candles_by_item: dict[int, list[Candle]] = {}
        for row in candle_rows:
            candles_by_item.setdefault(row["fetch_item_id"], []).append(
                Candle(
                    trading_date=row["trading_date"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

        with self._connect() as conn:
            archive_rows = conn.execute(
                """
                SELECT hfi.id AS fetch_item_id, a.*
                FROM historical_fetch_items hfi
                LEFT JOIN historical_instrument_archive a ON a.instrument_id = hfi.instrument_id
                  AND a.source_provider = 'dhan'
                  AND a.interval = 'daily'
                WHERE hfi.run_id = ?
                """,
                (run["id"],),
            ).fetchall()
        archive_by_item = {row["fetch_item_id"]: dict(row) for row in archive_rows}

        quality_items = []
        for item in items:
            item_dict = dict(item)
            archive = archive_by_item.get(item["id"], {})
            effective_expected = expected_sessions_for_item(expected_sessions, archive)
            quality_items.append(
                self._classify_item(
                    item_dict,
                    candles_by_item.get(item["id"], []),
                    effective_expected,
                    set(effective_expected),
                    latest_expected,
                    archive,
                )
            )
        summary = build_summary(run=dict(run), expected_sessions=expected_sessions, quality_items=quality_items)
        filtered_items = filter_items(quality_items, status_filter)
        filtered_items.sort(key=lambda item: (STATUS_ORDER[item["quality_status"]] * -1, item["symbol"]))
        return {
            **summary,
            "items": filtered_items[: min(max(limit, 1), 500)],
        }

    def _classify_item(
        self,
        item: dict[str, Any],
        candles: list[Candle],
        expected_sessions: list[str],
        expected_set: set[str],
        latest_expected: str | None,
        archive: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []
        quality_status = "healthy"

        archive_status = archive_status_for_item(item, archive, latest_expected)
        if item["status"] == "skipped_unmapped":
            issues.append("UNMAPPED_INSTRUMENT")
            quality_status = "blocked"
        elif item["status"] == "failed":
            issues.append("FETCH_FAILED")
            quality_status = "blocked"

        candle_dates = {candle.trading_date for candle in candles}
        latest_candle_date = max(candle_dates) if candle_dates else None
        missing_sessions = len(expected_set - candle_dates)
        invalid_ohlc = 0
        negative_volume = 0
        zero_volume = 0
        extreme_moves = 0
        previous_close: float | None = None

        for candle in sorted(candles, key=lambda value: value.trading_date):
            if (
                candle.open <= 0
                or candle.high <= 0
                or candle.low <= 0
                or candle.close <= 0
                or candle.high < max(candle.open, candle.low, candle.close)
                or candle.low > min(candle.open, candle.high, candle.close)
            ):
                invalid_ohlc += 1
            if candle.volume < 0:
                negative_volume += 1
            if candle.volume == 0:
                zero_volume += 1
            if previous_close and previous_close > 0:
                close_move = abs((candle.close - previous_close) / previous_close) * 100
                gap_move = abs((candle.open - previous_close) / previous_close) * 100
                if max(close_move, gap_move) >= self.settings.data_quality_extreme_move_percent:
                    extreme_moves += 1
            previous_close = candle.close

        if item["status"] not in ("skipped_unmapped", "failed"):
            if not candles and item["status"] != "skipped_no_new_data":
                issues.append("NO_CANDLES")
                quality_status = "blocked"
            if latest_expected and latest_expected not in candle_dates and item["status"] != "skipped_no_new_data":
                issues.append("STALE_LATEST_CANDLE")
                quality_status = "blocked"
            if missing_sessions and item["status"] != "skipped_no_new_data":
                issues.append("MISSING_SESSIONS")
                if missing_sessions >= self.settings.data_quality_block_missing_sessions:
                    quality_status = "blocked"
                elif quality_status != "blocked":
                    quality_status = "warning"
            if invalid_ohlc:
                issues.append("INVALID_OHLC")
                quality_status = "blocked"
            if negative_volume:
                issues.append("NEGATIVE_VOLUME")
                quality_status = "blocked"
            if zero_volume:
                issues.append("ZERO_VOLUME")
                if quality_status != "blocked":
                    quality_status = "warning"
            if extreme_moves:
                issues.append("EXTREME_MOVE")
                if quality_status != "blocked":
                    quality_status = "warning"

        return {
            "symbol": item["symbol"],
            "company_name": item["company_name"],
            "industry": item["industry"],
            "isin": item["isin"],
            "security_id": item["security_id"],
            "quality_status": quality_status,
            "issues": sorted(set(issues)),
            "latest_candle_date": latest_candle_date,
            "first_stored_candle_date": archive.get("first_stored_candle_date"),
            "source_floor_reached": bool(archive.get("source_floor_reached") or False),
            "source_floor_date": archive.get("source_floor_date"),
            "source_floor_reason": archive.get("source_floor_reason") or "unknown",
            "complete_available_history": bool(archive.get("complete_available_history") or False),
            "next_retry_after": archive.get("next_retry_after"),
            "archive_status": archive_status,
            "archive_message": archive_message(archive_status, archive),
            "effective_start_date": expected_sessions[0] if expected_sessions else archive.get("first_stored_candle_date"),
            "expected_sessions": len(expected_sessions),
            "candle_count": len(candles),
            "missing_sessions": missing_sessions,
            "invalid_ohlc_count": invalid_ohlc,
            "zero_volume_count": zero_volume,
            "negative_volume_count": negative_volume,
            "extreme_move_count": extreme_moves,
            "fetch_status": item["status"],
            "fetch_error": item["error"],
        }


def build_summary(run: dict[str, Any], expected_sessions: list[str], quality_items: list[dict[str, Any]]) -> dict[str, Any]:
    healthy = sum(1 for item in quality_items if item["quality_status"] == "healthy")
    warning = sum(1 for item in quality_items if item["quality_status"] == "warning")
    blocked = sum(1 for item in quality_items if item["quality_status"] == "blocked")
    issue_counts: dict[str, int] = {}
    for item in quality_items:
        for issue in item["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    return {
        "generated_at": now_utc(),
        "historical_run_id": run["id"],
        "historical_run_status": run["status"],
        "from_date": run["from_date"],
        "to_date_exclusive": run["to_date_exclusive"],
        "latest_expected_session": expected_sessions[-1] if expected_sessions else None,
        "expected_session_count": len(expected_sessions),
        "total_symbols": len(quality_items),
        "healthy_count": healthy,
        "warning_count": warning,
        "blocked_count": blocked,
        "issue_counts": issue_counts,
    }


def expected_sessions_for_item(expected_sessions: list[str], archive: dict[str, Any]) -> list[str]:
    effective_start = archive.get("first_stored_candle_date")
    if bool(archive.get("complete_available_history")) and effective_start:
        return [session for session in expected_sessions if session >= effective_start]
    return expected_sessions


def archive_status_for_item(item: dict[str, Any], archive: dict[str, Any], latest_expected: str | None) -> str:
    if item["status"] == "failed":
        return "fetch_failed"
    if item["status"] == "skipped_unmapped":
        return "unmapped"
    if item["status"] == "skipped_no_new_data" and item.get("archive_status") == "older_history_backfill":
        if bool(archive.get("complete_available_history")):
            return "complete_available_history_saved"
        if bool(archive.get("source_floor_reached")):
            return "dhan_source_floor_reached"
    if item["status"] == "skipped_no_new_data":
        return "waiting_for_next_session"
    latest_stored = archive.get("latest_stored_candle_date")
    if latest_expected and latest_stored and latest_stored >= latest_expected:
        return "up_to_date"
    if bool(archive.get("complete_available_history")):
        return "complete_available_history_saved"
    if bool(archive.get("source_floor_reached")):
        return "dhan_source_floor_reached"
    return "needs_update"


def archive_message(status: str, archive: dict[str, Any]) -> str:
    reason = archive.get("source_floor_reason") or "unknown"
    if status == "up_to_date":
        if reason == "stock_listed_recently":
            return "Newly listed stock - limited history available"
        if reason == "dhan_5_year_limit":
            return "Up to date - Dhan source floor reached"
        return "Up to date"
    if status == "complete_available_history_saved":
        if reason == "stock_listed_recently":
            return "Newly listed stock - limited history available"
        if reason == "dhan_5_year_limit":
            return "Dhan source floor reached"
        return "Complete available history saved"
    if status == "waiting_for_next_session":
        return "Waiting for next trading session"
    if status == "fetch_failed":
        return "Fetch failed"
    if status == "unmapped":
        return "No active Dhan instrument mapping"
    if status == "dhan_source_floor_reached":
        return "Dhan source floor reached"
    return "Needs update"


def filter_items(items: list[dict[str, Any]], status_filter: str) -> list[dict[str, Any]]:
    normalized = status_filter.lower()
    if normalized == "all":
        return items
    if normalized in ("healthy", "warning", "blocked"):
        return [item for item in items if item["quality_status"] == normalized]
    return [item for item in items if item["quality_status"] != "healthy"]


def empty_report() -> dict[str, Any]:
    return {
        "generated_at": now_utc(),
        "historical_run_id": None,
        "historical_run_status": "missing",
        "from_date": "",
        "to_date_exclusive": "",
        "latest_expected_session": None,
        "expected_session_count": 0,
        "total_symbols": 0,
        "healthy_count": 0,
        "warning_count": 0,
        "blocked_count": 0,
        "issue_counts": {},
        "items": [],
    }
