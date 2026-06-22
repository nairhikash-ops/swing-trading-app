from __future__ import annotations

import argparse
import asyncio
import json
import os

from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.ingest import sha256_payload, token_hash
from app.matsya.settings import MatsyaSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a Dhan profile snapshot without printing tokens.")
    parser.add_argument("--access-token-env", default="DHAN_ACCESS_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="Call profile endpoint but do not write to PostgreSQL.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    access_token = os.getenv(args.access_token_env)
    if not access_token:
        raise RuntimeError(f"{args.access_token_env} is not set")
    profile = await DhanClient().profile(access_token)
    payload = profile.raw
    if args.dry_run:
        print(f"dry_run=true profile_hash={sha256_payload(payload)}")
        return

    settings = MatsyaSettings.from_env()
    with connect(settings) as conn:
        run_schema(conn)
        conn.execute(
            """
            INSERT INTO matsya.dhan_profile_snapshots (
                dhan_client_id, access_token_hash, profile_json, profile_hash
            )
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (provider_code, access_token_hash, profile_hash) DO NOTHING
            """,
            (
                profile.dhan_client_id,
                token_hash(access_token),
                json.dumps(payload, sort_keys=True),
                sha256_payload(payload),
            ),
        )
        conn.commit()
    print(f"profile snapshot captured profile_hash={sha256_payload(payload)}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
