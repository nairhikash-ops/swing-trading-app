from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
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
    v8_dir = tmp_path / "ledgers" / "v8"
    uptrend_dir = tmp_path / "ledgers" / "uptrend"
    write_report(v8_dir, V8_DATES)
    write_report(uptrend_dir, UPTREND_DATES)
    return (
        initializer.StrategySpec("v8_demo", v8_dir, "invalid_gap"),
        initializer.StrategySpec("uptrend_sideways", uptrend_dir, "healthy"),
    )


def configure_fixed_state(
    tmp_path: Path,
    specs: tuple[initializer.StrategySpec, initializer.StrategySpec],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    release_dir = tmp_path / "protected-release"
    release_dir.mkdir(mode=0o700)
    release_dir.chmod(0o700)
    marker = release_dir / "RELEASE_COMMIT"
    marker.write_text(SOURCE_MAIN_SHA + "\n", encoding="ascii")
    marker.chmod(0o644)
    coordinator = tmp_path / "protected-coordinator"
    coordinator.mkdir(mode=0o700)
    coordinator.chmod(0o700)
    monkeypatch.setattr(initializer, "RELEASE_MARKER_PATH", marker)
    monkeypatch.setattr(initializer, "COORDINATOR_STATE_DIR", coordinator)
    monkeypatch.setattr(initializer, "V8_LEDGER_DIR", specs[0].ledger_dir)
    monkeypatch.setattr(initializer, "UPTREND_LEDGER_DIR", specs[1].ledger_dir)
    return marker, coordinator


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
    *,
    refresh: Callable[[], initializer.AuditBundle] | None = None,
    after_create: Callable[[str, int], None] | None = None,
) -> initializer.InitializationResult:
    marker = initializer.read_release_marker()
    return initializer.initialize_metadata(
        bundle,
        expected_audit_sha256=bundle.audit_sha256,
        trusted_marker=marker,
        refresh_audit=refresh or (lambda: build_bundle(tuple(item.spec for item in bundle.audits))),
        after_create=after_create,
    )


def journal_path(coordinator: Path) -> Path:
    return coordinator / initializer.JOURNAL_FILENAME


def metadata_paths(
    specs: tuple[initializer.StrategySpec, initializer.StrategySpec],
) -> list[Path]:
    return [spec.ledger_dir / initializer.CONTINUITY_FILENAME for spec in specs]


def economic_identity(specs: tuple[initializer.StrategySpec, initializer.StrategySpec]) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for spec in specs:
        for path in spec.ledger_dir.iterdir():
            if path.name == initializer.CONTINUITY_FILENAME:
                continue
            file_stat = path.stat()
            result[str(path)] = (file_stat.st_dev, file_stat.st_ino, hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def test_dry_run_uses_fixed_paths_and_never_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    result = initializer.public_result(build_bundle(specs), mode="dry-run")

    assert result["mode"] == "dry-run"
    assert [item["metadata_action"] for item in result["strategies"]] == ["create", "create"]
    assert not journal_path(coordinator).exists()
    assert not any(path.exists() for path in metadata_paths(specs))
    with pytest.raises(SystemExit):
        initializer.parse_args(["--release-marker", str(tmp_path / "forged")])
    with pytest.raises(SystemExit):
        initializer.parse_args(["--coordinator-dir", str(tmp_path / "forged")])


def test_v8_gap_and_healthy_uptrend_use_production_plan(tmp_path: Path) -> None:
    v8, uptrend = build_bundle(make_specs(tmp_path)).audits

    assert (v8.status, v8.forward_valid) == ("invalid_gap", False)
    assert list(v8.missing_dates) == TRADING_DATES[3:-1]
    assert (uptrend.status, uptrend.forward_valid) == ("healthy", True)
    assert uptrend.missing_dates == uptrend.run_dates == ()


def test_success_retains_journal_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)

    first = initialize(bundle)
    original = [(path.read_bytes(), path.stat().st_mtime_ns) for path in metadata_paths(specs)]
    repeated = initialize(build_bundle(specs, calculated_at="2026-07-20T13:00:00+00:00"))

    assert first.actions == {"v8_demo": "create", "uptrend_sideways": "create"}
    assert repeated.actions == {"v8_demo": "unchanged", "uptrend_sideways": "unchanged"}
    assert journal_path(coordinator).exists()
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in metadata_paths(specs)] == original


def test_stale_market_dates_after_journal_creation_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
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
        initialize(bundle, refresh=mutable_refresh)
    assert journal_path(coordinator).exists()
    assert not any(path.exists() for path in metadata_paths(specs))


def test_concurrent_metadata_creation_is_preserved_and_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
    calls = 0
    external = b'{"status":"external"}\n'

    def concurrent_refresh() -> initializer.AuditBundle:
        nonlocal calls
        calls += 1
        current = build_bundle(specs)
        if calls == 2:
            metadata_paths(specs)[0].write_bytes(external)
        return current

    with pytest.raises(initializer.RecoveryRequiredError, match="concurrent metadata"):
        initialize(bundle, refresh=concurrent_refresh)
    assert metadata_paths(specs)[0].read_bytes() == external
    assert not metadata_paths(specs)[1].exists()
    assert journal_path(coordinator).exists()


