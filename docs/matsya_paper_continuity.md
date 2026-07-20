# Matsya paper-ledger continuity

Each paper strategy writes `continuity_status.json` beside its ledger files. The
scheduled wrapper obtains the actual stored Matsya trading dates, compares them
with `daily_report.csv`, and applies these rules:

- A normal new session is processed once.
- Multiple trailing sessions are replayed chronologically, but the epoch is
  permanently labeled `reconstructed` and is not valid forward evidence.
- A missing session behind a newer report is labeled `invalid_gap`; automatic
  out-of-order replay is refused.
- A new empty output directory starts at the latest stored session. It does not
  manufacture historical forward evidence.

The dashboard must show `Run healthy` only when `status=healthy` and
`forward_valid=true`. Missing continuity metadata is unhealthy by default.

## Recovery procedure

1. Stop the affected scheduled runner.
2. Copy the complete affected output directory into a timestamped, immutable
   evidence directory. Do not edit or replace the original CSV/JSON files.
3. Run any historical reconstruction in a different fresh output directory and
   label it reconstructed. Never merge reconstructed rows into the old forward
   ledger.
4. Start a new forward epoch in a new empty output directory after the fixed
   runner is deployed.
5. Verify the API reports continuity coverage, missing dates, and the expected
   final market date before treating the new epoch as healthy.

Example immutable V8 reconstruction inside the existing read-only report mount:

```bash
python scripts/reconstruct_paper_ledger.py \
  --strategy v8_demo \
  --from-date 2026-07-01 \
  --to-date 2026-07-17 \
  --output-dir /app/data/v8_demo_trader/reconstructions/20260720T-audit
```

The read-only session source is:

```text
GET /api/matsya/market-data/trading-dates?from=YYYY-MM-DD&to=YYYY-MM-DD
```

It returns dates that actually exist in Matsya OHLCV storage, so weekends and
exchange holidays are not incorrectly treated as gaps.

## Initialize missing metadata without running a strategy

`initialize_paper_continuity.py` imports only the continuity planner. It never
imports or invokes a strategy, broker, or order runner. Stop every process that
can write either paper-ledger directory, preserve and hash both directories,
and run the CLI without `--write` first:

```bash
python scripts/initialize_paper_continuity.py
```

The CLI accepts no path, source-SHA, release-marker, coordinator, or API
override. It derives the source SHA only from the fixed build-owned
`/app/RELEASE_COMMIT`. The fixed coordinator directory
`/var/lib/matsya-continuity-init` must already exist, be owned by root, grant
no group/other permissions, and have a protected root-owned parent.

The dry run must report `v8_demo=invalid_gap` and
`uptrend_sideways=healthy`. Review the processed dates, missing dates, source
SHA, calculation time, per-file hashes and aggregate ledger hash. To create
only the two missing `continuity_status.json` files, repeat the command with
the exact audit SHA printed by that dry run:

```bash
python scripts/initialize_paper_continuity.py \
  --write \
  --expected-audit-sha256 AUDIT_SHA_FROM_DRY_RUN
```

This is a create-only operation. Both fixed metadata targets must be absent.
Before creating either one, the CLI re-fetches market dates, rebuilds both
audits, requires an exact match with the approved dry-run SHA, and durably
creates the fixed immutable intent record
`/var/lib/matsya-continuity-init/continuity-initialization.json`. The intent
record contains hashes and content for the two fixed targets but contains no
filesystem paths or filenames.

Each metadata target is re-read immediately before creation and is opened with
`O_CREAT|O_EXCL|O_NOFOLLOW`. Concurrent creation is refused and never
overwritten. The files and ledger directories are fsynced, the audits and
fixed release marker are revalidated, and the coordinator directory is
fsynced last. The intent record is deliberately retained after success. An
identical repeat verifies the record and both fixed targets, fsyncs again, and
returns unchanged without rewriting timestamps.

There is no automatic rollback. The initializer contains no unlink, remove,
rename, replace, or restore operation. If it is interrupted after creating one
target, the durable fixed intent record and partial fixed state remain. Every
later invocation fails closed and requires an explicit, separately reviewed
operator recovery procedure. Do not delete, edit, or attempt to resume from
the record during this runbook.

Economic ledger files are enumerated and opened relative to pinned directory
descriptors with `O_NOFOLLOW`; device and inode identity are verified using
`fstat` on the opened descriptors. Economic CSV/JSON files are never opened
for writing and cannot be deleted or renamed by this CLI. Any symlink,
economic-ledger mutation, market-date change, marker change, metadata race, or
fsync failure is an error. Because the fixed intent record is durable before
metadata creation and is never cleaned up, a final coordinator-fsync failure
cannot leave undocumented committed metadata.
