# Drishti Signal 01 Blind Spot Report

Generated from the development server database.

Signal compared:

- `DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL`

Purpose of this report:

- Find historical `+10%` upward opportunities that Drishti Signal 01 did not catch.
- Use those missed opportunity families as raw material for future Drishti signals.

Important distinction:

- The `81.13%` number is Signal 01 follow-through: Drishti fired, then `43 / 53` hits later reached `+10%` from trigger close.
- This report measures coverage: a stock moved `+10%`, then we ask whether Signal 01 warned us.
- A strong follow-through rate and weak coverage can both be true. It means Signal 01 is precise for one pattern, not complete across all patterns.

## Classification Rules

Each `+10%` move event is classified as:

- `caught`: Signal 01 fired inside the move window, and the event still had at least `+10%` remaining from the Drishti trigger close to the event high.
- `late_or_too_extended`: Signal 01 fired inside the move window, but less than `+10%` remained from trigger close to event high.
- `missed`: the stock had a `+10%` move event, but Signal 01 did not fire inside that move window.
- `unscorable_lookback_limited`: the move started before Signal 01 had enough prior candles for a fair 45-session local-low check.

## Source Runs

- Move event run id: `1`
- Drishti run id: `2`
- Window: `2026-01-12` to `2026-05-12`
- Signal lookback: `45` sessions
- Volume confirmation: `1.2x` anchor volume and `1.0x` 20-session average volume

## Event-Level Coverage

This counts every stored `+10%` move event.

| Bucket | Count |
|---|---:|
| Total move events | 1,696 |
| Unscorable because of early lookback limit | 901 |
| Scorable move events | 795 |
| Caught | 16 |
| Late or too extended | 15 |
| Missed | 764 |

Scorable event coverage:

- Caught rate: `2.01%`
- Late/too-extended rate: `1.89%`
- Missed rate: `96.10%`

This is not a failure of Signal 01. It means Signal 01 catches only one specific reversal family.

## Best Opportunity Per Stock

This keeps only the strongest scorable `+10%` opportunity per symbol, which is easier for human review.

| Bucket | Count |
|---|---:|
| Scorable symbols with at least one `+10%` opportunity | 487 |
| Caught | 15 |
| Late or too extended | 3 |
| Missed | 469 |

Best-opportunity coverage:

- Caught rate: `3.08%`
- Missed symbols: `469`

This is the real blind-spot pool for future Drishti signals.

## Top Missed Best Opportunities

These are high-value moves that Signal 01 did not catch.

| Symbol | Company | Industry | Move | Low Date | Low | High Date | High | Sessions |
|---|---|---|---:|---|---:|---|---:|---:|
| HFCL | HFCL Ltd. | Telecommunication | 119.91% | 2026-03-30 | 67.15 | 2026-05-07 | 147.67 | 24 |
| WELCORP | Welspun Corp Ltd. | Capital Goods | 73.25% | 2026-03-23 | 759.00 | 2026-05-08 | 1315.00 | 29 |
| ADANIGREEN | Adani Green Energy Ltd. | Power | 71.82% | 2026-03-30 | 802.00 | 2026-05-07 | 1378.00 | 24 |
| BHEL | Bharat Heavy Electricals Ltd. | Capital Goods | 66.83% | 2026-04-06 | 239.17 | 2026-05-04 | 399.00 | 18 |
| ADANIPOWER | Adani Power Ltd. | Power | 62.05% | 2026-03-23 | 144.65 | 2026-05-05 | 234.40 | 26 |
| ADANIENSOL | Adani Energy Solutions Ltd. | Power | 61.87% | 2026-04-02 | 903.15 | 2026-04-29 | 1461.95 | 16 |
| NIACL | The New India Assurance Company Ltd. | Financial Services | 54.23% | 2026-03-30 | 116.97 | 2026-04-15 | 180.40 | 9 |
| ABDL | Allied Blenders and Distillers Ltd. | Fast Moving Consumer Goods | 53.89% | 2026-03-23 | 382.10 | 2026-04-20 | 588.00 | 16 |
| VIJAYA | Vijaya Diagnostic Centre Ltd. | Healthcare | 53.29% | 2026-03-30 | 848.00 | 2026-05-08 | 1299.90 | 25 |
| FINCABLES | Finolex Cables Ltd. | Capital Goods | 53.21% | 2026-04-02 | 765.50 | 2026-05-08 | 1172.80 | 23 |
| TITAGARH | Titagarh Rail Systems Ltd. | Capital Goods | 52.93% | 2026-03-30 | 568.70 | 2026-05-05 | 869.70 | 22 |
| CEMPRO | Cemindia Projects Ltd. | Construction | 52.81% | 2026-04-24 | 640.20 | 2026-05-04 | 978.30 | 5 |
| APTUS | Aptus Value Housing Finance India Ltd. | Financial Services | 52.26% | 2026-03-30 | 193.03 | 2026-05-07 | 293.90 | 24 |
| FIVESTAR | Five-Star Business Finance Ltd. | Financial Services | 51.36% | 2026-04-02 | 348.80 | 2026-04-21 | 527.95 | 11 |
| BANDHANBNK | Bandhan Bank Ltd. | Financial Services | 51.14% | 2026-04-02 | 140.70 | 2026-05-04 | 212.66 | 19 |
| LLOYDSME | Lloyds Metals And Energy Ltd. | Metals & Mining | 49.55% | 2026-03-30 | 1234.40 | 2026-05-06 | 1846.00 | 23 |
| BSE | BSE Ltd. | Financial Services | 49.22% | 2026-03-30 | 2676.60 | 2026-05-08 | 3994.00 | 25 |
| ENGINERSIN | Engineers India Ltd. | Construction | 49.07% | 2026-03-30 | 177.50 | 2026-04-27 | 264.60 | 17 |
| SUZLON | Suzlon Energy Ltd. | Capital Goods | 48.49% | 2026-03-30 | 39.10 | 2026-04-29 | 58.06 | 19 |
| RPOWER | Reliance Power Ltd. | Power | 48.49% | 2026-03-30 | 20.17 | 2026-04-15 | 29.95 | 9 |

