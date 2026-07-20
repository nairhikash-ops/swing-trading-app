from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from paper_trader_continuity import build_plan, fetch_latest_date, fetch_trading_dates, read_report_dates


DEFAULT_BASE_URL = "http://matsya-api:8020"
DEFAULT_V8_DIR = Path("/app/data/v8_demo_trader")
DEFAULT_UPTREND_DIR = Path("/app/data/uptrend_sideways_paper_trader")
DEFAULT_RELEASE_MARKER = Path("/app/RELEASE_COMMIT")
SOURCE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CONTINUITY_FILENAME = "continuity_status.json"
TRANSACTION_FILENAME = ".paper-continuity-metadata.transaction.json"
TRANSACTION_VERSION = 1


class ContinuityInitializationError(RuntimeError):
    pass


class LedgerChangedError(ContinuityInitializationError):
    pass


class RecoveryRequiredError(ContinuityInitializationError):
    pass


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    ledger_dir: Path
    expected_status: str


@dataclass(frozen=True)
class DirectoryIdentity:
    path: str
    device: int
    inode: int


@dataclass(frozen=True)
class FileIdentity:
    path: str
    sha256: str
    size: int
    device: int
    inode: int


@dataclass(frozen=True)
class LedgerSnapshot:
    sha256: str
    directory: DirectoryIdentity
    files: tuple[FileIdentity, ...]


@dataclass(frozen=True)
class ReleaseMarker:
    path: str
    source_main_sha: str
    device: int
    inode: int


@dataclass(frozen=True)
class InitializationResult:
    actions: dict[str, str]
    committed_audit: AuditBundle


@dataclass(frozen=True)
class StrategyAudit:
    spec: StrategySpec
    status: str
    forward_valid: bool
    coverage_start: str | None
    coverage_end: str | None
    processed_dates: tuple[str, ...]
    missing_dates: tuple[str, ...]
    run_dates: tuple[str, ...]
    duplicate_dates: tuple[str, ...]
    latest_market_date: str
    available_dates: tuple[str, ...]
    ledger: LedgerSnapshot
    calculated_at: str
    source_main_sha: str

    def stable_evidence(self) -> dict[str, object]:
        return {
            "strategy_id": self.spec.strategy_id,
            "status": self.status,
            "forward_valid": self.forward_valid,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "processed_dates": list(self.processed_dates),
            "missing_dates": list(self.missing_dates),
            "run_dates": list(self.run_dates),
            "duplicate_dates": list(self.duplicate_dates),
            "latest_market_date": self.latest_market_date,
            "available_dates": list(self.available_dates),
            "ledger_sha256": self.ledger.sha256,
            "ledger_directory": asdict(self.ledger.directory),
            "ledger_files": [asdict(item) for item in self.ledger.files],
            "source_main_sha": self.source_main_sha,
        }

    def metadata_payload(self) -> dict[str, object]:
        message = (
            "Ledger continuity is invalid; automatic processing refused until a new epoch is started."
            if not self.forward_valid
            else "All stored trading sessions in this epoch are present."
        )
        return {
            "strategy_id": self.spec.strategy_id,
            "status": self.status,
            "forward_valid": self.forward_valid,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "processed_dates": list(self.processed_dates),
            "missing_dates": list(self.missing_dates),
            "run_dates": list(self.run_dates),
            "duplicate_dates": list(self.duplicate_dates),
            "replayed_dates": [],
            "message": message,
            "checked_at": self.calculated_at,
            "ledger_sha256": self.ledger.sha256,
            "ledger_directory": asdict(self.ledger.directory),
            "ledger_files": [asdict(item) for item in self.ledger.files],
            "calculated_at": self.calculated_at,
            "source_main_sha": self.source_main_sha,
            "latest_market_date": self.latest_market_date,
        }


@dataclass(frozen=True)
class AuditBundle:
    audits: tuple[StrategyAudit, ...]
    audit_sha256: str
    calculated_at: str
    source_main_sha: str


