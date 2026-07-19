# Backtesting operating policy

These instructions apply to every strategy backtest in this repository.

## Swing-server execution

- Run full strategy backtests and market-history evaluations on the swing server.
- Local execution is limited to implementation work, unit tests, small deterministic fixtures,
  static validation, and diagnostics needed to make the server run safe.
- Use the reusable backtesting engine and the server's existing market-data/cache paths. Write
  every evaluation into a fresh, immutable run directory; never overwrite an earlier result.

## Inspect before extending

- Before planning or implementing a backtest, inspect the current reusable engine, strategy
  interfaces, experiment framework, server deployment, available data, cache coverage, and
  existing reports or related strategy implementations.
- Decide that an extra capability is required only after this inspection proves the current
  system cannot express, execute, validate, or report the requested test correctly.
- Do not build speculative infrastructure or a strategy-specific duplicate of behavior that the
  current engine already provides.

## Build capability before the backtest

- If a required capability is missing, implement and validate that capability first. Do not run
  the requested full backtest until the extension passes focused tests and is available in the
  swing-server runner.
- Put generic execution, portfolio, cost, chronology, diagnostics, caching, and reporting behavior
  in the reusable engine. Keep strategy-specific indicators and rules in configurable plug-ins.
- Preserve backward compatibility unless the user explicitly approves a breaking change.

## Design priorities

Choose the smallest design that is correct and, in this order:

1. reuses current engine components, prepared features, cached candles, and existing artifacts;
2. minimizes complexity, repeated database reads, indicator recomputation, memory use, and runtime;
3. is deterministic, leakage-aware, and realistic about entry timing, gaps, costs, and ambiguous bars;
4. is configurable and reusable for materially different future strategies; and
5. produces enough diagnostics to explain acceptance, rejection, filtering, and sample-size changes.

Prefer prepared-once calculations, vectorized or batched operations, cached datasets, named rule
results, rejection funnels, chronological out-of-sample scopes, cost scenarios, and pre-declared
acceptance gates. Do not reduce thresholds or add filters after seeing results without labeling the
change as post-hoc research requiring independent validation.

## Permanent improvement and proof

- Treat every justified extension as a permanent improvement to the reusable backtesting system:
  add focused tests, configuration examples, and operator documentation.
- Commit and push the exact engine revision used for a server backtest, deploy that revision to the
  swing server, and verify local/GitHub/server commit parity before sign-off.
- Report the data range, symbols, candle rows, signals, activated and resolved trades, costs,
  chronological boundaries, output directory, cache state, relevant hashes, and explicit
  accept/reject verdict.
- Never describe a watchlist, diagnostic candidate, post-hoc variant, or attractive in-sample result
  as a validated trading strategy.
