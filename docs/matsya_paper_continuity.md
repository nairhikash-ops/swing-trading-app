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
and run the CLI without `--write` first. The supplied source SHA must exactly
match a trusted, read-only release marker from the deployed build:

```bash
python scripts/initialize_paper_continuity.py \
  --source-main-sha FULL_DEPLOYED_MAIN_SHA \
  --release-marker /app/RELEASE_COMMIT
```

The dry run must report `v8_demo=invalid_gap` and
`uptrend_sideways=healthy`. Review the processed dates, missing dates, source
SHA, calculation time, per-file hashes and aggregate ledger hash. To create
only the two missing `continuity_status.json` files, repeat the command with
the exact audit SHA printed by that dry run:

```bash
python scripts/initialize_paper_continuity.py \
  --source-main-sha FULL_DEPLOYED_MAIN_SHA \
  --release-marker /app/RELEASE_COMMIT \
  --write \
  --expected-audit-sha256 AUDIT_SHA_FROM_DRY_RUN
```

Immediately before the commit boundary, the CLI re-fetches market dates,
rebuilds both audits, and requires the resulting audit SHA to equal the
approved dry-run SHA. It repeats that validation after the two replacements.
The write is refused if the release marker, either ledger or its pinned
directory/file identity, market dates, expected statuses, or approved audit
changes. Symlink ledger directories, ledger files, metadata files, release
markers, and transaction journals are refused. Malformed or conflicting
metadata is never overwritten.

The two metadata replacements form one recoverable group operation. Before
writing either strategy, the CLI durably records both prior states in a
transaction journal in the common parent directory. It stages and fsyncs both
new files, atomically replaces V8 then Uptrend, validates the post-write audit,
and only then removes and fsyncs the journal. Any ordinary failure restores
both prior states before reporting failure. A process interruption can leave
the journal and a partial pair; the next write invocation detects the journal
and restores both prior states before proceeding.
Do not delete or edit the journal manually.

Directory fsync failure is an error, not a warning. Recovery is attempted and
the journal is retained if restoration cannot be proven complete. A successful
identical repeat is a no-op and preserves the original metadata bytes,
calculation timestamp, and filesystem modification time. Economic ledger
CSV/JSON records are read and hashed but never modified; only the two
`continuity_status.json` files and the transient recovery journal/temp files
are within the initializer's write set.
