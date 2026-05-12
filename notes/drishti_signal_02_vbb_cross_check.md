# Drishti Signal 02 Candidate Cross-Check

Subject: Volumetric Base Breakout / Compact Base Volume Breakout

Status: research candidate only. Not yet saved as a formal Drishti signal.

## Starting Hypothesis

An external review suggested HFCL was not a Signal 01 style local-low reversal. The proposed explanation was:

- HFCL did not capitulate.
- HFCL coiled.
- A possible Signal 02 could detect a tight base with volume dry-up, followed by a volume-backed breakout.

The proposed strict rule was:

- Previous 15-session range <= `8%`
- 10-session average volume < 50-session average volume
- Close > previous 15-session high
- Volume >= `2.5x` 20-session average volume
- Close in top 25% of daily candle

## Strict Rule Result

The strict proposed rule does not pass cross-check.

Across the current Nifty 500 historical data:

- Hits: `8`
- Unique symbols: `8`
- Hits reaching `+10%`: `1`
- Follow-through rate: `12.50%`
- HFCL caught: no
- Top-10 blind-spot stocks caught: `0`

Conclusion:

- The concept may be useful.
- The exact proposed 15-session / 8% rule is too strict and does not describe HFCL correctly in our data.

## Why The Strict Rule Missed HFCL

HFCL's relevant breakout candle appears on `2026-04-09`.

HFCL on `2026-04-09`:

- Close: `79.61`
- Previous 15-session base range: `15.41%`
- Volume vs 20-session average: `3.38x`
- Close strength: `0.70`
- Future high: `147.67` on `2026-05-07`
- Outcome from trigger close: `85.49%`

Strict rule failures:

- Previous 15-session range was not <= `8%`; it was `15.41%`.
- Close strength was not >= `0.75`; it was about `0.70`.

So HFCL was not a perfect 15-day tight box. It was closer to a short compact breakout after recent volume dry-up.

## Best Candidate Variant So Far

Working candidate:

- Previous 5-session range <= `16%`
- 10-session average volume < 50-session average volume
- Close > previous 5-session high
- Volume >= `2.5x` previous 20-session average volume
- Close strength >= `0.65`

This is better described as:

> Short compact base breakout with volume expansion.

## Candidate Variant Result

Across the current Nifty 500 historical data:

- Hits: `114`
- Unique symbols: `102`
- Hits reaching `+10%`: `53`
- Raw follow-through rate: `46.49%`
- Symbols overlapping Drishti Signal 01: `6`
- New symbols not already found by Signal 01: `96`

Because recent triggers near the end of the dataset do not have enough future candles, mature-trigger scoring is more useful:

| Future Sessions Available | Hits | Hits Reaching +10% | Follow-Through |
|---:|---:|---:|---:|
| 0+ | 114 | 53 | 46.49% |
| 5+ | 81 | 49 | 60.49% |
| 10+ | 68 | 46 | 67.65% |
| 15+ | 49 | 39 | 79.59% |

Interpretation:

- Raw score is noisy because late-window signals do not have time to mature.
- Matured signals look much stronger.
- This candidate deserves more review, but it is not ready to become Signal 02 without chart inspection.

## Top Blind Spots Caught By Candidate Variant

From the top blind-spot list:

| Symbol | Status | Trigger Date | Trigger Close | Remaining To Event High | Base Range | Vol/20D | Close Strength |
|---|---|---|---:|---:|---:|---:|---:|
| HFCL | caught | 2026-04-09 | 79.61 | 85.49% | 9.77% | 3.38x | 0.70 |
| WELCORP | caught | 2026-04-08 | 937.05 | 40.33% | 9.75% | 2.78x | 0.86 |
| ADANIGREEN | caught | 2026-04-06 | 921.10 | 49.60% | 8.32% | 3.58x | 0.92 |
| BHEL | caught | 2026-04-09 | 277.20 | 43.94% | 11.97% | 3.10x | 0.78 |
| VIJAYA | caught | 2026-04-07 | 928.85 | 39.95% | 6.81% | 3.35x | 0.79 |

Top blind spots still missed:

- `ADANIPOWER`
- `ADANIENSOL`
- `NIACL`
- `ABDL`
- `FINCABLES`

## Top Successful Candidate Hits

| Symbol | Trigger Date | Trigger Close | Base Range | Vol/20D | Close Strength | Outcome |
|---|---|---:|---:|---:|---:|---:|
| HFCL | 2026-04-09 | 79.61 | 9.77% | 3.38x | 0.70 | 85.49% |
| OLAELEC | 2026-04-01 | 25.89 | 11.99% | 4.15x | 0.85 | 62.22% |
| ADANIGREEN | 2026-04-06 | 921.10 | 8.32% | 3.58x | 0.92 | 49.60% |
| BHEL | 2026-04-09 | 277.20 | 11.97% | 3.10x | 0.78 | 47.51% |
| CPPLUS | 2026-03-25 | 1809.40 | 8.69% | 2.52x | 0.80 | 42.31% |
| GRSE | 2026-04-01 | 2359.30 | 14.53% | 7.90x | 0.97 | 41.53% |
| WELCORP | 2026-04-08 | 937.05 | 9.75% | 2.78x | 0.86 | 40.33% |
| VIJAYA | 2026-04-07 | 928.85 | 6.81% | 3.35x | 0.79 | 39.95% |

## Important Caveats

- The current dataset is only about 120 calendar days. The optional 200-day trend filter cannot be tested properly yet.
- Raw outcome scoring is right-censored near the latest candles. A trigger on `2026-05-08` may look failed only because we do not have enough future candles yet.
- The candidate catches a different family than Signal 01, which is good, but its raw precision is lower.
- This should not be implemented as formal Signal 02 until we visually inspect both successful hits and mature failures.

## Current Decision

Do not finalize Signal 02 yet.

What we can say:

- The "Volumetric Base Breakout" family is real enough to keep researching.
- The exact Gemini version is rejected.
- The better candidate is a short compact base breakout:
  - 5-session compact range
  - prior volume dry-up
  - high-volume breakout
  - close holding at least 65% of the candle range

Suggested working name:

> Drishti Signal 02 Candidate: Compact Volume Breakout

Next review set:

1. `HFCL` on `2026-04-09`
2. `WELCORP` on `2026-04-08`
3. `ADANIGREEN` on `2026-04-06`
4. `BHEL` on `2026-04-09`
5. `VIJAYA` on `2026-04-07`
6. `OLAELEC` on `2026-04-01`
7. `CPPLUS` on `2026-03-25`
8. `GRSE` on `2026-04-01`

Also inspect mature failures:

1. `PREMIERENE` on `2026-04-17`
2. `BALRAMCHIN` on `2026-04-22`
3. `SJVN` on `2026-04-22`
4. `GMDCLTD` on `2026-04-16`
5. `COLPAL` on `2026-04-17`
