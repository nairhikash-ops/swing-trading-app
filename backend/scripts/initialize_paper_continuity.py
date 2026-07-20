from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from paper_trader_continuity import build_plan, fetch_latest_date, fetch_trading_dates, read_report_dates


DEFAULT_BASE_URL = "http://matsya-api:8020"
DEFAULT_V8_DIR = Path("/app/data/v8_demo_trader")
DEFAULT_UPTREND_DIR = Path("/app/data/uptrend_sideways_paper_trader")
SOURCE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CONTINUITY_FILENAME = "continuity_status.json"


class ContinuityInitializationError(RuntimeError):
    pass


class LedgerChangedError(ContinuityInitializationError):
    pass


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    ledger_dir: Path
    expected_status: str


@dataclass(frozen=True)
class LedgerFileEvidence:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class LedgerSnapshot:
    sha256: str
    files: tuple[LedgerFileEvidence, ...]


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


def _include_ledger_file(path: Path) -> bool:
    name = path.name
    return (
        path.is_file()
        and name != CONTINUITY_FILENAME
        and not name.startswith(f".{CONTINUITY_FILENAME}.")
        and not name.endswith(".tmp")
        and not name.endswith(".log")
    )


def snapshot_ledger(directory: Path) -> LedgerSnapshot:
    directory = directory.resolve()
    report = directory / "daily_report.csv"
    if not directory.is_dir():
        raise ContinuityInitializationError(f"ledger directory does not exist: {directory}")
    if not report.is_file():
        raise ContinuityInitializationError(f"daily report does not exist: {report}")

    evidence: list[LedgerFileEvidence] = []
    aggregate = hashlib.sha256()
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not _include_ledger_file(path):
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        item = LedgerFileEvidence(path=path.name, sha256=digest.hexdigest(), size=size)
        evidence.append(item)
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(item.sha256.encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(str(size).encode("ascii"))
        aggregate.update(b"\n")
    return LedgerSnapshot(sha256=aggregate.hexdigest(), files=tuple(evidence))


def audit_strategy(
    spec: StrategySpec,
    *,
    latest_market_date: str,
    load_available_dates: Callable[[str, str], Sequence[str]],
    source_main_sha: str,
    calculated_at: str,
) -> StrategyAudit:
    before = snapshot_ledger(spec.ledger_dir)
    processed = read_report_dates(spec.ledger_dir / "daily_report.csv")
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
        raise ContinuityInitializationError(
            f"{spec.strategy_id} is not complete through {latest_market_date}"
        )
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
    stable = {
        "source_main_sha": source_main_sha,
        "strategies": [audit.stable_evidence() for audit in audits],
    }
    audit_sha = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AuditBundle(audits=audits, audit_sha256=audit_sha, calculated_at=timestamp, source_main_sha=source_main_sha)


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _stable_metadata(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key not in {"checked_at", "calculated_at"}}


def _metadata_action(audit: StrategyAudit) -> str:
    path = audit.spec.ledger_dir / CONTINUITY_FILENAME
    if not path.exists():
        return "create"
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityInitializationError(f"invalid existing metadata: {path}") from exc
    if _stable_metadata(existing) == _stable_metadata(audit.metadata_payload()):
        return "unchanged"
    raise ContinuityInitializationError(f"conflicting continuity metadata already exists: {path}")


def initialize_metadata(
    bundle: AuditBundle,
    *,
    expected_audit_sha256: str,
    before_write: Callable[[], None] | None = None,
) -> dict[str, str]:
    if expected_audit_sha256 != bundle.audit_sha256:
        raise ContinuityInitializationError("expected audit SHA does not match the current dry-run evidence")
    actions = {audit.spec.strategy_id: _metadata_action(audit) for audit in bundle.audits}
    if before_write is not None:
        before_write()
    for audit in bundle.audits:
        if snapshot_ledger(audit.spec.ledger_dir) != audit.ledger:
            raise LedgerChangedError(f"{audit.spec.strategy_id} ledger changed between audit and write")
    for audit in bundle.audits:
        if actions[audit.spec.strategy_id] == "create":
            atomic_write_json(audit.spec.ledger_dir / CONTINUITY_FILENAME, audit.metadata_payload())
    for audit in bundle.audits:
        if snapshot_ledger(audit.spec.ledger_dir) != audit.ledger:
            raise LedgerChangedError(f"{audit.spec.strategy_id} ledger changed while metadata was written")
    return actions


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
    parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically create missing metadata after a matching dry run.",
    )
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
    try:
        latest = fetch_latest_date(args.base_url)
        bundle = build_audit_bundle(
            specs,
            latest_market_date=latest,
            load_available_dates=lambda start, end: fetch_trading_dates(args.base_url, start, end),
            source_main_sha=args.source_main_sha,
        )
        if args.write:
            actions = initialize_metadata(bundle, expected_audit_sha256=args.expected_audit_sha256)
            result = public_result(bundle, mode="write", actions=actions)
        else:
            result = public_result(bundle, mode="dry-run")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ContinuityInitializationError as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
