# backend/tests/test_track_shadow_hgb_shortlist.py
"""Tests for the updated track_shadow_hgb_shortlist script.
Ensures correct ceil‑based bucket cut‑offs, dry‑run safety, and duplicate handling.
"""
import json
import sqlite3
import pandas as pd
import pytest
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


# ---------------------------------------------------------------------------
# V1.25: Explicit --ranked-csv / --meta-json path tests
# ---------------------------------------------------------------------------

def _create_named_rankings(
    csv_path: Path,
    meta_path: Path,
    scored_sample_date: str,
    rows: int = 448,
):
    """Create a ranked CSV and meta JSON at explicit (named) paths."""
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
        "scored_sample_date": scored_sample_date,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)


def test_explicit_csv_and_meta_paths_used(tmp_path, capsys):
    """When --ranked-csv and --meta-json are both supplied, those files are used
    instead of the latest-file defaults."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    # Write ONLY the explicit dated files — no latest files exist
    csv_path  = exports_dir / "hgb_regime_rankings_2026-05-21.csv"
    meta_path = exports_dir / "hgb_regime_rankings_2026-05-21.meta.json"
    _create_named_rankings(csv_path, meta_path, scored_sample_date="2026-05-21")

    db_path = tmp_path / "shadow_tracking.sqlite3"
    run_track_shadow_hgb_shortlist(
        exports_dir=str(exports_dir),
        db_path=str(db_path),
        allow_live_today=True,
        execute=False,
        ranked_csv=str(csv_path),
        meta_json=str(meta_path),
    )
    out = capsys.readouterr().out
    # Tracker must report the date from the explicit meta, not a default
    assert "2026-05-21" in out
    assert "[DRY-RUN] HGB records that would be inserted: 23" in out


def test_supplying_only_ranked_csv_fails_loudly(tmp_path):
    """Supplying --ranked-csv without --meta-json raises ValueError immediately."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    csv_path = exports_dir / "hgb_regime_rankings_2026-05-21.csv"
    _create_named_rankings(
        csv_path,
        exports_dir / "hgb_regime_rankings_2026-05-21.meta.json",
        scored_sample_date="2026-05-21",
    )
    db_path = tmp_path / "shadow_tracking.sqlite3"
    with pytest.raises(ValueError, match="must be supplied together"):
        run_track_shadow_hgb_shortlist(
            exports_dir=str(exports_dir),
            db_path=str(db_path),
            allow_live_today=True,
            execute=False,
            ranked_csv=str(csv_path),
            meta_json=None,      # missing!
        )


def test_supplying_only_meta_json_fails_loudly(tmp_path):
    """Supplying --meta-json without --ranked-csv raises ValueError immediately."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    meta_path = exports_dir / "hgb_regime_rankings_2026-05-21.meta.json"
    _create_named_rankings(
        exports_dir / "hgb_regime_rankings_2026-05-21.csv",
        meta_path,
        scored_sample_date="2026-05-21",
    )
    db_path = tmp_path / "shadow_tracking.sqlite3"
    with pytest.raises(ValueError, match="must be supplied together"):
        run_track_shadow_hgb_shortlist(
            exports_dir=str(exports_dir),
            db_path=str(db_path),
            allow_live_today=True,
            execute=False,
            ranked_csv=None,     # missing!
            meta_json=str(meta_path),
        )


def test_explicit_d1_path_used_even_when_latest_points_to_d2(tmp_path, capsys):
    """Explicit D1 paths are used even if latest_* files contain D2 data.

    This is the core wrong-date prevention check: the tracker must
    track the date from the explicit paths, not from the latest files.
    """
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    # Write D1 (2026-05-15) as named archive files
    d1_csv  = exports_dir / "hgb_regime_rankings_2026-05-15.csv"
    d1_meta = exports_dir / "hgb_regime_rankings_2026-05-15.meta.json"
    _create_named_rankings(d1_csv, d1_meta, scored_sample_date="2026-05-15")

    # Also write D2 (2026-05-21) as the latest files
    _create_named_rankings(
        exports_dir / "latest_hgb_regime_rankings.csv",
        exports_dir / "latest_hgb_regime_rankings.meta.json",
        scored_sample_date="2026-05-21",
    )

    db_path = tmp_path / "shadow_tracking.sqlite3"
    run_track_shadow_hgb_shortlist(
        exports_dir=str(exports_dir),
        db_path=str(db_path),
        allow_live_today=True,
        execute=False,
        ranked_csv=str(d1_csv),
        meta_json=str(d1_meta),
    )
    out = capsys.readouterr().out
    # Must show D1's date, NOT D2's date
    assert "2026-05-15" in out, "Explicit D1 date must appear in output"
    assert "2026-05-21" not in out, "D2 (latest) date must NOT appear when D1 paths given"


