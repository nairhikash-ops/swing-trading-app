from __future__ import annotations

import csv
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

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


def write_marker(tmp_path: Path, value: str = SOURCE_MAIN_SHA) -> Path:
    marker = tmp_path / "RELEASE_COMMIT"
    marker.write_text(value + "\n", encoding="utf-8")
    marker.chmod(0o644)
    return marker


def build_bundle(
    specs: tuple[initializer.StrategySpec, initializer.StrategySpec],
    *,
    trading_dates: list[str] = TRADING_DATES,
    latest: str = "2026-07-17",
    calculated_at: str = "2026-07-20T12:00:00+00:00",
) -> initializer.AuditBundle:
    return initializer.build_audit_bundle(
        specs,
        latest_market_date=latest,
        load_available_dates=lambda _start, _end: trading_dates,
        source_main_sha=SOURCE_MAIN_SHA,
        calculated_at=calculated_at,
    )


def initialize(
    bundle: initializer.AuditBundle,
    marker_path: Path,
    *,
    refresh: Callable[[], initializer.AuditBundle] | None = None,
    after_replace: Callable[[str, int], None] | None = None,
) -> dict[str, str]:
    marker = initializer.read_release_marker(marker_path, expected_source_main_sha=SOURCE_MAIN_SHA)
    return initializer.initialize_metadata(
        bundle,
        expected_audit_sha256=bundle.audit_sha256,
        trusted_marker=marker,
        refresh_audit=refresh or (lambda: build_bundle(tuple(item.spec for item in bundle.audits))),
        after_replace=after_replace,
    ).actions


def transaction_path(specs: tuple[initializer.StrategySpec, initializer.StrategySpec]) -> Path:
    return specs[0].ledger_dir.parent / initializer.TRANSACTION_FILENAME


