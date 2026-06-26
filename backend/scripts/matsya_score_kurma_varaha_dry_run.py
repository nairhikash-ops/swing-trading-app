from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.matsya.kurma_varaha_artifacts import (
    DEFAULT_KURMA_3_ARTIFACT_DIR,
    DEFAULT_VARAHA_3_ARTIFACT_DIR,
)
from app.matsya.kurma_varaha_scoring_dry_run import score_kurma_varaha_dry_run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a no-trade Kurma 3 / Varaha 3 probability scoring dry-run."
    )
    parser.add_argument("--snapshot-csv", required=True)
    parser.add_argument("--kurma-artifact-dir", default=str(DEFAULT_KURMA_3_ARTIFACT_DIR))
    parser.add_argument("--varaha-artifact-dir", default=str(DEFAULT_VARAHA_3_ARTIFACT_DIR))
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    report = score_kurma_varaha_dry_run(
        snapshot_csv=Path(args.snapshot_csv),
        kurma_artifact_dir=Path(args.kurma_artifact_dir),
        varaha_artifact_dir=Path(args.varaha_artifact_dir),
        output_path=Path(args.output_path),
        limit=args.limit,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
