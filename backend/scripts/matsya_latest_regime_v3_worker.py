from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.matsya.latest_regime_v3_worker import run_latest_regime_v3_snapshot_worker


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually run the dry Matsya latest Dataset V3 Regime snapshot worker hook."
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--meta-path", default=None)
    args = parser.parse_args()

    result = run_latest_regime_v3_snapshot_worker(
        output_dir=Path(args.output_dir) if args.output_dir else None,
        output_path=Path(args.output_path) if args.output_path else None,
        meta_path=Path(args.meta_path) if args.meta_path else None,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
