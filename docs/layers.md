# Project Layers

This project has three separate layers. Keep them mentally and technically separate.

## 1. Data Layer

The data layer collects, stores, validates, and exposes market data.

Examples:

- Dhan token and renewal services
- Dhan client
- Dhan instrument master
- Nifty 500 universe
- Historical daily candles
- Data quality checks

Current backend examples:

- `backend/app/token_service.py`
- `backend/app/dhan_client.py`
- `backend/app/instrument_master.py`
- `backend/app/index_universe.py`
- `backend/app/historical_data.py`
- `backend/app/data_quality.py`

Rule:

> The data layer should not know what Drishti is.

## 2. Research / Discovery Tools

Research tools are allowed to be experimental. Their job is to discover, test, and challenge possible Drishti signals.

Examples:

- Momentum/range scans
- Move-event detection
- Blind spot reports
- False early detection reports
- Parameter sweeps
- Signal candidate cross-checks

Current backend examples:

- `backend/app/range_movers.py`
- `backend/app/move_events.py`

Current notes live under:

- `notes/research/`

Rule:

> Research tools are not official Drishti signals.

## 3. Drishti Layer

Drishti is the official early-watch radar system.

Only validated signals belong here.

Current official signal:

- `DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL`

Current backend example:

- `backend/app/drishti.py`

Rule:

> Drishti stores approved early-watch signals only. Candidate ideas stay in research until validated.

## Flow

```text
Data Layer
  -> clean candles and universe data

Research / Discovery Tools
  -> find patterns, misses, failures, and candidate rules

Drishti Layer
  -> stores only approved early-watch signals
```

## Naming Guidance

- Use `Drishti` only for approved signals and official radar output.
- Use `research`, `candidate`, `cross-check`, or `experiment` for discovery work.
- Do not call Signal 02 official until it has passed review and is intentionally promoted.
