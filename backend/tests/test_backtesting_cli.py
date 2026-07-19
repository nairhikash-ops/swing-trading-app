from __future__ import annotations

import json

import pandas as pd

from app.backtesting.cli import main


def test_cli_runs_end_to_end_and_refuses_overwrite(tmp_path) -> None:
    csv_path = tmp_path / "candles.csv"
    output_path = tmp_path / "result"
    values = [10, 9, 8, 10, 12, 13, 14]
    pd.DataFrame(
        [("AAA", f"2026-01-{day:02d}", value, value + 1, value - 1, value, 100) for day, value in enumerate(values, 1)],
        columns=["symbol", "date", "open", "high", "low", "close", "volume"],
    ).to_csv(csv_path, index=False)
    args = [
        "--source", "csv", "--csv", str(csv_path),
        "--strategy-params", '{"fast_window":2,"slow_window":3,"atr_window":2}',
        "--output-dir", str(output_path), "--commission-bps", "0", "--slippage-bps", "0", "--taxes-bps", "0",
    ]
    assert main(args) == 0
    summary = json.loads((output_path / "summary.json").read_text())
    assert summary["strategy"] == "moving_average_cross"
    assert summary["signal_count"] == 1
    try:
        main(args)
    except SystemExit as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("CLI overwrote an existing result directory")
