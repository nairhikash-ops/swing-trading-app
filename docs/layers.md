# Project Layers

This project currently has two active layers and one museum/reference area. Keep them mentally and technically separate.

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

## 2. Review / Diagnostics Tools

Review tools are manual diagnostics. They help inspect market data, but they do not control trading, demo trading, or data maintenance.

Examples:

- Momentum/range scans
- Move-event detection
- Regime diagnostics

Current backend examples:

- `backend/app/range_movers.py`
- `backend/app/move_events.py`
- `backend/app/regime.py`

Current notes live under:

- `notes/research/`

Rule:

> Review tools are not trading signals and must not run automatically from data maintenance.

## 3. Museum / Reference Code

Drishti and the old demo-trading flow are retired from the active runtime until a new design is approved.

Current museum examples:

- `backend/app/drishti.py`
- `backend/app/reversal_opportunities.py`
- `backend/app/support_resistance.py`
- `backend/app/candlesticks.py`
- `backend/app/watchlist.py`
- `backend/app/learning.py`
- `backend/app/demo_trading.py`
- `backend/app/trading_journal.py`

Rule:

> Museum code is not active runtime. It should not be wired into startup, data maintenance, or normal frontend navigation.

## Flow

```text
Data Layer
  -> clean candles and universe data

Review / Diagnostics Tools
  -> manually inspect movers, events, and regimes

Museum / Reference Code
  -> preserved for future redesign only
```

## Naming Guidance

- Use `review` or `diagnostics` for current non-trading tools.
- Do not promote museum code back into active runtime without an explicit design decision.
