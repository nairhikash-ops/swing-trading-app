from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class ContinuityPlan:
    status: str
    forward_valid: bool
    coverage_start: str | None
    coverage_end: str | None
    processed_dates: tuple[str, ...]
    missing_dates: tuple[str, ...]
    run_dates: tuple[str, ...]
    duplicate_dates: tuple[str, ...] = ()


def read_report_dates(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [str(row["date"]) for row in csv.DictReader(handle) if row.get("date")]


def fetch_latest_date(base_url: str) -> str:
    with urlopen(f"{base_url}/api/matsya/market-data/status", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latest = payload.get("latest_candle_date")
    if not latest:
        raise RuntimeError("Matsya latest_candle_date is empty.")
    return str(latest)


def fetch_trading_dates(base_url: str, from_date: str, to_date: str) -> list[str]:
    query = urlencode({"from": from_date, "to": to_date})
    with urlopen(f"{base_url}/api/matsya/market-data/trading-dates?{query}", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [str(value) for value in payload.get("trading_dates") or []]


def build_plan(processed_dates: list[str], available_dates: list[str]) -> ContinuityPlan:
    duplicate_dates = tuple(sorted(value for value, count in Counter(processed_dates).items() if count > 1))
    processed = tuple(sorted(set(processed_dates)))
    available = tuple(sorted(set(available_dates)))
    if not available:
        return ContinuityPlan("no_market_dates", False, None, None, processed, (), (), duplicate_dates)
    if duplicate_dates:
        return ContinuityPlan(
            "invalid_duplicate", False, processed[0] if processed else None,
            processed[-1] if processed else None, processed, (), (), duplicate_dates,
        )
    if not processed:
        latest = available[-1]
        return ContinuityPlan("new_epoch", True, latest, latest, (), (), (latest,), ())

    coverage_start = processed[0]
    coverage_end = processed[-1]
    expected = tuple(value for value in available if value >= coverage_start)
    processed_set = set(processed)
    missing = tuple(value for value in expected if value not in processed_set)
    interior = tuple(value for value in missing if value <= coverage_end)
    trailing = tuple(value for value in missing if value > coverage_end)
    if interior:
        return ContinuityPlan(
            "invalid_gap", False, coverage_start, coverage_end, processed, interior + trailing, ()
        )
    return ContinuityPlan("healthy", True, coverage_start, available[-1], processed, (), trailing)


def read_continuity(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_continuity(
    path: Path,
    *,
    strategy_id: str,
    plan: ContinuityPlan,
    replayed_dates: list[str] | None = None,
    message: str,
) -> None:
    prior = read_continuity(path)
    recovered = sorted(
        set(str(value) for value in (prior.get("replayed_dates") or []) if value)
        | set(replayed_dates or [])
    )
    payload = {
        **asdict(plan),
        "strategy_id": strategy_id,
        "replayed_dates": recovered,
        "message": message,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if recovered and payload["status"] == "healthy":
        payload["status"] = "reconstructed"
        payload["forward_valid"] = False
        payload["message"] = "Missing sessions were replayed after the fact; start a new epoch for forward validation."
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