def test_missing_metadata_is_dry_run_only_by_default(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    result = initializer.public_result(build_bundle(specs), mode="dry-run")

    assert result["mode"] == "dry-run"
    assert [item["metadata_action"] for item in result["strategies"]] == ["create", "create"]
    assert not list(tmp_path.rglob("continuity_status.json"))
    with pytest.raises(SystemExit):
        initializer.parse_args(["--source-main-sha", SOURCE_MAIN_SHA, "--write"])


def test_v8_gap_and_healthy_uptrend_use_production_plan(tmp_path: Path) -> None:
    v8, uptrend = build_bundle(make_specs(tmp_path)).audits

    assert (v8.status, v8.forward_valid) == ("invalid_gap", False)
    assert list(v8.processed_dates) == V8_DATES
    assert list(v8.missing_dates) == TRADING_DATES[3:-1]
    assert (uptrend.status, uptrend.forward_valid) == ("healthy", True)
    assert list(uptrend.processed_dates) == UPTREND_DATES
    assert uptrend.missing_dates == uptrend.run_dates == ()


def test_market_dates_changing_at_write_boundary_are_refused(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    initial = build_bundle(specs)
    calls = 0

    def mutable_refresh() -> initializer.AuditBundle:
        nonlocal calls
        calls += 1
        if calls == 1:
            return build_bundle(specs, calculated_at="2026-07-20T12:01:00+00:00")
        return build_bundle(
            specs,
            trading_dates=TRADING_DATES + ["2026-07-20"],
            latest="2026-07-20",
            calculated_at="2026-07-20T12:02:00+00:00",
        )

    with pytest.raises(initializer.ContinuityInitializationError):
        initialize(initial, write_marker(tmp_path), refresh=mutable_refresh)
    assert not list(tmp_path.rglob("continuity_status.json"))
    assert not transaction_path(specs).exists()


def test_ledger_change_during_first_replacement_restores_prior_state(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)

    def mutate_after_first(_strategy: str, index: int) -> None:
        if index == 0:
            (specs[0].ledger_dir / "paper_broker_state.json").write_text(
                json.dumps({"cash": 99_999, "positions": []}), encoding="utf-8"
            )

    with pytest.raises(initializer.ContinuityInitializationError):
        initialize(bundle, write_marker(tmp_path), after_replace=mutate_after_first)
    assert not list(tmp_path.rglob("continuity_status.json"))
    assert not transaction_path(specs).exists()


def test_interruption_between_replacements_is_detected_and_recovered(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)

    def interrupt(_strategy: str, index: int) -> None:
        if index == 0:
            raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        initialize(bundle, write_marker(tmp_path), after_replace=interrupt)
    assert (specs[0].ledger_dir / "continuity_status.json").exists()
    assert not (specs[1].ledger_dir / "continuity_status.json").exists()
    assert transaction_path(specs).exists()

    assert initializer.recover_interrupted_transaction(bundle) is True
    assert not list(tmp_path.rglob("continuity_status.json"))
    assert not transaction_path(specs).exists()


def test_atomic_group_write_and_idempotency_preserve_timestamp(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    marker = write_marker(tmp_path)
    first = build_bundle(specs)
    actions = initialize(first, marker)
    paths = [spec.ledger_dir / "continuity_status.json" for spec in specs]
    original = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]

    second = build_bundle(specs, calculated_at="2026-07-20T13:00:00+00:00")
    repeated = initialize(second, marker)

    assert actions == {"v8_demo": "create", "uptrend_sideways": "create"}
    assert repeated == {"v8_demo": "unchanged", "uptrend_sideways": "unchanged"}
    assert second.audit_sha256 == first.audit_sha256
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == original
    assert json.loads(paths[0].read_text(encoding="utf-8"))["calculated_at"] == "2026-07-20T12:00:00+00:00"


@pytest.mark.parametrize("content", ["not-json", json.dumps({"status": "healthy"})])
def test_malformed_or_conflicting_metadata_is_refused(tmp_path: Path, content: str) -> None:
    specs = make_specs(tmp_path)
    (specs[0].ledger_dir / "continuity_status.json").write_text(content, encoding="utf-8")

    with pytest.raises(initializer.ContinuityInitializationError):
        initialize(build_bundle(specs), write_marker(tmp_path))
    assert not (specs[1].ledger_dir / "continuity_status.json").exists()


def test_hash_includes_economic_files_and_excludes_metadata_logs_and_temps(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    ledger = specs[0].ledger_dir
    initial = initializer.snapshot_ledger(ledger)
    (ledger / "runner.log").write_text("changed", encoding="utf-8")
    (ledger / "pending.tmp").write_text("changed", encoding="utf-8")
    (ledger / "continuity_status.json").write_text("changed", encoding="utf-8")
    assert initializer.snapshot_ledger(ledger) == initial

    (ledger / "paper_order_ledger.csv").write_text("order_id\n1\n", encoding="utf-8")
    assert initializer.snapshot_ledger(ledger) != initial


def test_symlink_ledger_directory_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    write_report(real, V8_DATES)
    real_lstat = initializer.os.lstat

    def symlinked_directory(path: Path) -> os.stat_result | SimpleNamespace:
        if Path(path) == real:
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        return real_lstat(path)

    monkeypatch.setattr(initializer.os, "lstat", symlinked_directory)

    with pytest.raises(initializer.ContinuityInitializationError, match="must not be a symlink"):
        initializer.snapshot_ledger(real)


def test_symlink_ledger_file_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger"
    write_report(ledger, V8_DATES)
    state = ledger / "paper_broker_state.json"
    real_lstat = initializer.os.lstat

    def symlinked_file(path: Path) -> os.stat_result | SimpleNamespace:
        if Path(path) == state:
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        return real_lstat(path)

    monkeypatch.setattr(initializer.os, "lstat", symlinked_file)

    with pytest.raises(initializer.ContinuityInitializationError, match="must not be symlinks"):
        initializer.snapshot_ledger(ledger)


def test_directory_fsync_failure_restores_and_retains_no_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    bundle = build_bundle(specs)
    original = initializer._fsync_directory
    failed = False

    def fail_once(identity: initializer.DirectoryIdentity) -> None:
        nonlocal failed
        if identity.path == str(specs[0].ledger_dir.resolve()) and not failed:
            failed = True
            raise OSError("simulated directory fsync failure")
        original(identity)

    monkeypatch.setattr(initializer, "_fsync_directory", fail_once)
    with pytest.raises(OSError, match="fsync"):
        initialize(bundle, write_marker(tmp_path))
    assert failed is True
    assert not list(tmp_path.rglob("continuity_status.json"))
    assert not transaction_path(specs).exists()


def test_trusted_release_marker_mismatch_is_refused(tmp_path: Path) -> None:
    marker = write_marker(tmp_path, "0" * 40)

    with pytest.raises(initializer.ContinuityInitializationError, match="does not match"):
        initializer.read_release_marker(marker, expected_source_main_sha=SOURCE_MAIN_SHA)


def test_mutable_api_end_to_end_dry_run_write_refuses_changed_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = make_specs(tmp_path)
    marker = write_marker(tmp_path)
    dates = list(TRADING_DATES)
    latest = "2026-07-17"
    monkeypatch.setattr(initializer, "fetch_latest_date", lambda _url: latest)
    monkeypatch.setattr(initializer, "fetch_trading_dates", lambda _url, _start, _end: list(dates))
    args = [
        "--v8-dir", str(specs[0].ledger_dir),
        "--uptrend-dir", str(specs[1].ledger_dir),
        "--source-main-sha", SOURCE_MAIN_SHA,
        "--release-marker", str(marker),
    ]

    assert initializer.main(args) == 0
    dry_run = json.loads(capsys.readouterr().out)
    dates.append("2026-07-20")
    latest = "2026-07-20"
    assert initializer.main(args + ["--write", "--expected-audit-sha256", dry_run["audit_sha256"]]) == 2
    assert not list(tmp_path.rglob("continuity_status.json"))
