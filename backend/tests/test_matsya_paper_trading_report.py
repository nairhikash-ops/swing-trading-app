from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from app.matsya.paper_trading_report import PaperTradingReportService, max_drawdown


BACKEND_DIR = Path(__file__).resolve().parents[1]
for scripts_dir in (BACKEND_DIR / "app" / "scripts", BACKEND_DIR / "scripts"):
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

from uptrend_sideways_paper_trader import UPTREND_SCAN_COLUMNS, ensure_scan_csv_schema  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_report_repairs_legacy_uptrend_scan_rows_and_calculates_metrics(tmp_path: Path) -> None:
    v8_dir = tmp_path / "v8"
    sideways_dir = tmp_path / "sideways"
    v8_dir.mkdir()
    sideways_dir.mkdir()

    for directory in (v8_dir, sideways_dir):
        write_csv(
            directory / "daily_report.csv",
            [
                {"date": "2026-07-16", "equity": 100_000, "cash": 100_000, "open_value": 0},
                {"date": "2026-07-17", "equity": 101_500, "cash": 50_000, "open_value": 51_500},
            ],
        )
        (directory / "paper_broker_state.json").write_text(
            json.dumps(
                {
                    "cash": 50_000,
                    "pending_orders": [],
                    "open_positions": [{"symbol": "TEST", "invested_value": 50_000}],
                }
            ),
            encoding="utf-8",
        )
        write_csv(
            directory / "paper_trade_ledger.csv",
            [
                {"symbol": "WIN", "pnl_value": 2_000, "pnl_pct": 0.10},
                {"symbol": "LOSS", "pnl_value": -500, "pnl_pct": -0.025},
            ],
        )

    legacy_header = UPTREND_SCAN_COLUMNS[:14] + ["target_price"]
    legacy_values = [
        "TEST",
        "2026-07-17",
        "upward_breakout",
        "10",
        "0.1",
        "2026-07-03",
        "2026-07-16",
        "100",
        "90",
        "0.1111",
        "0.25",
        "105",
        "106",
        "101",
        "0.05",
        "0.1667",
        "110",
    ]
    with (sideways_dir / "signals.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(legacy_header)
        writer.writerow(legacy_values)

    status = PaperTradingReportService(v8_dir, sideways_dir).combined_status(limit=100)
    sideways = next(item for item in status["strategies"] if item["strategy_id"] == "uptrend_sideways")
    signal = sideways["signals"][0]

    assert signal["target_price"] == 110
    assert signal["move_from_base_high_pct"] == 0.05
    assert signal["move_from_base_low_pct"] == 0.1667
    assert "None" not in signal
    assert sideways["account"]["starting_equity"] == 100_000
    assert sideways["account"]["equity"] == 101_500
    assert sideways["account"]["unrealized_pnl"] == 1_500
    assert sideways["account"]["realized_pnl"] == 1_500
    assert sideways["account"]["return_pct"] == 0.015
    assert sideways["account"]["win_rate"] == 0.5
    assert sideways["account"]["profit_factor"] == 4.0
    assert status["summary"]["starting_equity"] == 200_000
    assert status["summary"]["total_equity"] == 203_000
    assert status["summary"]["total_return_pct"] == 0.015


def test_scan_schema_upgrade_preserves_legacy_target_and_movement_fields(tmp_path: Path) -> None:
    path = tmp_path / "signals.csv"
    legacy_header = UPTREND_SCAN_COLUMNS[:14] + ["target_price"]
    legacy_values = ["TEST", "2026-07-17", "upward_breakout", 10, 0.1, "2026-07-03", "2026-07-16", 100, 90, 0.1, 0.2, 105, 106, 101, 0.05, 0.1667, 110]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(legacy_header)
        writer.writerow(legacy_values)

    ensure_scan_csv_schema(path)

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        assert rows[0]["move_from_base_high_pct"] == "0.05"
        assert rows[0]["move_from_base_low_pct"] == "0.1667"
        assert rows[0]["target_price"] == "110"
        assert list(rows[0]) == UPTREND_SCAN_COLUMNS


def test_max_drawdown_uses_peak_to_trough_decline() -> None:
    assert max_drawdown([100, 110, 99, 120]) == pytest.approx(-0.1)


def test_report_exposes_continuity_and_recovers_legacy_trade_signal_date(tmp_path: Path) -> None:
    v8_dir = tmp_path / "v8"
    sideways_dir = tmp_path / "sideways"
    for directory in (v8_dir, sideways_dir):
        directory.mkdir()
        write_csv(directory / "daily_report.csv", [{"date": "2026-07-17", "equity": 100_000}])
        (directory / "paper_broker_state.json").write_text(
            json.dumps({"cash": 100_000, "pending_orders": [], "open_positions": []}), encoding="utf-8"
        )
        (directory / "continuity_status.json").write_text(
            json.dumps({"status": "healthy", "forward_valid": True, "missing_dates": []}), encoding="utf-8"
        )

    write_csv(
        sideways_dir / "paper_order_ledger.csv",
        [{"symbol": "AEGISVOPAK", "signal_date": "2026-07-03", "target_allocation": 20_000}],
    )
    write_csv(
        sideways_dir / "paper_trade_ledger.csv",
        [{"symbol": "AEGISVOPAK", "entry_date": "2026-07-06", "exit_date": "2026-07-06", "pnl_value": 991.35}],
    )

    status = PaperTradingReportService(v8_dir, sideways_dir).combined_status(limit=100)
    sideways = next(item for item in status["strategies"] if item["strategy_id"] == "uptrend_sideways")

    assert sideways["continuity"]["status"] == "healthy"
    assert sideways["continuity"]["forward_valid"] is True
    assert sideways["closed_trades"][0]["signal_date"] == "2026-07-03"
