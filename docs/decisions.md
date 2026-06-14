# Decisions

This file records project decisions that should not be rediscovered from mixed code, notes, or experiments.

## Current Decisions

### Active System Is Data Foundation First

The active system is focused on Dhan token handling, instrument master, Nifty 500 universe, historical candles, and data quality.

It does not place orders, recommend entries as final instructions, run AI review, or act as an automated trading system.

### Keep Data Separate From Retired Signal Code

The data layer owns token handling, instruments, universe membership, candles, and quality checks.

Retired signal/demo modules consume data only if manually redesigned later. They should not own data ingestion.

### Keep Review Tools Manual

Momentum scans, move events, and regime diagnostics are review tools.

They are allowed to be noisy and exploratory, but they must not trigger demo/trading action flows.

They are not official signal output unless explicitly redesigned and promoted.

### Drishti And Demo Flow Are Museum Code

The old Drishti, reversal opportunity, support/resistance, candlestick, watchlist, learning, demo trading, and journal modules are not active runtime.

They are retained only as reference where still present.

### Gemini / AI Review Is Removed

Gemini credentials, Gemini review, and local discipline review are removed from active development.

### Production Remains Untouched

All active work continues on `develop`.

Production `main` remains untouched until a tested release is intentionally approved.

## Open Decisions

- Whether any retired signal/demo module should return after a fresh design.
- Whether review diagnostics should remain in the current frontend or move to a separate diagnostics area.
