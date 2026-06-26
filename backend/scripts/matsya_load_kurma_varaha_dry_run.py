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
from app.matsya.kurma_varaha_model_loader import load_kurma_varaha_models_dry_run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Kurma 3 and Varaha 3 artifacts in a no-scoring dry-run."
    )
    parser.add_argument("--kurma-artifact-dir", default=str(DEFAULT_KURMA_3_ARTIFACT_DIR))
    parser.add_argument("--varaha-artifact-dir", default=str(DEFAULT_VARAHA_3_ARTIFACT_DIR))
    args = parser.parse_args()

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=Path(args.kurma_artifact_dir),
        varaha_artifact_dir=Path(args.varaha_artifact_dir),
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
