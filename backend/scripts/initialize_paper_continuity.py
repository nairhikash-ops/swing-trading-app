from __future__ import annotations

import argparse
import base64
import csv
import errno
import hashlib
import io
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from paper_trader_continuity import build_plan, fetch_latest_date, fetch_trading_dates


MATSYA_BASE_URL = "http://matsya-api:8020"
V8_LEDGER_DIR = Path("/app/data/v8_demo_trader")
UPTREND_LEDGER_DIR = Path("/app/data/uptrend_sideways_paper_trader")
RELEASE_MARKER_PATH = Path("/app/RELEASE_COMMIT")
COORDINATOR_STATE_DIR = Path("/var/lib/matsya-continuity-init")

CONTINUITY_FILENAME = "continuity_status.json"
DAILY_REPORT_FILENAME = "daily_report.csv"
JOURNAL_FILENAME = "continuity-initialization.json"
JOURNAL_VERSION = 2
SOURCE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
STRATEGY_IDS = ("v8_demo", "uptrend_sideways")


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
class PathComponentIdentity:
    path: str
    device: int
    inode: int


@dataclass(frozen=True)
class DirectoryIdentity:
    path: str
    device: int
    inode: int
    components: tuple[PathComponentIdentity, ...] = ()


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
    components: tuple[PathComponentIdentity, ...] = ()


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


@dataclass(frozen=True)
class InitializationResult:
    actions: dict[str, str]
    committed_audit: AuditBundle


@dataclass(frozen=True)
class JournalTarget:
    strategy_id: str
    target_sha256: str
    target_base64: str

    @property
    def content(self) -> bytes:
        try:
            value = base64.b64decode(self.target_base64, validate=True)
        except ValueError as exc:
            raise RecoveryRequiredError("fixed recovery record contains invalid base64") from exc
        if hashlib.sha256(value).hexdigest() != self.target_sha256:
            raise RecoveryRequiredError("fixed recovery record target hash mismatch")
        return value


@dataclass(frozen=True)
class JournalRecord:
    audit_sha256: str
    source_main_sha: str
    created_at: str
    targets: tuple[JournalTarget, ...]


def _pin_absolute_components(path: Path, *, label: str, final_kind: str) -> tuple[Path, os.stat_result, tuple[PathComponentIdentity, ...]]:
    requested = Path(path)
    if not requested.is_absolute():
        raise ContinuityInitializationError(f"{label} must be an absolute fixed path")
    if os.name == "nt":
        current = Path(requested.anchor)
        components: list[PathComponentIdentity] = []
        parts = requested.parts[1:] if requested.anchor else requested.parts
        for index, part in enumerate(parts):
            current = current / part
            current_stat = os.lstat(current)
            if stat.S_ISLNK(current_stat.st_mode):
                raise ContinuityInitializationError(f"{label} contains a symlink component: {current}")
            is_final = index == len(parts) - 1
            if not is_final and not stat.S_ISDIR(current_stat.st_mode):
                raise ContinuityInitializationError(f"{label} component is not a directory: {current}")
            components.append(PathComponentIdentity(str(current), current_stat.st_dev, current_stat.st_ino))
        if not components:
            raise ContinuityInitializationError(f"{label} cannot be filesystem root")
        final_stat = os.lstat(current)
        if final_kind == "directory" and not stat.S_ISDIR(final_stat.st_mode):
            raise ContinuityInitializationError(f"{label} is not a directory: {current}")
        if final_kind == "file" and not stat.S_ISREG(final_stat.st_mode):
            raise ContinuityInitializationError(f"{label} is not a regular file: {current}")
        return current, final_stat, tuple(components)
    parts = requested.parts[1:]
    current = Path(requested.anchor)
    descriptors: list[int] = []
    components: list[PathComponentIdentity] = []
    try:
        root_fd = os.open(requested.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(root_fd)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != 0 or root_stat.st_mode & 0o022:
            raise ContinuityInitializationError(f"{label} filesystem root is not trusted")
        components.append(PathComponentIdentity(str(current), root_stat.st_dev, root_stat.st_ino))
        final_stat = root_stat
        for index, part in enumerate(parts):
            current = current / part
            is_final = index == len(parts) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if not is_final or final_kind == "directory" else 0)
            child_fd = os.open(part, flags, dir_fd=descriptors[-1])
            descriptors.append(child_fd)
            child_stat = os.fstat(child_fd)
            if child_stat.st_uid != 0:
                raise ContinuityInitializationError(f"{label} component is not root-owned: {current}")
            if child_stat.st_mode & 0o022:
                raise ContinuityInitializationError(f"{label} component is group/world writable: {current}")
            if is_final:
                if final_kind == "directory" and not stat.S_ISDIR(child_stat.st_mode):
                    raise ContinuityInitializationError(f"{label} is not a directory: {current}")
                if final_kind == "file" and not stat.S_ISREG(child_stat.st_mode):
                    raise ContinuityInitializationError(f"{label} is not a regular file: {current}")
            elif not stat.S_ISDIR(child_stat.st_mode):
                raise ContinuityInitializationError(f"{label} component is not a directory: {current}")
            components.append(PathComponentIdentity(str(current), child_stat.st_dev, child_stat.st_ino))
            final_stat = child_stat
        return current, final_stat, tuple(components)
    except OSError as exc:
        if exc.errno == errno.ELOOP or ("current" in locals() and os.path.islink(current)):
            raise ContinuityInitializationError(f"{label} contains a symlink component") from exc
        raise ContinuityInitializationError(f"{label} component cannot be opened safely") from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _pin_directory(path: Path, *, label: str) -> DirectoryIdentity:
    resolved, resolved_stat, components = _pin_absolute_components(path, label=label, final_kind="directory")
    return DirectoryIdentity(str(resolved), resolved_stat.st_dev, resolved_stat.st_ino, components)


