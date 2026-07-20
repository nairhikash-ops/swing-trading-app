from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import initialize_paper_continuity as initializer  # noqa: E402


SOURCE_MAIN_SHA = "3de34ba273196a55d31778aff7720a303a865780"
TRADING_DATES = [
    "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
    "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14",
    "2026-07-15", "2026-07-16", "2026-07-17",
]
V8_DATES = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-17"]
UPTREND_DATES = TRADING_DATES[2:]


def write_report(directory: Path, dates: list[str]) -> None:
    directory.mkdir(parents=True)
    with (directory / "daily_report.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "equity"])
        writer.writeheader()
        for index, value in enumerate(dates):
            writer.writerow({"date": value, "equity": 100_000 + index})
    (directory / "paper_broker_state.json").write_text(
        json.dumps({"cash": 100_000, "positions": []}), encoding="utf-8"
    )


def make_specs(tmp_path: Path) -> tuple[initializer.StrategySpec, initializer.StrategySpec]:
    v8_dir = tmp_path / "v8"
    uptrend_dir = tmp_path / "uptrend"
    write_report(v8_dir, V8_DATES)
    write_report(uptrend_dir, UPTREND_DATES)
    return (
        initializer.StrategySpec("v8_demo", v8_dir, "invalid_gap"),
        initializer.StrategySpec("uptrend_sideways", uptrend_dir, "healthy"),
    )


def build_bundle(
    specs: tuple[initializer.StrategySpec, initializer.StrategySpec],
    *,
    calculated_at: str = "2026-07-20T12:00:00+00:00",
) -> initializer.AuditBundle:
    return initializer.build_audit_bundle(
        specs,
        latest_market_date="2026-07-17",
        load_available_dates=lambda _start, _end: TRADING_DATES,
        source_main_sha=SOURCE_MAIN_SHA,
        calculated_at=calculated_at,
    )


def test_missing_metadata_is_dry_run_only_by_default(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)
    result = initializer.public_result(bundle, mode="dry-run")

    assert result["mode"] == "dry-run"
    assert [item["metadata_action"] for item in result["strategies"]] == ["create", "create"]
    assert not (specs[0].ledger_dir / "continuity_status.json").exists()
    assert not (specs[1].ledger_dir / "continuity_status.json").exists()
    with pytest.raises(SystemExit):
        initializer.parse_args(["--source-main-sha", SOURCE_MAIN_SHA, "--write"])


def test_v8_gap_records_processed_missing_hash_time_and_source_sha(tmp_path: Path) -> None:
    audit = build_bundle(make_specs(tmp_path)).audits[0]
    payload = audit.metadata_payload()

    assert audit.status == "invalid_gap"
    assert audit.forward_valid is False
    assert list(audit.processed_dates) == V8_DATES
    assert list(audit.missing_dates) == TRADING_DATES[3:-1]
    assert payload["ledger_sha256"] == audit.ledger.sha256
    assert payload["calculated_at"] == "2026-07-20T12:00:00+00:00"
    assert payload["source_main_sha"] == SOURCE_MAIN_SHA


def test_healthy_uptrend_has_no_missing_or_pending_sessions(tmp_path: Path) -> None:
    audit = build_bundle(make_specs(tmp_path)).audits[1]

    assert audit.status == "healthy"
    assert audit.forward_valid is True
    assert list(audit.processed_dates) == UPTREND_DATES
    assert audit.missing_dates == ()
    assert audit.run_dates == ()


def test_changed_ledger_between_audit_and_write_is_refused(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)

    def mutate_ledger() -> None:
        with (specs[0].ledger_dir / "daily_report.csv").open("a", encoding="utf-8") as handle:
            handle.write("2026-07-18,100005\n")

    with pytest.raises(initializer.LedgerChangedError, match="between audit and write"):
        initializer.initialize_metadata(
            bundle,
            expected_audit_sha256=bundle.audit_sha256,
            before_write=mutate_ledger,
        )
    assert not (specs[0].ledger_dir / "continuity_status.json").exists()
    assert not (specs[1].ledger_dir / "continuity_status.json").exists()


def test_metadata_writes_use_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(initializer.os, "replace", recording_replace)
    actions = initializer.initialize_metadata(bundle, expected_audit_sha256=bundle.audit_sha256)

    assert actions == {"v8_demo": "create", "uptrend_sideways": "create"}
    assert len(replacements) == 2
    assert {destination.name for _, destination in replacements} == {"continuity_status.json"}
    assert all(source.name.startswith(".continuity_status.json.") for source, _ in replacements)
    assert not list(tmp_path.rglob("*.tmp"))


def test_repeated_write_is_idempotent_and_preserves_original_calculation_time(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    first = build_bundle(specs)
    initializer.initialize_metadata(first, expected_audit_sha256=first.audit_sha256)
    paths = [spec.ledger_dir / "continuity_status.json" for spec in specs]
    original = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]

    second = build_bundle(specs, calculated_at="2026-07-20T13:00:00+00:00")
    actions = initializer.initialize_metadata(second, expected_audit_sha256=second.audit_sha256)

    assert second.audit_sha256 == first.audit_sha256
    assert actions == {"v8_demo": "unchanged", "uptrend_sideways": "unchanged"}
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == original
    assert json.loads(paths[0].read_text(encoding="utf-8"))["calculated_at"] == "2026-07-20T12:00:00+00:00"