def test_interruption_after_first_create_retains_fixed_recovery_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)

    def interrupt(_strategy: str, index: int) -> None:
        if index == 0:
            raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        initialize(bundle, after_create=interrupt)
    assert [path.exists() for path in metadata_paths(specs)] == [True, False]
    assert journal_path(coordinator).exists()

    with pytest.raises(initializer.RecoveryRequiredError, match="explicit operator recovery"):
        initialize(bundle)
    assert [path.exists() for path in metadata_paths(specs)] == [True, False]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory fsync")
def test_recovery_record_is_file_and_directory_fsynced_before_metadata_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
    original_fsync = initializer.os.fsync
    original_create_metadata = initializer._create_v8_metadata
    fsync_kinds: list[str] = []

    def record_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        fsync_kinds.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(descriptor)

    def prove_journal_first(identity: initializer.DirectoryIdentity, payload: bytes) -> None:
        assert journal_path(coordinator).exists()
        assert fsync_kinds[:2] == ["file", "directory"]
        original_create_metadata(identity, payload)

    monkeypatch.setattr(initializer.os, "fsync", record_fsync)
    monkeypatch.setattr(initializer, "_create_v8_metadata", prove_journal_first)
    initialize(bundle)


def test_final_coordinator_fsync_failure_keeps_documentation_and_retries_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
    original = initializer._fsync_directory
    coordinator_calls = 0

    def fail_final(identity: initializer.DirectoryIdentity) -> None:
        nonlocal coordinator_calls
        if identity.path == str(coordinator.resolve()):
            coordinator_calls += 1
            if coordinator_calls == 2:
                raise OSError("simulated final coordinator fsync failure")
        original(identity)

    monkeypatch.setattr(initializer, "_fsync_directory", fail_final)
    with pytest.raises(OSError, match="final coordinator"):
        initialize(bundle)
    assert journal_path(coordinator).exists()
    assert [path.exists() for path in metadata_paths(specs)] == [True, True]

    monkeypatch.setattr(initializer, "_fsync_directory", original)
    assert initialize(bundle).actions == {"v8_demo": "unchanged", "uptrend_sideways": "unchanged"}


@pytest.mark.parametrize("malicious", ["daily_report.csv", "../v8/daily_report.csv", "../../victim"])
def test_malicious_journal_filename_or_traversal_is_rejected_without_economic_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malicious: str
) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
    targets = {audit.spec.strategy_id: initializer._target_bytes(audit) for audit in bundle.audits}
    journal = json.loads(initializer._journal_bytes(bundle, targets))
    journal["targets"][0]["temporary"] = malicious
    journal_path(coordinator).write_text(json.dumps(journal), encoding="utf-8")
    before = economic_identity(specs)

    with pytest.raises(initializer.RecoveryRequiredError, match="schema"):
        initialize(bundle)
    assert economic_identity(specs) == before


def test_malformed_journal_never_changes_ledgers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    _marker, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    journal_path(coordinator).write_text("not-json", encoding="utf-8")
    before = economic_identity(specs)

    with pytest.raises(initializer.RecoveryRequiredError, match="malformed"):
        initialize(build_bundle(specs))
    assert economic_identity(specs) == before


def test_existing_metadata_without_fixed_journal_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    configure_fixed_state(tmp_path, specs, monkeypatch)
    external = b'{"status":"existing"}\n'
    metadata_paths(specs)[0].write_bytes(external)

    with pytest.raises(initializer.ContinuityInitializationError, match="both metadata files to be absent"):
        initialize(build_bundle(specs))
    assert metadata_paths(specs)[0].read_bytes() == external