def _pin_directory(path: Path, *, label: str) -> DirectoryIdentity:
    requested = Path(path)
    try:
        requested_stat = os.lstat(requested)
    except OSError as exc:
        raise ContinuityInitializationError(f"{label} does not exist: {requested}") from exc
    if stat.S_ISLNK(requested_stat.st_mode):
        raise ContinuityInitializationError(f"{label} must not be a symlink: {requested}")
    resolved = requested.resolve(strict=True)
    resolved_stat = os.lstat(resolved)
    if not stat.S_ISDIR(resolved_stat.st_mode):
        raise ContinuityInitializationError(f"{label} is not a directory: {resolved}")
    return DirectoryIdentity(str(resolved), resolved_stat.st_dev, resolved_stat.st_ino)


def _verify_directory(identity: DirectoryIdentity) -> None:
    current = _pin_directory(Path(identity.path), label="pinned directory")
    if current != identity:
        raise LedgerChangedError(f"directory identity changed: {identity.path}")


def _open_directory(identity: DirectoryIdentity) -> int | None:
    _verify_directory(identity)
    if os.name == "nt":
        return None
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(identity.path, flags)
    current = os.fstat(descriptor)
    if (current.st_dev, current.st_ino) != (identity.device, identity.inode):
        os.close(descriptor)
        raise LedgerChangedError(f"directory identity changed while opening: {identity.path}")
    return descriptor


def _fsync_directory(identity: DirectoryIdentity) -> None:
    descriptor = _open_directory(identity)
    if descriptor is None:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _include_ledger_file(path: Path) -> bool:
    name = path.name
    return (
        name != CONTINUITY_FILENAME
        and not name.startswith(f".{CONTINUITY_FILENAME}.")
        and not name.endswith(".tmp")
        and not name.endswith(".log")
    )


def snapshot_ledger(directory: Path) -> LedgerSnapshot:
    identity = _pin_directory(directory, label="ledger directory")
    resolved = Path(identity.path)
    report = resolved / "daily_report.csv"
    if not report.is_file():
        raise ContinuityInitializationError(f"daily report does not exist: {report}")

    evidence: list[FileIdentity] = []
    aggregate = hashlib.sha256()
    for path in sorted(resolved.iterdir(), key=lambda item: item.name):
        file_stat = os.lstat(path)
        if stat.S_ISLNK(file_stat.st_mode):
            raise ContinuityInitializationError(f"ledger entries must not be symlinks: {path}")
        if not stat.S_ISREG(file_stat.st_mode) or not _include_ledger_file(path):
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (file_stat.st_dev, file_stat.st_ino):
                raise LedgerChangedError(f"ledger file identity changed while opening: {path}")
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            closed = os.fstat(handle.fileno())
            if (closed.st_dev, closed.st_ino, closed.st_size) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ):
                raise LedgerChangedError(f"ledger file changed while hashing: {path}")
        item = FileIdentity(path.name, digest.hexdigest(), size, file_stat.st_dev, file_stat.st_ino)
        evidence.append(item)
        aggregate.update(json.dumps(asdict(item), sort_keys=True, separators=(",", ":")).encode("utf-8"))
        aggregate.update(b"\n")
    _verify_directory(identity)
    return LedgerSnapshot(aggregate.hexdigest(), identity, tuple(evidence))


def read_release_marker(path: Path, *, expected_source_main_sha: str) -> ReleaseMarker:
    marker = Path(path)
    marker_stat = os.lstat(marker)
    if stat.S_ISLNK(marker_stat.st_mode) or not stat.S_ISREG(marker_stat.st_mode):
        raise ContinuityInitializationError(f"release marker must be a regular non-symlink file: {marker}")
    # Windows does not implement Unix group/world permission bits faithfully.
    # The deployed runtime is Linux, where a mutable release marker is refused.
    if os.name != "nt" and marker_stat.st_mode & 0o022:
        raise ContinuityInitializationError(f"release marker must not be group/world writable: {marker}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(marker, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (marker_stat.st_dev, marker_stat.st_ino):
            raise ContinuityInitializationError("trusted release marker identity changed while opening")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = handle.read().strip()
            closed = os.fstat(handle.fileno())
            if (closed.st_dev, closed.st_ino, closed.st_size) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ):
                raise ContinuityInitializationError("trusted release marker changed while reading")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if value != expected_source_main_sha:
        raise ContinuityInitializationError(
            f"source main SHA does not match trusted release marker: expected {expected_source_main_sha}, found {value}"
        )
    return ReleaseMarker(str(marker.resolve(strict=True)), value, marker_stat.st_dev, marker_stat.st_ino)


