from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.matsya.latest_regime_v3_snapshot import (
    DEFAULT_META_PATH,
    DEFAULT_OUTPUT_PATH,
    generate_latest_regime_v3_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the latest Dataset V3 Regime inference snapshot from read-only Matsya OHLCV data."
    )
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--meta-path", default=str(DEFAULT_META_PATH))
    args = parser.parse_args()

    result = generate_latest_regime_v3_snapshot(
        output_path=Path(args.output_path),
        meta_path=Path(args.meta_path),
    )
    print(json.dumps(result.metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