def _pin_protected_directory(path: Path, *, label: str) -> DirectoryIdentity:
    return _pin_directory(path, label=label)


def _verify_directory(identity: DirectoryIdentity) -> None:
    if _pin_directory(Path(identity.path), label="pinned directory") != identity:
        raise LedgerChangedError(f"directory identity changed: {identity.path}")


def _open_directory(identity: DirectoryIdentity) -> int | None:
    _verify_directory(identity)
    if os.name == "nt":
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
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


def _directory_names(identity: DirectoryIdentity, descriptor: int | None) -> tuple[str, ...]:
    if descriptor is not None:
        return tuple(sorted(os.listdir(descriptor)))
    return tuple(sorted(item.name for item in Path(identity.path).iterdir()))


def _stat_relative(identity: DirectoryIdentity, descriptor: int | None, name: str) -> os.stat_result:
    if descriptor is not None:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    return os.stat(Path(identity.path) / name, follow_symlinks=False)


def _open_relative_read(identity: DirectoryIdentity, descriptor: int | None, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if descriptor is not None:
        return os.open(name, flags, dir_fd=descriptor)
    return os.open(Path(identity.path) / name, flags)


def _read_opened_file(
    identity: DirectoryIdentity,
    descriptor: int | None,
    name: str,
    expected: os.stat_result,
) -> bytes:
    file_descriptor = _open_relative_read(identity, descriptor, name)
    try:
        opened = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContinuityInitializationError(f"ledger entry must be a regular file: {identity.path}/{name}")
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise LedgerChangedError(f"ledger file identity changed while opening: {identity.path}/{name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        closed = os.fstat(file_descriptor)
        if (closed.st_dev, closed.st_ino, closed.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise LedgerChangedError(f"ledger file changed while hashing: {identity.path}/{name}")
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _include_economic_file(name: str) -> bool:
    return (
        name != CONTINUITY_FILENAME
        and not name.endswith(".tmp")
        and not name.endswith(".log")
    )


def snapshot_ledger(directory: Path) -> LedgerSnapshot:
    identity = _pin_directory(directory, label="ledger directory")
    descriptor = _open_directory(identity)
    try:
        names_before = _directory_names(identity, descriptor)
        if DAILY_REPORT_FILENAME not in names_before:
            raise ContinuityInitializationError(f"daily report does not exist: {identity.path}/{DAILY_REPORT_FILENAME}")
        evidence: list[FileIdentity] = []
        aggregate = hashlib.sha256()
        for name in names_before:
            file_stat = _stat_relative(identity, descriptor, name)
            if stat.S_ISLNK(file_stat.st_mode):
                raise ContinuityInitializationError(f"ledger entries must not be symlinks: {identity.path}/{name}")
            if not stat.S_ISREG(file_stat.st_mode) or not _include_economic_file(name):
                continue
            content = _read_opened_file(identity, descriptor, name, file_stat)
            item = FileIdentity(
                name,
                hashlib.sha256(content).hexdigest(),
                len(content),
                file_stat.st_dev,
                file_stat.st_ino,
            )
            evidence.append(item)
            aggregate.update(json.dumps(asdict(item), sort_keys=True, separators=(",", ":")).encode("utf-8"))
            aggregate.update(b"\n")
        if _directory_names(identity, descriptor) != names_before:
            raise LedgerChangedError(f"ledger directory entries changed while hashing: {identity.path}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _verify_directory(identity)
    return LedgerSnapshot(aggregate.hexdigest(), identity, tuple(evidence))


def _read_daily_report_dates(identity: DirectoryIdentity) -> list[str]:
    descriptor = _open_directory(identity)
    try:
        report_stat = _stat_relative(identity, descriptor, DAILY_REPORT_FILENAME)
        if stat.S_ISLNK(report_stat.st_mode) or not stat.S_ISREG(report_stat.st_mode):
            raise ContinuityInitializationError("daily report must be a regular non-symlink file")
        content = _read_opened_file(identity, descriptor, DAILY_REPORT_FILENAME, report_stat)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    text = content.decode("utf-8")
    return [str(row["date"]) for row in csv.DictReader(io.StringIO(text)) if row.get("date")]


def read_release_marker() -> ReleaseMarker:
    marker, marker_stat, components = _pin_absolute_components(
        RELEASE_MARKER_PATH,
        label="fixed release marker",
        final_kind="file",
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(marker, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (marker_stat.st_dev, marker_stat.st_ino):
            raise ContinuityInitializationError("fixed release marker identity changed while opening")
        content = b""
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            content += chunk
        closed = os.fstat(descriptor)
        if (closed.st_dev, closed.st_ino, closed.st_size) != (opened.st_dev, opened.st_ino, opened.st_size):
            raise ContinuityInitializationError("fixed release marker changed while reading")
    finally:
        os.close(descriptor)
    value = content.decode("ascii").strip()
    if not SOURCE_SHA_PATTERN.fullmatch(value):
        raise ContinuityInitializationError("fixed release marker does not contain an exact commit SHA")
    return ReleaseMarker(str(marker), value, marker_stat.st_dev, marker_stat.st_ino, components)


def verify_release_marker(marker: ReleaseMarker) -> None:
    current = read_release_marker()
    if current != marker:
        raise ContinuityInitializationError("fixed release marker identity or content changed")


def audit_strategy(
    spec: StrategySpec,
    *,
    latest_market_date: str,
    load_available_dates: Callable[[str, str], Sequence[str]],
    source_main_sha: str,
    calculated_at: str,
) -> StrategyAudit:
    before = snapshot_ledger(spec.ledger_dir)
    processed = _read_daily_report_dates(before.directory)
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
        raise ContinuityInitializationError("source main SHA must come from the fixed release marker")
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
    if tuple(audit.spec.strategy_id for audit in audits) != STRATEGY_IDS:
        raise ContinuityInitializationError("initializer supports only the fixed V8 and Uptrend strategy pair")
    stable = {"source_main_sha": source_main_sha, "strategies": [item.stable_evidence() for item in audits]}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return AuditBundle(audits, digest.hexdigest(), timestamp, source_main_sha)


def _read_fixed_file(identity: DirectoryIdentity, filename: str) -> bytes | None:
    descriptor = _open_directory(identity)
    try:
        try:
            file_stat = _stat_relative(identity, descriptor, filename)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise ContinuityInitializationError(f"fixed state file must be regular and non-symlink: {filename}")
        return _read_opened_file(identity, descriptor, filename, file_stat)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_metadata(identity: DirectoryIdentity) -> bytes | None:
    return _read_fixed_file(identity, CONTINUITY_FILENAME)


def _read_journal(identity: DirectoryIdentity) -> bytes | None:
    return _read_fixed_file(identity, JOURNAL_FILENAME)


def _create_intent_record(payload: bytes) -> None:
    identity = _fixed_coordinator()
    descriptor = _open_directory(identity)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        if descriptor is not None:
            file_descriptor = os.open(JOURNAL_FILENAME, flags, 0o600, dir_fd=descriptor)
        else:
            file_descriptor = os.open(Path(identity.path) / JOURNAL_FILENAME, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(file_descriptor, view)
                if written <= 0:
                    raise OSError("fixed state file write made no progress")
                view = view[written:]
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _create_v8_metadata(payload: bytes) -> None:
    identity = _pin_directory(V8_LEDGER_DIR, label="fixed V8 ledger directory")
    descriptor = _open_directory(identity)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        if descriptor is not None:
            file_descriptor = os.open(CONTINUITY_FILENAME, flags, 0o600, dir_fd=descriptor)
        else:
            file_descriptor = os.open(Path(identity.path) / CONTINUITY_FILENAME, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(file_descriptor, view)
                if written <= 0:
                    raise OSError("V8 metadata write made no progress")
                view = view[written:]
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _create_uptrend_metadata(payload: bytes) -> None:
    identity = _pin_directory(UPTREND_LEDGER_DIR, label="fixed Uptrend ledger directory")
    descriptor = _open_directory(identity)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        if descriptor is not None:
            file_descriptor = os.open(CONTINUITY_FILENAME, flags, 0o600, dir_fd=descriptor)
        else:
            file_descriptor = os.open(Path(identity.path) / CONTINUITY_FILENAME, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(file_descriptor, view)
                if written <= 0:
                    raise OSError("Uptrend metadata write made no progress")
                view = view[written:]
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        _fsync_directory(identity)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _target_bytes(audit: StrategyAudit) -> bytes:
    return (json.dumps(audit.metadata_payload(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _journal_bytes(bundle: AuditBundle, targets: dict[str, bytes]) -> bytes:
    record = {
        "version": JOURNAL_VERSION,
        "audit_sha256": bundle.audit_sha256,
        "source_main_sha": bundle.source_main_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "targets": [
            {
                "strategy_id": strategy_id,
                "target_sha256": hashlib.sha256(targets[strategy_id]).hexdigest(),
                "target_base64": base64.b64encode(targets[strategy_id]).decode("ascii"),
            }
            for strategy_id in STRATEGY_IDS
        ],
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_journal(raw: bytes) -> JournalRecord:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryRequiredError("fixed recovery record is malformed") from exc
    expected_keys = {"version", "audit_sha256", "source_main_sha", "created_at", "targets"}
    if not isinstance(value, dict) or set(value) != expected_keys or value["version"] != JOURNAL_VERSION:
        raise RecoveryRequiredError("fixed recovery record has an invalid schema")
    raw_targets = value["targets"]
    if not isinstance(raw_targets, list) or len(raw_targets) != len(STRATEGY_IDS):
        raise RecoveryRequiredError("fixed recovery record has invalid targets")
    targets: list[JournalTarget] = []
    target_keys = {"strategy_id", "target_sha256", "target_base64"}
    for raw_target in raw_targets:
        if not isinstance(raw_target, dict) or set(raw_target) != target_keys:
            raise RecoveryRequiredError("fixed recovery record target schema is invalid")
        target = JournalTarget(
            str(raw_target["strategy_id"]),
            str(raw_target["target_sha256"]),
            str(raw_target["target_base64"]),
        )
        target.content
        targets.append(target)
    if tuple(target.strategy_id for target in targets) != STRATEGY_IDS:
        raise RecoveryRequiredError("fixed recovery record strategy order is invalid")
    return JournalRecord(
        str(value["audit_sha256"]),
        str(value["source_main_sha"]),
        str(value["created_at"]),
        tuple(targets),
    )


def _assert_bundle_current(bundle: AuditBundle) -> None:
    for audit in bundle.audits:
        if snapshot_ledger(audit.spec.ledger_dir) != audit.ledger:
            raise LedgerChangedError(f"{audit.spec.strategy_id} ledger changed at write boundary")


def _fixed_coordinator() -> DirectoryIdentity:
    return _pin_protected_directory(COORDINATOR_STATE_DIR, label="fixed coordinator state directory")


def _existing_target_state(bundle: AuditBundle, record: JournalRecord) -> dict[str, str]:
    expected = {target.strategy_id: target.content for target in record.targets}
    states: dict[str, str] = {}
    for audit in bundle.audits:
        current = _read_metadata(audit.ledger.directory)
        if current is None:
            states[audit.spec.strategy_id] = "absent"
        elif current == expected[audit.spec.strategy_id]:
            states[audit.spec.strategy_id] = "exact"
        else:
            states[audit.spec.strategy_id] = "unexpected"
    return states


def initialize_metadata(
    bundle: AuditBundle,
    *,
    expected_audit_sha256: str,
    trusted_marker: ReleaseMarker,
    refresh_audit: Callable[[], AuditBundle],
    after_create: Callable[[str, int], None] | None = None,
) -> InitializationResult:
    if expected_audit_sha256 != bundle.audit_sha256:
        raise ContinuityInitializationError("expected audit SHA does not match the approved dry run")
    verify_release_marker(trusted_marker)
    coordinator = _fixed_coordinator()
    existing_journal = _read_journal(coordinator)
    if existing_journal is not None:
        record = _parse_journal(existing_journal)
        if record.source_main_sha != trusted_marker.source_main_sha or record.audit_sha256 != expected_audit_sha256:
            raise RecoveryRequiredError("fixed recovery record belongs to different approved evidence")
        refreshed = refresh_audit()
        if refreshed.audit_sha256 != expected_audit_sha256:
            raise RecoveryRequiredError("current market/ledger evidence differs from the fixed recovery record")
        states = _existing_target_state(refreshed, record)
        if set(states.values()) == {"exact"}:
            for audit in refreshed.audits:
                _fsync_directory(audit.ledger.directory)
            _fsync_directory(coordinator)
            return InitializationResult({strategy_id: "unchanged" for strategy_id in STRATEGY_IDS}, refreshed)
        raise RecoveryRequiredError(
            "interrupted or inconsistent create-only initialization; fixed recovery record retained; "
            f"explicit operator recovery required: {states}"
        )

    refreshed = refresh_audit()
    if refreshed.audit_sha256 != expected_audit_sha256:
        raise ContinuityInitializationError("write-boundary market/ledger audit differs from approved dry run")
    verify_release_marker(trusted_marker)
    _assert_bundle_current(refreshed)
    if any(_read_metadata(audit.ledger.directory) is not None for audit in refreshed.audits):
        raise ContinuityInitializationError("create-only initialization requires both metadata files to be absent")

    targets = {audit.spec.strategy_id: _target_bytes(audit) for audit in refreshed.audits}
    _create_intent_record(_journal_bytes(refreshed, targets))

    final_boundary = refresh_audit()
    if final_boundary.audit_sha256 != expected_audit_sha256:
        raise RecoveryRequiredError("market/ledger evidence changed after durable recovery record creation")
    verify_release_marker(trusted_marker)
    _assert_bundle_current(final_boundary)
    for index, audit in enumerate(final_boundary.audits):
        if _read_metadata(audit.ledger.directory) is not None:
            raise RecoveryRequiredError(
                f"concurrent metadata creation detected for {audit.spec.strategy_id}; recovery record retained"
            )
        if audit.spec.strategy_id == "v8_demo":
            if _pin_directory(V8_LEDGER_DIR, label="fixed V8 ledger directory") != audit.ledger.directory:
                raise LedgerChangedError("fixed V8 ledger directory identity changed")
            _create_v8_metadata(targets[audit.spec.strategy_id])
        elif audit.spec.strategy_id == "uptrend_sideways":
            if _pin_directory(UPTREND_LEDGER_DIR, label="fixed Uptrend ledger directory") != audit.ledger.directory:
                raise LedgerChangedError("fixed Uptrend ledger directory identity changed")
            _create_uptrend_metadata(targets[audit.spec.strategy_id])
        else:
            raise ContinuityInitializationError("unexpected fixed strategy identifier")
        if after_create is not None:
            after_create(audit.spec.strategy_id, index)

    verify_release_marker(trusted_marker)
    post_write = refresh_audit()
    if post_write.audit_sha256 != expected_audit_sha256:
        raise RecoveryRequiredError("market/ledger evidence changed after metadata creation; recovery record retained")
    _assert_bundle_current(post_write)
    record = _parse_journal(_read_journal(coordinator) or b"")
    if set(_existing_target_state(post_write, record).values()) != {"exact"}:
        raise RecoveryRequiredError("post-create metadata validation failed; recovery record retained")
    for audit in post_write.audits:
        _fsync_directory(audit.ledger.directory)
    _fsync_directory(coordinator)
    return InitializationResult({strategy_id: "create" for strategy_id in STRATEGY_IDS}, refreshed)


def public_result(bundle: AuditBundle, *, mode: str, actions: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "mode": mode,
        "audit_sha256": bundle.audit_sha256,
        "calculated_at": bundle.calculated_at,
        "source_main_sha": bundle.source_main_sha,
        "fixed_release_marker": str(RELEASE_MARKER_PATH),
        "fixed_coordinator_state": str(COORDINATOR_STATE_DIR),
        "strategies": [
            {
                **audit.stable_evidence(),
                "calculated_at": audit.calculated_at,
                "metadata_action": (actions or {}).get(
                    audit.spec.strategy_id,
                    "create" if _read_metadata(audit.ledger.directory) is None else "present",
                ),
            }
            for audit in bundle.audits
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit and create fixed paper-ledger continuity metadata without strategy execution."
    )
    parser.add_argument("--write", action="store_true", help="Create both missing fixed metadata files.")
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
        StrategySpec("v8_demo", V8_LEDGER_DIR, "invalid_gap"),
        StrategySpec("uptrend_sideways", UPTREND_LEDGER_DIR, "healthy"),
    )
    try:
        marker = read_release_marker()

        def current_audit() -> AuditBundle:
            latest = fetch_latest_date(MATSYA_BASE_URL)
            return build_audit_bundle(
                specs,
                latest_market_date=latest,
                load_available_dates=lambda start, end: fetch_trading_dates(MATSYA_BASE_URL, start, end),
                source_main_sha=marker.source_main_sha,
            )

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
