from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.matsya.latest_regime_v3_snapshot import (
    DEFAULT_META_PATH,
    DEFAULT_OUTPUT_PATH,
    LATEST_SNAPSHOT_DIR,
    MODEL_FEATURE_COUNT,
    MatsyaLatestRegimeV3Repository,
    MatsyaSnapshotReadinessError,
    SnapshotRepository,
    SnapshotResult,
    _validate_readiness,
    generate_latest_regime_v3_snapshot,
)


SNAPSHOT_FILENAME = DEFAULT_OUTPUT_PATH.name
SNAPSHOT_META_FILENAME = DEFAULT_META_PATH.name


class SnapshotGenerator(Protocol):
    def __call__(
        self,
        *,
        repository: SnapshotRepository | None = None,
        output_path: str | Path = DEFAULT_OUTPUT_PATH,
        meta_path: str | Path = DEFAULT_META_PATH,
    ) -> SnapshotResult:
        ...


@dataclass(frozen=True)
class LatestRegimeV3WorkerResult:
    status: str
    sample_date: str | None
    row_count: int | None
    feature_count: int | None
    output_path: str
    meta_path: str
    readiness_status: str
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_latest_regime_v3_snapshot_worker(
    *,
    repository: SnapshotRepository | None = None,
    output_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    meta_path: str | Path | None = None,
    generator: SnapshotGenerator = generate_latest_regime_v3_snapshot,
) -> LatestRegimeV3WorkerResult:
    resolved_repository = repository or MatsyaLatestRegimeV3Repository()
    resolved_output_path, resolved_meta_path = resolve_snapshot_paths(
        output_dir=output_dir,
        output_path=output_path,
        meta_path=meta_path,
    )
    readiness = resolved_repository.readiness()
    readiness_status = str(readiness.get("status") or "unknown")

    try:
        _validate_readiness(readiness)
    except MatsyaSnapshotReadinessError as exc:
        return LatestRegimeV3WorkerResult(
            status="not_ready",
            sample_date=None,
            row_count=None,
            feature_count=MODEL_FEATURE_COUNT,
            output_path=str(resolved_output_path),
            meta_path=str(resolved_meta_path),
            readiness_status=readiness_status,
            failure_reason=str(exc),
        )

    existing_paths = _existing_output_paths(resolved_output_path, resolved_meta_path)
    try:
        result = generator(
            repository=resolved_repository,
            output_path=resolved_output_path,
            meta_path=resolved_meta_path,
        )
    except MatsyaSnapshotReadinessError as exc:
        _remove_new_or_temporary_outputs(resolved_output_path, resolved_meta_path, existing_paths)
        return LatestRegimeV3WorkerResult(
            status="not_ready",
            sample_date=None,
            row_count=None,
            feature_count=MODEL_FEATURE_COUNT,
            output_path=str(resolved_output_path),
            meta_path=str(resolved_meta_path),
            readiness_status=readiness_status,
            failure_reason=str(exc),
        )
    except Exception as exc:
        _remove_new_or_temporary_outputs(resolved_output_path, resolved_meta_path, existing_paths)
        return LatestRegimeV3WorkerResult(
            status="failed",
            sample_date=None,
            row_count=None,
            feature_count=MODEL_FEATURE_COUNT,
            output_path=str(resolved_output_path),
            meta_path=str(resolved_meta_path),
            readiness_status=readiness_status,
            failure_reason=str(exc),
        )

    metadata = result.metadata
    return LatestRegimeV3WorkerResult(
        status="success",
        sample_date=str(metadata.get("sample_date")) if metadata.get("sample_date") else None,
        row_count=int(metadata.get("row_count") or 0),
        feature_count=int(metadata.get("feature_count") or len(result.feature_names)),
        output_path=result.output_path,
        meta_path=result.meta_path,
        readiness_status=str(metadata.get("matsya_readiness_status") or readiness_status),
        failure_reason=None,
    )


def resolve_snapshot_paths(
    *,
    output_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    meta_path: str | Path | None = None,
) -> tuple[Path, Path]:
    if output_path and meta_path:
        return Path(output_path), Path(meta_path)
    if output_path or meta_path:
        raise ValueError("output_path and meta_path must be provided together.")
    directory = Path(output_dir) if output_dir else LATEST_SNAPSHOT_DIR
    return directory / SNAPSHOT_FILENAME, directory / SNAPSHOT_META_FILENAME


def _existing_output_paths(output_path: Path, meta_path: Path) -> dict[Path, bool]:
    return {
        output_path: output_path.exists(),
        meta_path: meta_path.exists(),
    }


def _remove_new_or_temporary_outputs(output_path: Path, meta_path: Path, existing_paths: dict[Path, bool]) -> None:
    for path in (
        output_path.with_suffix(output_path.suffix + ".tmp"),
        meta_path.with_suffix(meta_path.suffix + ".tmp"),
        output_path,
        meta_path,
    ):
        if not path.exists():
            continue
        if path in existing_paths and existing_paths[path]:
            continue
        path.unlink()
