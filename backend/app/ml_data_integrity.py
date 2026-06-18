"""
ml_data_integrity.py

Shared helper functions for the ML V1.16 Data Integrity Audit Layer.
All functions are read-only. Nothing here deletes or modifies any data.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_OUTCOMES = {"WIN", "LOSS", "TIMEOUT", "AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA"}
TRAINABLE_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
NON_TRAINABLE_OUTCOMES = {"AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA"}

VALID_BUCKETS = {"PRIMARY_TOP_1", "WATCH_TOP_5"}
VALID_TRACKING_STATUSES = {"OBSERVING", "RESOLVED"}

FORBIDDEN_FEATURE_KEYS = {
    "RSI", "MACD", "EMA", "SMA", "ATR",
    "support", "resistance", "candlestick", "drishti", "regime",
}

EXPECTED_FEATURE_COUNT = 300
EXPECTED_BASE_CSV_COLUMNS = 303   # symbol, sample_date, outcome + 300 features
EXPECTED_REGIME_CSV_COLUMNS = 311  # + 8 regime features

DEFAULT_MAIN_DB = "/app/data/dhan_auth.sqlite3"
DEFAULT_SHADOW_DB = "/app/data/shadow_tracking.sqlite3"
DEFAULT_EXPORTS_DIR = "/app/data/exports"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    name: str
    status: str          # "PASS" | "FAIL" | "SKIP"
    detail: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------

def check_testsym_contamination(main_db: str) -> CheckResult:
    """Check 1: TESTSYM must not exist in any core table."""
    errors: list[str] = []
    try:
        conn = sqlite3.connect(main_db)
        conn.row_factory = sqlite3.Row

        ml_count = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples WHERE UPPER(symbol)='TESTSYM'"
        ).fetchone()["c"]
        if ml_count:
            errors.append(f"ml_samples has {ml_count} TESTSYM row(s)")

        inst_count = conn.execute(
            "SELECT COUNT(*) c FROM instruments WHERE UPPER(underlying_symbol)='TESTSYM'"
        ).fetchone()["c"]
        if inst_count:
            errors.append(f"instruments has {inst_count} TESTSYM row(s)")

        candle_count = conn.execute(
            "SELECT COUNT(*) c FROM daily_candles WHERE instrument_id IN "
            "(SELECT id FROM instruments WHERE UPPER(underlying_symbol)='TESTSYM')"
        ).fetchone()["c"]
        if candle_count:
            errors.append(f"daily_candles has {candle_count} row(s) linked to TESTSYM")

        conn.close()
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    return CheckResult(
        name="testsym_contamination",
        status="PASS" if not errors else "FAIL",
        detail="No TESTSYM contamination found." if not errors else "TESTSYM contamination detected.",
        errors=errors,
    )


def check_ml_samples_duplicates(main_db: str) -> CheckResult:
    """Check 2: No duplicate (model_name, label_name, instrument_id, sample_date) or
    (model_name, label_name, symbol, sample_date) rows."""
    errors: list[str] = []
    try:
        conn = sqlite3.connect(main_db)

        dup_inst = conn.execute(
            "SELECT COUNT(*) c FROM ("
            "  SELECT model_name, label_name, instrument_id, sample_date, COUNT(*) n"
            "  FROM ml_samples"
            "  GROUP BY model_name, label_name, instrument_id, sample_date"
            "  HAVING n > 1"
            ")"
        ).fetchone()[0]
        if dup_inst:
            errors.append(f"{dup_inst} duplicate group(s) by instrument_id + sample_date")

        dup_sym = conn.execute(
            "SELECT COUNT(*) c FROM ("
            "  SELECT model_name, label_name, symbol, sample_date, COUNT(*) n"
            "  FROM ml_samples"
            "  GROUP BY model_name, label_name, symbol, sample_date"
            "  HAVING n > 1"
            ")"
        ).fetchone()[0]
        if dup_sym:
            errors.append(f"{dup_sym} duplicate group(s) by symbol + sample_date")

        conn.close()
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    return CheckResult(
        name="ml_samples_duplicates",
        status="PASS" if not errors else "FAIL",
        detail="No duplicates found." if not errors else "Duplicates detected.",
        errors=errors,
    )


def check_ml_sample_validity(main_db: str) -> CheckResult:
    """Check 3: sample_date non-null, symbol non-null, outcome valid, trainable consistent."""
    errors: list[str] = []
    try:
        conn = sqlite3.connect(main_db)

        null_dates = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples WHERE sample_date IS NULL"
        ).fetchone()[0]
        if null_dates:
            errors.append(f"{null_dates} row(s) have null sample_date")

        null_syms = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples WHERE symbol IS NULL OR TRIM(symbol)=''"
        ).fetchone()[0]
        if null_syms:
            errors.append(f"{null_syms} row(s) have null/blank symbol")

        # Outcome validity
        valid_outcome_list = ", ".join(f"'{o}'" for o in VALID_OUTCOMES)
        bad_outcomes = conn.execute(
            f"SELECT COUNT(*) c FROM ml_samples WHERE outcome NOT IN ({valid_outcome_list})"
        ).fetchone()[0]
        if bad_outcomes:
            errors.append(f"{bad_outcomes} row(s) have invalid outcome values")

        # Trainable consistency: WIN/LOSS/TIMEOUT => trainable=1
        bad_trainable_on = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples "
            "WHERE outcome IN ('WIN','LOSS','TIMEOUT') AND trainable != 1"
        ).fetchone()[0]
        if bad_trainable_on:
            errors.append(f"{bad_trainable_on} row(s) with WIN/LOSS/TIMEOUT but trainable=0")

        # Trainable consistency: AMBIGUOUS/INSUFFICIENT_FUTURE_DATA => trainable=0
        bad_trainable_off = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples "
            "WHERE outcome IN ('AMBIGUOUS','INSUFFICIENT_FUTURE_DATA') AND trainable != 0"
        ).fetchone()[0]
        if bad_trainable_off:
            errors.append(f"{bad_trainable_off} row(s) with AMBIGUOUS/INSUFFICIENT but trainable=1")

        conn.close()
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    return CheckResult(
        name="ml_sample_validity",
        status="PASS" if not errors else "FAIL",
        detail="All sample fields valid." if not errors else "Sample validity issues found.",
        errors=errors,
    )


def check_feature_json_validity(main_db: str, sample_limit: int = 5000) -> CheckResult:
    """Check 4: Feature JSON is valid, has 300 keys, no null/NaN/inf, no forbidden keys."""
    errors: list[str] = []
    try:
        conn = sqlite3.connect(main_db)
        rows = conn.execute(
            "SELECT id, symbol, sample_date, feature_json FROM ml_samples "
            "WHERE trainable = 1 LIMIT ?",
            (sample_limit,)
        ).fetchall()
        conn.close()

        bad_json_count = 0
        wrong_key_count = 0
        null_val_count = 0
        nan_inf_count = 0
        forbidden_key_count = 0

        for row in rows:
            row_id, symbol, sample_date, fj = row
            try:
                feat = json.loads(fj)
            except (json.JSONDecodeError, TypeError):
                bad_json_count += 1
                continue

            if len(feat) != EXPECTED_FEATURE_COUNT:
                wrong_key_count += 1

            for k, v in feat.items():
                # Forbidden key check (substring match)
                k_upper = k.upper()
                for fk in FORBIDDEN_FEATURE_KEYS:
                    if fk.upper() in k_upper:
                        forbidden_key_count += 1
                        break

                if v is None:
                    null_val_count += 1
                elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    nan_inf_count += 1

        if bad_json_count:
            errors.append(f"{bad_json_count} row(s) have invalid/unparseable feature_json")
        if wrong_key_count:
            errors.append(f"{wrong_key_count} row(s) have != {EXPECTED_FEATURE_COUNT} feature keys")
        if null_val_count:
            errors.append(f"{null_val_count} null value(s) found in feature_json")
        if nan_inf_count:
            errors.append(f"{nan_inf_count} NaN/Inf value(s) found in feature_json")
        if forbidden_key_count:
            errors.append(f"{forbidden_key_count} occurrence(s) of forbidden feature key substrings")

    except Exception as exc:
        errors.append(f"DB error: {exc}")

    checked_count = min(sample_limit, len(errors) + (len(rows) if 'rows' in dir() else 0))
    return CheckResult(
        name="feature_json_validity",
        status="PASS" if not errors else "FAIL",
        detail=f"Checked up to {sample_limit} trainable samples.",
        errors=errors,
    )


def check_candle_linkage(main_db: str) -> CheckResult:
    """Check 5: Every ml_samples.instrument_id must exist in instruments.
    Every ml_sample's sample_date must exist in daily_candles for the same instrument_id."""
    errors: list[str] = []
    try:
        conn = sqlite3.connect(main_db)

        # Orphaned instrument_ids
        orphaned = conn.execute(
            "SELECT COUNT(*) c FROM ml_samples "
            "WHERE instrument_id NOT IN (SELECT id FROM instruments)"
        ).fetchone()[0]
        if orphaned:
            errors.append(f"{orphaned} ml_samples row(s) have instrument_id not in instruments")

        # Missing candles for sample_date (spot-check: limit to 200 distinct instruments)
        missing_candles = conn.execute(
            "SELECT COUNT(*) c FROM ("
            "  SELECT DISTINCT ms.instrument_id, ms.sample_date"
            "  FROM ml_samples ms"
            "  WHERE NOT EXISTS ("
            "    SELECT 1 FROM daily_candles dc"
            "    WHERE dc.instrument_id = ms.instrument_id"
            "    AND dc.trading_date = ms.sample_date"
            "  )"
            "  LIMIT 1000"
            ")"
        ).fetchone()[0]
        if missing_candles:
            errors.append(f"{missing_candles} (instrument_id, sample_date) pair(s) have no matching daily_candle")

        conn.close()
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    return CheckResult(
        name="candle_linkage",
        status="PASS" if not errors else "FAIL",
        detail="All instrument and candle links valid." if not errors else "Linkage issues found.",
        errors=errors,
    )


