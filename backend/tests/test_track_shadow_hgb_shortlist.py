# backend/tests/test_track_shadow_hgb_shortlist.py
"""Tests for the updated track_shadow_hgb_shortlist script.
Ensures correct ceil‑based bucket cut‑offs, dry‑run safety, and duplicate handling.
"""
import json
import sqlite3
import pandas as pd
from pathlib import Path
from app.scripts.track_shadow_hgb_shortlist import run_track_shadow_hgb_shortlist, DEFAULT_DB_PATH

def _create_fake_rankings(csv_path: Path, meta_path: Path, rows: int = 448):
    df = pd.DataFrame({
        "rank": range(1, rows + 1),
        "symbol": [f"SYM{i:03d}" for i in range(1, rows + 1)],
        "win_probability": [0.5] * rows,
        "market_median_20d_return": [0] * rows,
        "market_breakout_rate": [0] * rows,
        "market_breakdown_rate": [0] * rows,
        "market_breadth_delta": [0] * rows,
        "market_cross_sectional_volatility": [0] * rows,
        "stock_20d_return_minus_market_median": [0] * rows,
        "stock_is_stronger_than_market": [0] * rows,
        "stock_breakout_while_market_weak": [0] * rows,
    })
    df.to_csv(csv_path, index=False)
    meta = {
        "is_live_today": False,
        "model_version": "stock_opportunity_hgb_regime_v1",
        "scored_sample_date": "2026-05-18",
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

def test_bucket_cutoffs_and_dry_run(tmp_path, capsys):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    csv_path = exports_dir / "latest_hgb_regime_rankings.csv"
    meta_path = exports_dir / "latest_hgb_regime_rankings.meta.json"
    _create_fake_rankings(csv_path, meta_path, rows=448)
    db_path = tmp_path / "shadow_tracking.sqlite3"
    run_track_shadow_hgb_shortlist(
        exports_dir=str(exports_dir),
        db_path=str(db_path),
        allow_live_today=True,
        execute=False,
    )
    out = capsys.readouterr().out
    assert "HGB Ranking rows: 448" in out
    assert "HGB Top 5% tracked: 23" in out
    assert "HGB Primary Top 1%: 5" in out
    assert "HGB WATCH_TOP_5 rows: 18" in out
    assert "[DRY-RUN] HGB records that would be inserted: 23" in out
    assert not db_path.exists()

def test_execute_inserts_and_duplicate_safe(tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    csv_path = exports_dir / "latest_hgb_regime_rankings.csv"
    meta_path = exports_dir / "latest_hgb_regime_rankings.meta.json"
    _create_fake_rankings(csv_path, meta_path, rows=448)
    db_path = tmp_path / "shadow_tracking.sqlite3"
    # first run
    run_track_shadow_hgb_shortlist(
        exports_dir=str(exports_dir),
        db_path=str(db_path),
        allow_live_today=True,
        execute=True,
    )
    conn = sqlite3.connect(db_path)
    cnt = conn.execute("SELECT COUNT(1) FROM shadow_tracking WHERE model_version=?", ("stock_opportunity_hgb_regime_v1",)).fetchone()[0]
    conn.close()
    assert cnt == 23
    # second run – duplicates
    run_track_shadow_hgb_shortlist(
        exports_dir=str(exports_dir),
        db_path=str(db_path),
        allow_live_today=True,
        execute=True,
    )
    conn = sqlite3.connect(db_path)
    cnt2 = conn.execute("SELECT COUNT(1) FROM shadow_tracking WHERE model_version=?", ("stock_opportunity_hgb_regime_v1",)).fetchone()[0]
    conn.close()
    assert cnt2 == 23
    # add dummy LR row
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO shadow_tracking (date_scored, scored_sample_date, model_version, model_commit, rank, bucket, symbol, win_probability, regime_context_json, tracking_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-18T00:00:00Z", "2026-05-18", "stock_opportunity_ohlcv_regime_v1", "dummy", 1, "PRIMARY_TOP_1", "SYM001", 0.6, "{}", "OBSERVING", "now", "now"),
    )
    conn.commit()
    lr_cnt = conn.execute("SELECT COUNT(1) FROM shadow_tracking WHERE model_version=?", ("stock_opportunity_ohlcv_regime_v1",)).fetchone()[0]
    conn.close()
    assert lr_cnt == 1