def verify_release_marker(marker: ReleaseMarker) -> None:
    current = read_release_marker(Path(marker.path), expected_source_main_sha=marker.source_main_sha)
    if current != marker:
        raise ContinuityInitializationError("trusted release marker identity changed")


def audit_strategy(
    spec: StrategySpec,
    *,
    latest_market_date: str,
    load_available_dates: Callable[[str, str], Sequence[str]],
    source_main_sha: str,
    calculated_at: str,
) -> StrategyAudit:
    before = snapshot_ledger(spec.ledger_dir)
    processed = read_report_dates(Path(before.directory.path) / "daily_report.csv")
    start = min(processed) if processed else latest_market_date
    available = tuple(str(value) for value in load_available_dates(start, latest_market_date))
    plan = build_plan(processed, list(available))
    after = snapshot_ledger(spec.ledger_dir)
    if before != after:
        raise LedgerChangedError(f"{spec.strategy_id} ledger changed during continuity audit")
    if plan.status != spec.expected_status:
        raise ContinuityInitializationError(
            f"{spec.strategy_id} expected {spec.expected_status}, calculated {plan.status}"
        )
    if spec.expected_status == "healthy" and (plan.missing_dates or plan.run_dates):
        raise ContinuityInitializationError(f"{spec.strategy_id} is not complete through {latest_market_date}")
    return StrategyAudit(
        spec=spec,
        status=plan.status,
        forward_valid=plan.forward_valid,
        coverage_start=plan.coverage_start,
        coverage_end=plan.coverage_end,
        processed_dates=plan.processed_dates,
        missing_dates=plan.missing_dates,
        run_dates=plan.run_dates,
        duplicate_dates=plan.duplicate_dates,
        latest_market_date=latest_market_date,
        available_dates=available,
        ledger=before,
        calculated_at=calculated_at,
        source_main_sha=source_main_sha,
    )


def build_audit_bundle(
    specs: Sequence[StrategySpec],
    *,
    latest_market_date: str,
    load_available_dates: Callable[[str, str], Sequence[str]],
    source_main_sha: str,
    calculated_at: str | None = None,
) -> AuditBundle:
    if not SOURCE_SHA_PATTERN.fullmatch(source_main_sha):
        raise ContinuityInitializationError("source main SHA must be exactly 40 lowercase hexadecimal characters")
    timestamp = calculated_at or datetime.now(timezone.utc).isoformat()
    audits = tuple(
        audit_strategy(
            spec,
            latest_market_date=latest_market_date,
            load_available_dates=load_available_dates,
            source_main_sha=source_main_sha,
            calculated_at=timestamp,
        )
        for spec in specs
    )
    stable = {"source_main_sha": source_main_sha, "strategies": [item.stable_evidence() for item in audits]}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return AuditBundle(audits, digest.hexdigest(), timestamp, source_main_sha)