def test_economic_files_are_never_deleted_renamed_or_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    configure_fixed_state(tmp_path, specs, monkeypatch)
    before = economic_identity(specs)
    initialize(build_bundle(specs))
    assert economic_identity(specs) == before

    source = (SCRIPTS_DIR / "initialize_paper_continuity.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"unlink", "remove", "removedirs", "rename", "renames", "replace"}
    invoked = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert invoked.isdisjoint(forbidden)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX O_NOFOLLOW")
def test_symlink_substitution_during_descriptor_relative_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = make_specs(tmp_path)
    target = specs[0].ledger_dir / "paper_broker_state.json"
    moved = specs[0].ledger_dir / "moved-economic.json"
    original = initializer._open_relative_read
    substituted = False

    def substitute(identity: initializer.DirectoryIdentity, descriptor: int | None, name: str) -> int:
        nonlocal substituted
        if identity.path == str(specs[0].ledger_dir.resolve()) and name == target.name and not substituted:
            substituted = True
            target.rename(moved)
            target.symlink_to(moved.name)
        return original(identity, descriptor, name)

    monkeypatch.setattr(initializer, "_open_relative_read", substitute)
    with pytest.raises(OSError):
        initializer.snapshot_ledger(specs[0].ledger_dir)
    assert substituted is True


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX ownership")
def test_forged_release_marker_owner_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    marker, _coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    if os.geteuid() == 0:
        os.chown(marker, 65534, 65534)
    with pytest.raises(initializer.ContinuityInitializationError, match="root-owned"):
        initializer.read_release_marker()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX permissions")
def test_forged_release_marker_parent_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    marker, _coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    marker.parent.chmod(0o777)
    with pytest.raises(initializer.ContinuityInitializationError, match="group/world writable"):
        initializer.read_release_marker()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX path ownership and permissions")
def test_writable_grandparent_is_rejected_for_fixed_paths(tmp_path: Path) -> None:
    grandparent = tmp_path / "grandparent"
    parent = grandparent / "parent"
    target = parent / "target"
    target.mkdir(parents=True, mode=0o700)
    grandparent.chmod(0o777)

    with pytest.raises(initializer.ContinuityInitializationError, match="group/world writable"):
        initializer._pin_directory(target, label="hostile fixed ledger")


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX path ownership")
def test_non_root_owned_ancestor_is_rejected(tmp_path: Path) -> None:
    grandparent = tmp_path / "grandparent"
    target = grandparent / "target"
    target.mkdir(parents=True, mode=0o700)
    if os.geteuid() != 0:
        pytest.skip("test requires root to create a non-root-owned ancestor")
    os.chown(grandparent, 65534, 65534)

    with pytest.raises(initializer.ContinuityInitializationError, match="not root-owned"):
        initializer._pin_directory(target, label="hostile fixed ledger")


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX symlink semantics")
def test_ancestor_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(initializer.ContinuityInitializationError, match="symlink component"):
        initializer._pin_directory(link / "target", label="hostile fixed ledger")


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory replacement")
def test_ancestor_replacement_after_pinning_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = root / "target"
    target.mkdir(parents=True, mode=0o700)
    identity = initializer._pin_directory(target, label="fixed ledger")
    root.rename(tmp_path / "old-root")
    (tmp_path / "root" / "target").mkdir(parents=True, mode=0o700)

    with pytest.raises(initializer.LedgerChangedError):
        initializer._verify_directory(identity)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX fixed-path creation")
def test_specialized_creators_have_no_filename_or_target_directory_parameter() -> None:
    import inspect

    for function in (
        initializer._create_intent_record,
        initializer._create_v8_metadata,
        initializer._create_uptrend_metadata,
    ):
        assert "filename" not in inspect.signature(function).parameters
    assert not hasattr(initializer, "_create_fixed_file")


def test_hash_includes_economic_files_and_excludes_fixed_metadata_logs_and_temps(tmp_path: Path) -> None:
    specs = make_specs(tmp_path)
    ledger = specs[0].ledger_dir
    initial = initializer.snapshot_ledger(ledger)
    (ledger / "runner.log").write_text("changed", encoding="utf-8")
    (ledger / "pending.tmp").write_text("changed", encoding="utf-8")
    (ledger / initializer.CONTINUITY_FILENAME).write_text("changed", encoding="utf-8")
    assert initializer.snapshot_ledger(ledger).sha256 == initial.sha256

    (ledger / "paper_order_ledger.csv").write_text("order_id\n1\n", encoding="utf-8")
    assert initializer.snapshot_ledger(ledger).sha256 != initial.sha256


def test_release_marker_change_is_rejected_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = make_specs(tmp_path)
    marker_path, coordinator = configure_fixed_state(tmp_path, specs, monkeypatch)
    bundle = build_bundle(specs)
    marker = initializer.read_release_marker()
    marker_path.write_text("0" * 40 + "\n", encoding="ascii")

    with pytest.raises(initializer.ContinuityInitializationError, match="changed"):
        initializer.initialize_metadata(
            bundle,
            expected_audit_sha256=bundle.audit_sha256,
            trusted_marker=marker,
            refresh_audit=lambda: build_bundle(specs),
        )
    assert not journal_path(coordinator).exists()


def test_mutable_api_end_to_end_refuses_stale_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = make_specs(tmp_path)
    configure_fixed_state(tmp_path, specs, monkeypatch)
    dates = list(TRADING_DATES)
    latest = "2026-07-17"
    monkeypatch.setattr(initializer, "fetch_latest_date", lambda _url: latest)
    monkeypatch.setattr(initializer, "fetch_trading_dates", lambda _url, _start, _end: list(dates))

    assert initializer.main([]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    dates.append("2026-07-20")
    latest = "2026-07-20"
    assert initializer.main(["--write", "--expected-audit-sha256", dry_run["audit_sha256"]]) == 2
    assert not any(path.exists() for path in metadata_paths(specs))


def test_runtime_imports_have_no_strategy_broker_or_order_path() -> None:
    source = (SCRIPTS_DIR / "initialize_paper_continuity.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(token in name for name in imports for token in ("strategy", "broker", "order", "dhan"))