def check_export_artifacts(exports_dir: str) -> CheckResult:
    """Check 6: Export files exist and have the correct column counts."""
    errors: list[str] = []

    required_files = [
        "ml_dataset_ohlcv_v1.csv",
        "ml_dataset_ohlcv_regime_v1.csv",
        "latest_regime_rankings.meta.json",
        "shadow_performance_summary.json",
    ]
    for fname in required_files:
        fpath = os.path.join(exports_dir, fname)
        if not os.path.exists(fpath):
            errors.append(f"Missing export file: {fname}")

    # Check base CSV column count
    base_csv = os.path.join(exports_dir, "ml_dataset_ohlcv_v1.csv")
    if os.path.exists(base_csv):
        try:
            with open(base_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
            if len(header) != EXPECTED_BASE_CSV_COLUMNS:
                errors.append(
                    f"ml_dataset_ohlcv_v1.csv has {len(header)} columns, expected {EXPECTED_BASE_CSV_COLUMNS}"
                )
        except Exception as exc:
            errors.append(f"Failed to read ml_dataset_ohlcv_v1.csv header: {exc}")

    # Check regime CSV column count
    regime_csv = os.path.join(exports_dir, "ml_dataset_ohlcv_regime_v1.csv")
    if os.path.exists(regime_csv):
        try:
            with open(regime_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
            if len(header) != EXPECTED_REGIME_CSV_COLUMNS:
                errors.append(
                    f"ml_dataset_ohlcv_regime_v1.csv has {len(header)} columns, expected {EXPECTED_REGIME_CSV_COLUMNS}"
                )
        except Exception as exc:
            errors.append(f"Failed to read ml_dataset_ohlcv_regime_v1.csv header: {exc}")

    # Check regime metadata
    regime_meta = os.path.join(exports_dir, "ml_dataset_ohlcv_regime_v1.meta.json")
    if os.path.exists(regime_meta):
        try:
            with open(regime_meta, "r", encoding="utf-8") as f:
                meta = json.load(f)
            checks_meta = [
                ("technical_feature_count", 300),
                ("regime_feature_count", 8),
                ("total_feature_count", 308),
                ("duplicate_count", 0),
                ("null_count", 0),
            ]
            for key, expected in checks_meta:
                actual = meta.get(key)
                if actual != expected:
                    errors.append(f"regime meta {key}: expected {expected}, got {actual}")
        except Exception as exc:
            errors.append(f"Failed to parse ml_dataset_ohlcv_regime_v1.meta.json: {exc}")

    return CheckResult(
        name="export_artifacts",
        status="PASS" if not errors else "FAIL",
        detail="All export artifacts present and valid." if not errors else "Export artifact issues found.",
        errors=errors,
    )


def check_ranking_artifacts(exports_dir: str) -> CheckResult:
    """Check 7: Ranking meta has scored_sample_date, ranking CSV exists and matches count."""
    errors: list[str] = []

    meta_path = os.path.join(exports_dir, "latest_regime_rankings.meta.json")
    csv_path = os.path.join(exports_dir, "latest_regime_rankings.csv")

    if not os.path.exists(meta_path):
        return CheckResult(
            name="ranking_artifacts",
            status="FAIL",
            detail="Ranking meta file missing.",
            errors=["latest_regime_rankings.meta.json not found"],
        )

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as exc:
        return CheckResult(
            name="ranking_artifacts",
            status="FAIL",
            detail="Failed to parse ranking meta.",
            errors=[str(exc)],
        )

    scored_date = meta.get("scored_sample_date")
    if not scored_date:
        errors.append("ranking meta missing scored_sample_date")

    ranking_count = meta.get("ranking_count", 0)
    if ranking_count <= 0:
        errors.append(f"ranking_count is {ranking_count}, expected > 0")

    if not os.path.exists(csv_path):
        errors.append("latest_regime_rankings.csv not found")
    else:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            actual_count = len(rows)
            if actual_count != ranking_count:
                errors.append(
                    f"ranking CSV has {actual_count} data rows, meta says {ranking_count}"
                )
            # Check no duplicate symbols for the scored date
            if scored_date:
                symbols_seen: set[str] = set()
                for row in rows:
                    sym = row.get("symbol", "")
                    if sym in symbols_seen:
                        errors.append(f"Duplicate symbol in ranking CSV: {sym}")
                    symbols_seen.add(sym)
        except Exception as exc:
            errors.append(f"Failed to read latest_regime_rankings.csv: {exc}")

    return CheckResult(
        name="ranking_artifacts",
        status="PASS" if not errors else "FAIL",
        detail=f"Ranking meta scored_sample_date={scored_date}, ranking_count={ranking_count}.",
        errors=errors,
    )


def check_shadow_tracking(shadow_db: str) -> CheckResult:
    """Check 8: Shadow DB exists, no duplicate rows, all required fields present,
    bucket and tracking_status values valid."""
    errors: list[str] = []

    if not os.path.exists(shadow_db):
        return CheckResult(
            name="shadow_tracking",
            status="FAIL",
            detail="Shadow tracking DB missing.",
            errors=[f"Not found: {shadow_db}"],
        )

    try:
        conn = sqlite3.connect(shadow_db)
        conn.row_factory = sqlite3.Row

        # Duplicate check
        dup_count = conn.execute(
            "SELECT COUNT(*) c FROM ("
            "  SELECT model_version, scored_sample_date, symbol, COUNT(*) n"
            "  FROM shadow_tracking"
            "  GROUP BY model_version, scored_sample_date, symbol"
            "  HAVING n > 1"
            ")"
        ).fetchone()["c"]
        if dup_count:
            errors.append(f"{dup_count} duplicate group(s) by model_version + scored_sample_date + symbol")

        # Required fields
        required_fields = [
            "symbol", "scored_sample_date", "rank", "bucket",
            "win_probability", "tracking_status",
        ]
        for fld in required_fields:
            null_count = conn.execute(
                f"SELECT COUNT(*) c FROM shadow_tracking WHERE {fld} IS NULL"
            ).fetchone()["c"]
            if null_count:
                errors.append(f"{null_count} row(s) have null {fld}")

        # Bucket validity
        valid_bucket_list = ", ".join(f"'{b}'" for b in VALID_BUCKETS)
        bad_bucket = conn.execute(
            f"SELECT COUNT(*) c FROM shadow_tracking WHERE bucket NOT IN ({valid_bucket_list})"
        ).fetchone()["c"]
        if bad_bucket:
            errors.append(f"{bad_bucket} row(s) have invalid bucket value")

        # Tracking status validity
        valid_status_list = ", ".join(f"'{s}'" for s in VALID_TRACKING_STATUSES)
        bad_status = conn.execute(
            f"SELECT COUNT(*) c FROM shadow_tracking WHERE tracking_status NOT IN ({valid_status_list})"
        ).fetchone()["c"]
        if bad_status:
            errors.append(f"{bad_status} row(s) have invalid tracking_status value")

        conn.close()
    except Exception as exc:
        errors.append(f"DB error: {exc}")

    return CheckResult(
        name="shadow_tracking",
        status="PASS" if not errors else "FAIL",
        detail="Shadow tracking DB clean." if not errors else "Shadow tracking issues found.",
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all_checks(
    main_db: str = DEFAULT_MAIN_DB,
    shadow_db: str = DEFAULT_SHADOW_DB,
    exports_dir: str = DEFAULT_EXPORTS_DIR,
    feature_sample_limit: int = 5000,
) -> tuple[str, list[CheckResult]]:
    """Run all checks. Returns (overall_status, list_of_CheckResult)."""
    checks: list[CheckResult] = [
        check_testsym_contamination(main_db),
        check_ml_samples_duplicates(main_db),
        check_ml_sample_validity(main_db),
        check_feature_json_validity(main_db, sample_limit=feature_sample_limit),
        check_candle_linkage(main_db),
        check_export_artifacts(exports_dir),
        check_ranking_artifacts(exports_dir),
        check_shadow_tracking(shadow_db),
    ]

    any_fail = any(c.status == "FAIL" for c in checks)
    overall = "FAIL" if any_fail else "PASS"
    return overall, checks
