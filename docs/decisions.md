# Decisions

This file records project decisions that should not be rediscovered from mixed code, notes, or experiments.

## Current Decisions

### Drishti Is Early Watch, Not Trade Advice

Drishti is a radar system. It finds stocks worth watching and researching.

It does not place orders, recommend entries as final instructions, or act as an automated trading system.

### Keep Data Separate From Drishti

The data layer owns token handling, instruments, universe membership, candles, and quality checks.

Drishti consumes data. It should not own data ingestion.

### Keep Research Tools Separate From Drishti

Momentum scans, move events, blind spot reports, and parameter sweeps are research tools.

They are allowed to be noisy and exploratory.

They are not official Drishti output unless explicitly promoted.

### Signal 01 Is Official

Official id:

- `DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL`

Purpose:

- Detect a fresh local low followed by immediate upside demand with volume confirmation.

### Signal 02 Is Research-Only

Current working family:

- Compact Volume Breakout

Status:

- Candidate only.
- Not saved as an official Drishti signal.
- The exact rejection math is not locked.

### Production Remains Untouched

All active work continues on `develop`.

Production `main` remains untouched until a tested release is intentionally approved.

## Open Decisions

- Whether Compact Volume Breakout should become Drishti Signal 02.
- How to mathematically separate valid compact breakouts from vertical exhaustion into supply.
- Whether Drishti research tools should eventually get a separate UI page.