## Late Or Too Extended Best Opportunities

These were not blind misses. Signal 01 fired, but it fired too late or too high to leave a clean `+10%` from trigger close.

| Symbol | Move | Low Date | High Date | Trigger Date | Trigger Close | Remaining From Trigger |
|---|---:|---|---|---|---:|---:|
| IIFL | 15.74% | 2026-04-27 | 2026-05-04 | 2026-04-27 | 434.00 | 9.10% |
| SUNPHARMA | 15.13% | 2026-04-24 | 2026-05-06 | 2026-04-27 | 1733.50 | 7.17% |
| INFY | 13.32% | 2026-03-19 | 2026-04-08 | 2026-03-20 | 1255.90 | 9.63% |

## Missed Best Opportunities By Industry

| Industry | Missed Symbols |
|---|---:|
| Financial Services | 96 |
| Capital Goods | 58 |
| Healthcare | 45 |
| Automobile and Auto Components | 36 |
| Consumer Services | 29 |
| Chemicals | 26 |
| Fast Moving Consumer Goods | 25 |
| Information Technology | 22 |
| Metals & Mining | 18 |
| Power | 17 |
| Oil Gas & Consumable Fuels | 17 |
| Consumer Durables | 15 |
| Construction | 13 |
| Services | 13 |
| Construction Materials | 11 |
| Realty | 10 |
| Telecommunication | 7 |
| Textiles | 5 |
| Media Entertainment & Publication | 4 |
| Diversified | 2 |

## First Conclusions

- Signal 01 has strong follow-through when it fires, but very low market-wide coverage.
- That is acceptable because Signal 01 is one pattern, not the full Drishti system.
- The next Drishti signal should come from the missed pool, especially the top missed best opportunities.
- The most urgent blind spot family appears to be strong continuation or base-breakout moves, not local-low reversals.
- `HFCL`, `WELCORP`, `ADANIGREEN`, `BHEL`, and `ADANIPOWER` are better candidates for discovering Signal 02 than the weak Signal 01 misses.

## Suggested Next Review Set

Open these charts first:

1. `HFCL`
2. `WELCORP`
3. `ADANIGREEN`
4. `BHEL`
5. `ADANIPOWER`
6. `ADANIENSOL`
7. `NIACL`
8. `ABDL`
9. `VIJAYA`
10. `FINCABLES`

For each chart, inspect the 5-10 sessions before the move starts. The question is not "why did it go up after the low?" The question is:

> What was visible before or at the early part of the move that Signal 01 could not see?