def _read_relative(identity: DirectoryIdentity, name: str) -> bytes | None:
    directory_descriptor = _open_directory(identity)
    path = Path(identity.path) / name
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            if directory_descriptor is not None:
                descriptor = os.open(name, flags, dir_fd=directory_descriptor)
            else:
                descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ContinuityInitializationError(f"metadata entry must be a regular non-symlink file: {path}")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                content = handle.read()
                closed = os.fstat(handle.fileno())
                if (closed.st_dev, closed.st_ino, closed.st_size) != (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                ):
                    raise LedgerChangedError(f"metadata entry changed while reading: {path}")
                return content
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _stage_bytes(identity: DirectoryIdentity, name: str, payload: bytes) -> None:
    descriptor = _open_directory(identity)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    if descriptor is not None:
        file_descriptor = os.open(name, flags, 0o600, dir_fd=descriptor)
    else:
        file_descriptor = os.open(Path(identity.path) / name, flags, 0o600)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _replace_relative(identity: DirectoryIdentity, source: str, destination: str) -> None:
    descriptor = _open_directory(identity)
    try:
        if descriptor is not None:
            os.replace(source, destination, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        else:
            os.replace(Path(identity.path) / source, Path(identity.path) / destination)
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _remove_relative(identity: DirectoryIdentity, name: str) -> None:
    descriptor = _open_directory(identity)
    try:
        try:
            if descriptor is not None:
                os.unlink(name, dir_fd=descriptor)
            else:
                (Path(identity.path) / name).unlink()
        except FileNotFoundError:
            return
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_write_bytes(identity: DirectoryIdentity, destination: str, payload: bytes) -> None:
    temporary = f".{destination}.{secrets.token_hex(12)}.tmp"
    _stage_bytes(identity, temporary, payload)
    try:
        _replace_relative(identity, temporary, destination)
    finally:
        _remove_relative(identity, temporary)


def _coordinator_identity(bundle: AuditBundle) -> DirectoryIdentity:
    parents = {str(Path(audit.ledger.directory.path).parent) for audit in bundle.audits}
    if len(parents) != 1:
        raise ContinuityInitializationError("V8 and Uptrend ledger directories must share one parent")
    return _pin_directory(Path(next(iter(parents))), label="transaction coordinator directory")


def _stable_metadata(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key not in {"checked_at", "calculated_at"}}


def _metadata_action(audit: StrategyAudit) -> str:
    content = _read_relative(audit.ledger.directory, CONTINUITY_FILENAME)
    if content is None:
        return "create"
    try:
        existing = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ContinuityInitializationError(
            f"invalid existing metadata: {audit.ledger.directory.path}/{CONTINUITY_FILENAME}"
        ) from exc
    if _stable_metadata(existing) == _stable_metadata(audit.metadata_payload()):
        return "unchanged"
    raise ContinuityInitializationError(
        f"conflicting continuity metadata exists: {audit.ledger.directory.path}/{CONTINUITY_FILENAME}"
    )


def _transaction_payload(bundle: AuditBundle, actions: dict[str, str]) -> tuple[dict[str, object], dict[str, bytes]]:
    staged: dict[str, bytes] = {}
    entries: list[dict[str, object]] = []
    for audit in bundle.audits:
        prior = _read_relative(audit.ledger.directory, CONTINUITY_FILENAME)
        target = (json.dumps(audit.metadata_payload(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        temporary = f".{CONTINUITY_FILENAME}.{secrets.token_hex(12)}.tmp"
        staged[audit.spec.strategy_id] = target
        entries.append(
            {
                "strategy_id": audit.spec.strategy_id,
                "directory": asdict(audit.ledger.directory),
                "action": actions[audit.spec.strategy_id],
                "prior_exists": prior is not None,
                "prior_base64": base64.b64encode(prior or b"").decode("ascii"),
                "prior_sha256": hashlib.sha256(prior or b"").hexdigest(),
                "target_sha256": hashlib.sha256(target).hexdigest(),
                "temporary": temporary,
            }
        )
    return (
        {
            "version": TRANSACTION_VERSION,
            "audit_sha256": bundle.audit_sha256,
            "source_main_sha": bundle.source_main_sha,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entries": entries,
        },
        staged,
    )


def _decode_identity(value: dict[str, object]) -> DirectoryIdentity:
    return DirectoryIdentity(str(value["path"]), int(value["device"]), int(value["inode"]))


def recover_interrupted_transaction(bundle: AuditBundle) -> bool:
    coordinator = _coordinator_identity(bundle)
    raw = _read_relative(coordinator, TRANSACTION_FILENAME)
    if raw is None:
        return False
    try:
        journal = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryRequiredError(f"invalid recovery journal: {coordinator.path}/{TRANSACTION_FILENAME}") from exc
    if journal.get("version") != TRANSACTION_VERSION:
        raise RecoveryRequiredError("unsupported continuity recovery journal version")
    if journal.get("source_main_sha") != bundle.source_main_sha:
        raise RecoveryRequiredError("continuity recovery journal belongs to a different source release")
    entries = journal.get("entries")
    if not isinstance(entries, list) or len(entries) != len(bundle.audits):
        raise RecoveryRequiredError("continuity recovery journal has invalid entries")

    expected_directories = {
        audit.spec.strategy_id: audit.ledger.directory for audit in bundle.audits
    }
    journal_ids = [str(entry.get("strategy_id")) for entry in entries if isinstance(entry, dict)]
    if len(journal_ids) != len(entries) or set(journal_ids) != set(expected_directories):
        raise RecoveryRequiredError("continuity recovery journal has unexpected strategy entries")

    decoded: list[tuple[dict[str, object], DirectoryIdentity, bytes | None, bytes | None]] = []
    for entry in entries:
        identity = _decode_identity(entry["directory"])
        strategy_id = str(entry["strategy_id"])
        if identity != expected_directories[strategy_id]:
            raise RecoveryRequiredError(f"continuity recovery journal directory mismatch for {strategy_id}")
        _verify_directory(identity)
        prior = base64.b64decode(str(entry["prior_base64"]), validate=True) if entry["prior_exists"] else None
        current = _read_relative(identity, CONTINUITY_FILENAME)
        current_hash = hashlib.sha256(current or b"").hexdigest()
        allowed = {str(entry["prior_sha256"]), str(entry["target_sha256"])}
        if current_hash not in allowed:
            raise RecoveryRequiredError(
                f"metadata changed outside interrupted transaction: {identity.path}/{CONTINUITY_FILENAME}"
            )
        decoded.append((entry, identity, prior, current))

    for entry, identity, prior, _current in decoded:
        if prior is None:
            _remove_relative(identity, CONTINUITY_FILENAME)
        else:
            _atomic_write_bytes(identity, CONTINUITY_FILENAME, prior)
        _remove_relative(identity, str(entry["temporary"]))
    _remove_relative(coordinator, TRANSACTION_FILENAME)
    return True


def _assert_bundle_current(bundle: AuditBundle) -> None:
    for audit in bundle.audits:
        if snapshot_ledger(audit.spec.ledger_dir) != audit.ledger:
            raise LedgerChangedError(f"{audit.spec.strategy_id} ledger changed at write boundary")


def initialize_metadata(
    bundle: AuditBundle,
    *,
    expected_audit_sha256: str,
    trusted_marker: ReleaseMarker,
    refresh_audit: Callable[[], AuditBundle],
    after_replace: Callable[[str, int], None] | None = None,
) -> InitializationResult:
    if expected_audit_sha256 != bundle.audit_sha256:
        raise ContinuityInitializationError("expected audit SHA does not match current evidence")
    verify_release_marker(trusted_marker)
    recovered = recover_interrupted_transaction(bundle)

    refreshed = refresh_audit()
    if refreshed.audit_sha256 != expected_audit_sha256:
        raise ContinuityInitializationError("write-boundary market/ledger audit differs from approved dry run")
    verify_release_marker(trusted_marker)
    _assert_bundle_current(refreshed)
    actions = {audit.spec.strategy_id: _metadata_action(audit) for audit in refreshed.audits}
    unique_actions = set(actions.values())
    if unique_actions == {"unchanged"}:
        return InitializationResult(actions, refreshed)
    if unique_actions != {"create"}:
        reason = " after interrupted-transaction recovery" if recovered else ""
        raise RecoveryRequiredError(f"partial continuity metadata state{reason}; refusing unjournaled completion")

    coordinator = _coordinator_identity(refreshed)
    journal, staged = _transaction_payload(refreshed, actions)
    journal_bytes = (json.dumps(journal, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if _read_relative(coordinator, TRANSACTION_FILENAME) is not None:
        raise RecoveryRequiredError("continuity transaction journal already exists")
    _atomic_write_bytes(coordinator, TRANSACTION_FILENAME, journal_bytes)

    try:
        for entry in journal["entries"]:
            identity = _decode_identity(entry["directory"])
            strategy_id = str(entry["strategy_id"])
            _stage_bytes(identity, str(entry["temporary"]), staged[strategy_id])
        verify_release_marker(trusted_marker)
        final_boundary = refresh_audit()
        if final_boundary.audit_sha256 != expected_audit_sha256:
            raise ContinuityInitializationError("market/ledger evidence changed before metadata commit")
        _assert_bundle_current(final_boundary)
        for index, entry in enumerate(journal["entries"]):
            identity = _decode_identity(entry["directory"])
            strategy_id = str(entry["strategy_id"])
            _replace_relative(identity, str(entry["temporary"]), CONTINUITY_FILENAME)
            if after_replace is not None:
                after_replace(strategy_id, index)
        verify_release_marker(trusted_marker)
        post_write = refresh_audit()
        if post_write.audit_sha256 != expected_audit_sha256:
            raise ContinuityInitializationError("market/ledger evidence changed during metadata commit")
        _assert_bundle_current(post_write)
        _remove_relative(coordinator, TRANSACTION_FILENAME)
        return InitializationResult(actions, refreshed)
    except Exception:
        try:
            recover_interrupted_transaction(refreshed)
        except Exception as recovery_exc:
            raise RecoveryRequiredError(
                f"metadata initialization failed and automatic recovery is incomplete; journal retained at "
                f"{coordinator.path}/{TRANSACTION_FILENAME}: {recovery_exc}"
            ) from recovery_exc
        raise


def public_result(bundle: AuditBundle, *, mode: str, actions: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "mode": mode,
        "audit_sha256": bundle.audit_sha256,
        "calculated_at": bundle.calculated_at,
        "source_main_sha": bundle.source_main_sha,
        "strategies": [
            {
                **audit.stable_evidence(),
                "calculated_at": audit.calculated_at,
                "metadata_action": (actions or {}).get(audit.spec.strategy_id, _metadata_action(audit)),
            }
            for audit in bundle.audits
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit and initialize paper-ledger continuity metadata without running strategy logic."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--v8-dir", type=Path, default=DEFAULT_V8_DIR)
    parser.add_argument("--uptrend-dir", type=Path, default=DEFAULT_UPTREND_DIR)
    parser.add_argument("--source-main-sha", required=True)
    parser.add_argument("--release-marker", type=Path, default=DEFAULT_RELEASE_MARKER)
    parser.add_argument("--write", action="store_true", help="Commit missing metadata after a matching dry run.")
    parser.add_argument("--expected-audit-sha256", help="Required with --write; copy from the preceding dry run.")
    args = parser.parse_args(argv)
    if args.write and not args.expected_audit_sha256:
        parser.error("--write requires --expected-audit-sha256 from a preceding dry run")
    if not args.write and args.expected_audit_sha256:
        parser.error("--expected-audit-sha256 is valid only with --write")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    specs = (
        StrategySpec("v8_demo", args.v8_dir, "invalid_gap"),
        StrategySpec("uptrend_sideways", args.uptrend_dir, "healthy"),
    )

    def current_audit() -> AuditBundle:
        latest = fetch_latest_date(args.base_url)
        return build_audit_bundle(
            specs,
            latest_market_date=latest,
            load_available_dates=lambda start, end: fetch_trading_dates(args.base_url, start, end),
            source_main_sha=args.source_main_sha,
        )

    try:
        marker = read_release_marker(args.release_marker, expected_source_main_sha=args.source_main_sha)
        bundle = current_audit()
        if args.write:
            initialization = initialize_metadata(
                bundle,
                expected_audit_sha256=args.expected_audit_sha256,
                trusted_marker=marker,
                refresh_audit=current_audit,
            )
            result = public_result(
                initialization.committed_audit,
                mode="write",
                actions=initialization.actions,
            )
        else:
            result = public_result(bundle, mode="dry-run")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ContinuityInitializationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
