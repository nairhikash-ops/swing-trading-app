from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paper_trader_continuity import build_plan, write_continuity  # noqa: E402
from reconstruct_paper_ledger import ensure_empty_output_dir  # noqa: E402


TRADING_DATES = [
    "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
    "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14",
    "2026-07-15", "2026-07-16", "2026-07-17",
]


def test_detects_interior_v8_gap_and_refuses_out_of_order_replay() -> None:
    plan = build_plan(
        ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-17"],
        TRADING_DATES,
    )

    assert plan.status == "invalid_gap"
    assert plan.forward_valid is False
    assert plan.run_dates == ()
    assert list(plan.missing_dates) == TRADING_DATES[3:-1]


def test_plans_only_actual_trailing_trading_sessions() -> None:
    plan = build_plan(TRADING_DATES[:8], TRADING_DATES)

    assert plan.status == "healthy"
    assert plan.forward_valid is True
    assert list(plan.run_dates) == TRADING_DATES[8:]


def test_duplicate_report_dates_invalidate_the_epoch() -> None:
    plan = build_plan(["2026-07-16", "2026-07-17", "2026-07-17"], TRADING_DATES[-2:])

    assert plan.status == "invalid_duplicate"
    assert plan.forward_valid is False
    assert plan.duplicate_dates == ("2026-07-17",)


def test_fresh_epoch_starts_at_latest_date_without_backdating() -> None:
    plan = build_plan([], TRADING_DATES)

    assert plan.status == "new_epoch"
    assert plan.run_dates == ("2026-07-17",)
    assert plan.coverage_start == "2026-07-17"


def test_replayed_sessions_remain_labeled_reconstructed(tmp_path: Path) -> None:
    path = tmp_path / "continuity_status.json"
    plan = build_plan(TRADING_DATES, TRADING_DATES)

    write_continuity(
        path,
        strategy_id="v8_demo",
        plan=plan,
        replayed_dates=["2026-07-16", "2026-07-17"],
        message="complete",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "reconstructed"
    assert payload["forward_valid"] is False
    assert payload["replayed_dates"] == ["2026-07-16", "2026-07-17"]


def test_reconstruction_requires_a_fresh_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "reconstruction"
    ensure_empty_output_dir(output_dir)
    (output_dir / "evidence.txt").write_text("preserve", encoding="utf-8")

    try:
        ensure_empty_output_dir(output_dir)
    except RuntimeError as exc:
        assert "fresh empty directory" in str(exc)
    else:
        raise AssertionError("non-empty reconstruction directory was accepted")
