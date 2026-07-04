import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path(
    r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3"
)
BRANCH_A_CSV = Path(
    r"D:\app\data\exports\sweep_sideways_expectancy\uptrend_sideways_branch\branch_a_upward_first.csv"
)
OUT_DIR = Path(r"D:\app\data\exports\uptrend_sideways_live_rule")

BASE_DAYS = 30
BASE_RANGE_MAX = 0.08
PRE_RETURN_DAYS = 60
PRE_RETURN_MIN = 0.10
BREAKOUT_BUFFER = 1.005
TARGET_PCT = 0.10
LOOKAHEAD_DAYS = 40


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 10), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    print("--- Uptrend Sideways Live Rule Historical Test ---")
    print(f"DB Path: {DEFAULT_DB_PATH}")
    print(f"DB SHA256: {file_sha256(DEFAULT_DB_PATH)}")
    if not BRANCH_A_CSV.exists():
        raise FileNotFoundError(BRANCH_A_CSV)

    out = pd.read_csv(BRANCH_A_CSV)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "uptrend_sideways_live_rule_signals.csv"
    out_json = OUT_DIR / "uptrend_sideways_live_rule_summary.json"
    out.to_csv(out_csv, index=False)

    summary = {
        "db_path": str(DEFAULT_DB_PATH),
        "db_sha256": file_sha256(DEFAULT_DB_PATH),
        "source_branch_a_csv": str(BRANCH_A_CSV),
        "rule": {
            "base_days": BASE_DAYS,
            "base_range_max": BASE_RANGE_MAX,
            "pre_return_days": PRE_RETURN_DAYS,
            "pre_return_min": PRE_RETURN_MIN,
            "breakout_buffer": BREAKOUT_BUFFER,
            "target_pct_from_base_high": TARGET_PCT,
            "lookahead_days": LOOKAHEAD_DAYS,
        },
        "signal_count": int(len(out)),
        "reached_10pct_40d_count": int(out["reached_10pct_above_base_high_40d"].sum())
        if len(out)
        else 0,
        "reached_10pct_40d_pct": float(out["reached_10pct_above_base_high_40d"].mean())
        if len(out)
        else 0,
        "average_max_return_40d_pct": float(out["max_return_from_base_high_40d"].mean() * 100)
        if len(out)
        else 0,
        "median_max_return_40d_pct": float(out["max_return_from_base_high_40d"].median() * 100)
        if len(out)
        else 0,
        "output_csv": str(out_csv),
    }
    with out_json.open("w") as f:
        json.dump(summary, f, indent=4)

    print(json.dumps(summary, indent=4))


if __name__ == "__main__":
    main()
