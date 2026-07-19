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
