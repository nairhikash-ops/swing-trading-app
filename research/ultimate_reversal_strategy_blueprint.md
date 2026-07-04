# Corrected 10% Reversal Research

## 1. Data Correction

The original research was not based on 9,500+ instruments with full candle history.

Correct scope:

- Active NSE instruments in DB: `9,504`
- Instruments with candle history: `503`
- Symbols used in successful-reversal study: `497`
- Symbols in corrected all-events validation: `469`
- Candle range: `2021-06-17` to `2026-06-17`

So the correct framing is:

> This research is based on NSE equity candle history for roughly 500 candle-backed instruments, not the full 9,500+ instrument master.

## 2. Biggest Methodology Correction

The original `7,090` reversals were future-confirmed winners. That means many findings describe what successful reversals looked like after we already knew they worked.

Correct framing:

> The 7,090-reversal study is useful for clue generation, but it is not proof of predictive edge.

The corrected all-events denominator found:

- Candidate crash/downtrend events: `10,653`
- Fixed next-open trade, `-5%` stop, `+10%` target:
  - Overall win rate: `34.09%`
  - Avg PnL: `+0.29%`
  - Test period `2025-05+`: `31.14%`
  - Test avg PnL: `-0.13%`

## 3. Exact Bottom Correction

The original research repeatedly called the setup day the “exact bottom.”

That is not correct.

The setup date was the lowest low before target only about `22.61%` of the time. Median additional drawdown after setup was about `-2.95%`.

Correct conclusion:

> The setup day is usually not the exact bottom. It is better described as an early crash-zone signal that often suffers further drawdown before any reversal.

## 4. Candlestick Correction

The original same-day candlestick section is wrong.

Correct same-day numbers:

- Hammer: `0.78%`
- Bullish engulfing: `0.28%`
- Doji: `4.05%`
- No classic pattern on same day: roughly `94%+`

Correct conclusion:

> Classic candlestick patterns almost never identify the crash-day entry itself.

The 11-day window finding is still mostly valid:

- Any classic pattern around the bottom: `95.46%`
- Doji: `68.07%`
- Harami: `54.40%`
- Morning Star: `38.77%`

But corrected interpretation:

> Candlestick patterns appear around successful bottoms, but that does not prove they predict bottoms unless tested against failed crash events too.

## 5. Maximum Pain Correction

Original claim:

> RSI2 < 20, lower Bollinger Band, and stochastic oversold define the true DNA of a crash bottom.

Corrected result:

- `radar_max_pain` events: `2,463`
- Overall win rate: `34.15%`
- Avg PnL: `+0.44%`
- Test period win rate: `27.68%`
- Test avg PnL: `-0.49%`

Correct conclusion:

> Maximum pain is common in successful reversals, but by itself it does not produce a robust tradable edge.

## 6. Early Warning Correction

Original early warning signals were directionally useful, but overstated.

Corrected all-event result:

- `radar + pre-warning`:
  - Overall win rate: `35.13%`
  - Avg PnL: `+0.55%`
  - Test period win rate: `28.13%`
  - Test avg PnL: `-0.39%`

Correct conclusion:

> Volume exhaustion and wick expansion slightly improve the setup, but not enough to survive out-of-sample as a standalone rule.

## 7. Confirmation Correction

The original report treated EMA5/RSI confirmation as very powerful, but some earlier scoring effectively benefited from crash-day entry.

Correct forward-only confirmation result:

- `radar -> wait for EMA5 + RSI40 confirmation -> enter next open`
- Trades: `1,201`
- Overall win rate: `32.64%`
- Avg PnL: `+0.09%`
- Test period win rate: `29.19%`
- Test avg PnL: `-0.31%`

Correct conclusion:

> Confirmation improves psychological comfort, but it does not currently improve the actual forward-tested edge.

## 8. Historical Support Correction

Original finding:

- Successful reversals hit historical support only `34.13%` of the time.

This number is probably true for winners, but the conclusion is too strong.

Corrected all-event result (Double Bottom + Weak Breakout):

- `Support Zone` (Crash low within 3% of a prior 1-year low):
  - Trades: `29` (Less than 5% of candidate crashes)
  - Win Rate: `37.93%`
  - Avg PnL: `+3.90%`
- `Middle of Nowhere` (Reversed in mid-air):
  - Trades: `575`
  - Win Rate: `27.30%`
  - Avg PnL: `+2.05%`

Correct conclusion:

> Historical support is not required for a successful reversal, but mid-air reversals are significantly less tradable. When an unconditioned crash hits a true historical support zone, the win rate leaps by over 10% and the expectancy nearly doubles. However, these clean support setups are incredibly rare (less than 5% of all crashes).

## 9. Overhead Supply Correction

The “overhead supply” thesis is plausible, but not mathematically proven.

Correct conclusion:

> The data shows crash-zone reversals have unstable win rates and often fail after rebounds. “Overhead supply” is a reasonable market explanation, but the research has not directly measured trapped holder supply.

## 10. Correct Final Verdict

The original conclusion was too confident.

**Corrected Conclusion:** When tested in a forward-only, unconditioned environment, the Double Bottom + Weak Breakout setup failed to preserve the earlier 40%+ win-rate result. The out-of-sample test produced a 25.13% win rate across 191 trades, confirming that the earlier high win rate was inflated by winner-conditioning and structure-selection bias.

However, the strategy was not completely dead: out-of-sample expectancy remained positive at +1.21% per trade. This means the setup is not a high-win-rate reversal system, but it may still be a low-win-rate, high-payoff candidate that requires separate drawdown, overlap, capital usage, and regime testing.

## 11. Regime Analysis: The Missing Filter

Per the conclusion, we analyzed the broader market regime during the specific Strong vs. Weak months identified in the forward-tester. We measured **Market Breadth** (percentage of stocks above their 50-day EMA) and **Average Market Return**.

**STRONG MONTHS (High Win Rate):**
- `2025-05`: Avg Breadth: **74.37%** | Avg Market Return: **+8.79%**
- `2025-06`: Avg Breadth: **75.82%** | Avg Market Return: **+3.93%**
- `2026-04`: Avg Breadth: **59.48%** | Avg Market Return: **+15.90%**

**WEAK MONTHS (Low Win Rate):**
- `2025-07`: Avg Breadth: **69.29%** | Avg Market Return: **-1.95%**
- `2025-11`: Avg Breadth: **46.00%** | Avg Market Return: **-1.80%**
- `2026-02`: Avg Breadth: **44.86%** | Avg Market Return: **+1.49%**
- `2026-03`: Avg Breadth: **21.13%** | Avg Market Return: **-10.64%**

### Corrected Regime Conclusion

Market regime clearly affects crash-reversal performance, but the current evidence does not yet prove a universal mandatory regime filter.

The strongest months occurred when the broader market return was sharply positive, and the weakest months often occurred when breadth or market return deteriorated. However, breadth alone did not explain all outcomes: 2025-07 had high breadth but weak reversal performance because market return was negative.

A simple regime filter using strong monthly market return improves the test-period result, but validation remains weak. Therefore, regime is a promising explanatory variable and should be added to the next research pass, but it is not yet a proven deployable filter.

Correct status: regime filter candidate, not final rule.

The overhead-supply thesis remains a plausible explanation for the low win rate, but it is not directly proven by this test. The safe conclusion is that this reversal family is unsuitable as a clean retail-style high-win-rate system. It should not be deployed without portfolio-level risk validation.

## 12. The Raw Falling Knife Revelation

To finalize the regime thesis, the regime filter (Market Return >= +5%) was cross-referenced against the raw, unconditioned "Falling Knife" trade (buying the exact next open after a 15% drop, with no Double Bottom or Weak Breakout filter required).

The results completely flipped the structural assumptions:

- **Strong Regime (Market Return >= +5%) on Raw Falling Knives:**
  - Total Trades: `7,007`
  - Win Rate: `49.35%`
  - Avg PnL: `+2.49%`
  - Validation WR: `39.83%` (vs `18.37%` when using the Double Bottom filter)
  - Test WR: `52.55%`
- **Weak Regime (Market Return < +5%) on Raw Falling Knives:**
  - Total Trades: `16,665`
  - Win Rate: `29.05%`
  - Avg PnL: `-0.58%`

### Corrected Section 12 Verdict

Raw falling-knife trades show a powerful post-hoc relationship with strong market months. When the full entry month later finished with market return >= +5%, raw crash entries performed extremely well. When the month finished below that threshold, results deteriorated sharply.

However, this is not yet a tradable rule because the full monthly return is unknown at the time of entry. Therefore, `Market Return >= +5% this month` is an oracle/regime label, not a forward-safe filter.

Correct conclusion: crash reversals are highly regime-sensitive, and strong market momentum may be the missing variable. But the next test must use only information known before entry, such as prior-month return, month-to-date return through yesterday, market breadth through yesterday, or index trend through yesterday.

### 13. Forward-Safe Regime Test (Final Nail)
When restricted strictly to no-lookahead regime filters (data known *before* the market open), the regime edge collapses completely back to the 30% baseline.

**Baseline (No Filter):** Val WR: `32.04%` | Test WR: `30.90%`
- **Prior Month Return >= +5%:** Val WR: `33.75%` | Test WR: `28.54%` (No edge)
- **MTD Return (through yesterday) >= +2%:** Val WR: `31.39%` | Test WR: `36.91%` (Inconsistent)
- **Yesterday Breadth >= 60%:** Val WR: `29.77%` | Test WR: `30.49%` (Worse than baseline)
- **Index > EMA20 / EMA50:** Val WR: `~29.0%` | Test WR: `~29.0%` (Worse than baseline)

**Final Status:** Dead strategy. Predicting a falling knife requires predicting the exact month's closing market return, which is impossible at entry. Without future knowledge, no combination of breadth or prior momentum can save the crash reversal.

## 14. Exhaustive Multi-Variable Heatmap (The Absolute Limit)

To ensure no hidden edge was missed, we ran an exhaustive grid search over 5,101 unique combinations of the following 9 no-lookahead features:
1. Prior Month Market Return
2. Month-To-Date (MTD) Market Return
3. Breadth Trend (Rising/Falling over 5 days)
4. Stock Relative Strength vs Market (20 days)
5. Crash Depth bucket
6. ATR Volatility bucket
7. Distance to 1-Year Historical Support
8. Structure (Double Bottom or not)
9. Trigger (Same-Day Weak Candle or not)

The test required a minimum sample size (Train >= 50, Val >= 30, Test >= 30) and required the combination to beat the baseline win rate out-of-sample while maintaining positive expectancy across two different exit models (Fixed and Structural).

**Result:** Out of 5,101 full-bucket exact combinations, exactly **0** combinations passed the robustness thresholds due to sample size fragmentation and lack of lower-order generalization.

The first full-bucket heatmap found no robust 10-variable exact bucket under strict sample-size gates. This weakened the crash-reversal thesis further, but it did not exhaust the search space. 

## 15. Lower-Order Heatmap & Final Validation (The Survivor)

A revised lower-order heatmap (testing 1D, 2D, and 3D combinations) successfully isolated a robust, highly profitable **Candidate Family**.

The candidate family centers around **Raw Crash Events** occurring under **High Volatility (ATR > 3.5%)**, **Normal Volume (0.5x to 2.0x)**, and **Neutral Relative Strength**. Neither classical candlestick patterns nor structural Double Bottoms are required.

To ensure this was not a curve-fit artifact, an exhaustive **Walk-Forward Validator** was deployed across 13,824 threshold combinations, optimized strictly for out-of-sample expectancy decay and portfolio concurrency on Train/Validation sets, leaving the Test set (2025-05+) completely untouched.

### Final Locked Parameters (The Validated Candidate)
- **ATR Threshold:** `> 3.5%` (Must be highly volatile)
- **RS Band:** `[-5.0%, +5.0%]` (Must not be in a structural death-spiral)
- **Volume Ratio Band:** `[0.5x, 2.0x]` (Must not be a climax or dry-up)
- **Crash Depth:** `>= 15.0%`
- **Cooldown Days:** `15` (Prevents signal stacking)
- **Entry Timing:** `Next Close`
- **MTD Regime:** `> 2%` (Market must have positive month-to-date momentum)

### Walk-Forward Fixed Exit Performance (-5% Stop / +10% Target)
| Dataset | Trades | WR | Avg PnL | Profit Factor | Avg Hold | Max Conc. Pos | Max Losing Streak |
|---|---|---|---|---|---|---|---|
| **Train (Pre-2024)** | 21 | 47.62% | +1.94% | 1.71 | 8.1d | 3.0 | 4 |
| **Val (2024 - 2025-04)** | 27 | 48.15% | +2.02% | 1.75 | 7.6d | 6.0 | 7 |
| **Test (2025-05+)** | 27 | 59.26% | +3.69% | 2.74 | 10.0d | 7.0 | 5 |
| **All-Time** | 75 | 52.00% | +2.60% | 2.04 | 8.6d | 7.0 | 7 |

### Portfolio Stress Testing
- **Max Drawdown (Linear PnL sum):** `36.40%`
- **Performance excluding best month & top 5 symbols:** `+1.55%` Avg PnL per trade (Still highly positive)

### Final Conclusion
The raw crash reversal is **not** a dead strategy, but it is extremely narrow. The vast majority of crashes fail. However, when a stock crashes 15%+ while maintaining high volatility, normal volume, and neutral relative strength during a market that is already up >2% on the month, buying the next close shows a strong edge.

This setup is rare (averaging only 1-3 trades per month). While it survived an initial train/validation threshold search and produced excellent test results, the sample size is small and the broader MTD >2% regime itself carries much of the edge.

This is a validated research candidate requiring corrected cooldown testing, larger-sample robustness checks, and portfolio simulation.

## 16. The Crash Zone Classification Breakthrough

A major philosophical error in early reversal testing was treating all "Crash Zones" as identical. A crash zone only tells you that the price stopped falling aggressively; it does not tell you *why* it stopped.

To test this, we built a **Leakage-Free Crash Zone Classifier** that strictly isolates data known on the day of the crash from structural price action occurring in the days that follow.

### The 8 Crash Zone Types (Day-0 Labels)
1. **Accumulation**: High lower-wick rejection, elevated volume, neutral/strong RS.
2. **Short-Covering Bounce**: Deep crash, low/normal volume, weak close.
3. **Value-Buying Pause**: Moderate bounce, average volume, remains below MAs.
4. **Liquidity Trap**: Crash low lands exactly on a 1-year pivot support zone.
5. **News/Event Repricing**: Gap down > 5%, Volume > 3x, massive ATR expansion.
6. **Market-Panic**: Broad market MTD return is deeply negative.
7. **Sector-Rotation / Weakness**: Stock's 20-day RS vs Universe is in bottom quartile.
8. **Exhaustion Zone**: Massive panic candle, Volume > 3x, extremely long lower wick.

### The "Dead-Cat" vs "Confirmed Structure" Test
We tested buying the immediate bounce (`Raw_Next_Open`) versus waiting for a structural confirmation (`Confirmed_Higher_Low` breakout) across the isolated crash labels. The out-of-sample results definitively proved that structural confirmation is mandatory:

- **Market Panic Crashes**:
  - Buying the blind bounce: `25.06%` Win Rate (Negative Expectancy)
  - Waiting for Higher Low: `53.38%` Win Rate (Highly Positive Expectancy)
- **Liquidity Traps (1-Year Support)**:
  - Buying the blind bounce: `21.99%` Win Rate
  - Waiting for Higher Low: `43.94%` Win Rate
- **Short-Covering Candidates**:
  - Buying the blind bounce: `30.86%` Win Rate
  - Waiting for Higher Low: `43.75%` Win Rate

### Types to Avoid Entirely
- **News/Event Repricing Gaps**: The structural charts are fundamentally broken. Both entry methods collapsed to sub-15% win rates.
- **Exhaustion (Climax Wicks)**: Both entry methods yielded **0.00%** out-of-sample win rates. Massive lower wicks at the absolute bottom of a crash are frequently just bear flags before final structural capitulation.

### Final Blueprint Conclusion
**In this first classifier pass, crash events that later formed a higher-low breakout had materially better forward expectancy than blind next-open crash entries. This supports the higher-low confirmation thesis, but the implementation still needs label-quality fixes before final promotion.**

Blind crash-zone buying appears weak. Post-crash higher-low confirmation appears to significantly improve reversal quality. However, this is not yet proven until the implementation is audited for lookahead bias, sample size, execution realism, overlap, and survivorship bias.

## 17. V1 Classifier Forensic Audit Baseline

The first crash-zone classifier result was promising, but it could not be accepted as proof until the exact trade path was audited event by event. A forensic audit was therefore built in `v1_audit_generator_fixed.py` and exported into two relational CSVs:

- `v1_audit_events_fixed.csv`: one row per unique crash event and trade path.
- `v1_audit_labels_fixed.csv`: mapping of each `event_id` to one or more Day-0 crash labels.

This fixed audit intentionally preserves the true V1 logic, including the known V1 flaws, so the results can be reconciled against the original classifier:

- The post-crash structure search uses the original V1 `break` behavior when a fresh lower low appears.
- The structure window matches V1 exactly: `range(1, 15)`.
- `Raw_Next_Open` rows have no future `confirmation_date` or `higher_low_date`.
- `event_id` is deterministic and unique in the event table.
- Concurrency is counted by unique `event_id`, not duplicated label rows.
- Same-day stop/target ambiguity is handled pessimistically as stop-first.

### Audit Integrity Checks

The regenerated fixed audit produced:

- **Unique event rows:** `6,745`
- **Mapped label rows:** `8,498`
- **Symbols represented:** `478`
- **Raw future structure leakage:** `0`
- **Confirmed entries before/at confirmation:** `0`
- **Exit before entry:** `0`
- **Max event-level concurrency:** `74`

Important universe correction: this is not a 9,500-symbol test. The instrument master contains roughly 9,500 active NSE equity instruments, but only about 500 active equity instruments have candle data, and 478 symbols appear in the fixed audit.

### True Unique-Event Test Performance

| Structure | Test Events | Target WR | Positive-PnL WR | Expectancy |
|---|---:|---:|---:|---:|
| **Confirmed_Higher_Low** | `279` | `38.35%` | `44.80%` | `+1.32%` |
| **Raw_Next_Open** | `1,124` | `21.89%` | `28.47%` | `-1.20%` |

The old duplicated-label view still reconciles closely to the original headline result. In the Test split, `Market_Panic -> Confirmed_Higher_Low` produced:

- **Duplicated label rows:** `130`
- **Target WR:** `52.31%`
- **Positive-PnL WR:** `59.23%`
- **Expectancy:** `+3.46%`

### Correct Interpretation

The strict forensic audit supports the confirmation thesis: waiting for a confirmed higher-low breakout after a crash materially outperforms blind next-open dip buying.

However, this is still not deployable. V1 deliberately preserves flawed components so the baseline remains comparable:

- `Support_Candidate` still uses the flawed unshifted rolling 250-day low logic.
- The market regime proxy still uses average close percentage change, not a true index or equal-weight return proxy.
- Multi-label classification is useful for analysis but must not be treated as independent trade count.
- The evidence is limited to the candle-backed universe, not the full instrument master.

### V2 Direction

V2 should be a controlled delta against this frozen V1 baseline. It should not introduce new strategy ideas until the flawed V1 labels and proxies are corrected.

Required V2 changes:

1. Replace `Support_Candidate` with a prior-only support calculation, ideally prior pivot lows whose pivot dates are strictly before the crash date.
2. Replace the crude market proxy with either a real index instrument, if available, or an equal-weight daily return proxy computed per symbol before aggregation.
3. Preserve the V1 execution model: crash detection, break-on-new-low structure search, next-open entry, -5% stop, +10% target, timeout, friction, and pessimistic same-day ambiguity.
4. Produce side-by-side V1 vs V2 reports showing event counts, label counts, Test WR, expectancy, label migration, and events added/removed by the corrected labels.

The V2 question is narrow: did fixing the flawed labels and market proxy improve the edge, weaken it, or merely relabel the same higher-low effect?

## 18. V2 Classifier Audit Results

V2 was implemented as a strictly controlled delta against the frozen V1 forensic baseline. The execution engine was intentionally left unchanged:

- Same crash detection.
- Same `range(1, 15)` post-crash structure window.
- Same break-on-new-low behavior.
- Same next-open entry.
- Same +10% target, -5% stop, 20-day timeout, friction, and pessimistic stop-first ambiguity policy.
- Same deterministic `event_id` formula, allowing direct V1 vs V2 migration analysis.

Only two label/proxy flaws were corrected:

1. `Support_Candidate` now uses a prior-only shifted support calculation: `low.shift(1).rolling(250).min()`.
2. `Market_Panic` now uses an equal-weight daily return proxy: per-instrument daily percentage returns are computed first, then averaged by date.

### V2 Audit Integrity

The V2 run produced:

- **V1 event rows:** `6,745`
- **V2 event rows:** `6,745`
- **Events only in V1:** `0`
- **Events only in V2:** `0`
- **V1 label rows:** `8,498`
- **V2 label rows:** `8,435`
- **Raw future structure leakage:** `0`
- **Confirmed entries before/at confirmation:** `0`
- **Exit before entry:** `0`

This confirms that V2 did not change the trading universe or execution path. It only changed label assignment.

### Label Migration

The label migration file `v1_v2_label_migration.csv` showed:

- **Events with any label change:** `526`
- **Support_Candidate lost:** `16`
- **Support_Candidate gained:** `0`
- **Market_Panic lost:** `315`
- **Market_Panic gained:** `195`
- **Raw_Crash_Unclassified lost:** `123`
- **Raw_Crash_Unclassified gained:** `196`

The support fix removed a small number of false support labels created by the crash day itself. The market proxy fix had a much larger classification impact, proving that the original average-close market regime proxy materially distorted the panic label population.

### V1 vs V2 Market Panic Higher-Low Test

Liquid Test split, duplicated-label view for `Market_Panic -> Confirmed_Higher_Low`:

| Metric | V1 Frozen Baseline | V2 Corrected Labels |
|---|---:|---:|
| Rows | `130` | `125` |
| Target WR | `52.31%` | `51.20%` |
| Positive-PnL WR | `59.23%` | `58.40%` |
| Expectancy | `+3.46%` | `+3.29%` |

### V2 Unique-Event Structure Performance

Because the event universe and execution paths are unchanged, the unique-event structure-level performance remains the same as the frozen V1 baseline:

| Structure | Test Events | Target WR | Positive-PnL WR | Expectancy |
|---|---:|---:|---:|---:|
| **Confirmed_Higher_Low** | `279` | `38.35%` | `44.80%` | `+1.32%` |
| **Raw_Next_Open** | `1,124` | `21.89%` | `28.47%` | `-1.20%` |

### Correct Interpretation

V2 did not discover a new edge. It hardened the label definitions and showed that the `Market_Panic -> Confirmed_Higher_Low` subset remained strong after replacing the flawed market proxy.

The key conclusion is therefore narrower and stronger than the original claim: the higher-low confirmation effect is not dependent on the V1 support lookahead flaw or the V1 average-close market proxy. However, the system is still not deployable until it survives portfolio-level constraints, broader universe coverage, and additional robustness checks.

## 19. Portfolio Constraint Simulation

A portfolio constraint simulator was built to test whether the V2 crash-reversal edge survives realistic capital limits and clustered signals. The simulator reads `v2_audit_events.csv` and `v2_audit_labels.csv`, then processes trades chronologically with:

- Max concurrent position slots: `3`, `5`, and `10`.
- One open trade per symbol.
- Fixed slot weight at entry: `equity / max_slots`.
- Closed-trade equity accounting.
- Closed-equity drawdown, not true mark-to-market drawdown.
- Ranking rules: liquidity, panic severity, positive entry gap, negative entry gap, and 100-run Monte Carlo random selection.

### Important Correction

The first portfolio run reported strong full-history results, but that was not sufficient out-of-sample proof. The simulator was corrected to report both:

- `All`: full historical audit period.
- `Test`: out-of-sample split only.

The random ranking rule was also corrected from a single deterministic shuffle to a 100-run Monte Carlo average.

### Market Panic + Confirmed Higher Low

Subset: `V2_Market_Panic_Confirmed`

Full-history results are strong, especially under negative entry-gap ranking:

| Scope | Slots | Ranking | Return | Closed DD | Taken | Skipped |
|---|---:|---|---:|---:|---:|---:|
| All | `3` | `entry_gap_negative` | `+40.28%` | `12.95%` | `79` | `638` |
| All | `5` | `entry_gap_negative` | `+37.72%` | `8.84%` | `120` | `597` |
| All | `10` | `entry_gap_negative` | `+14.49%` | `9.50%` | `194` | `520` |

However, Test-only performance is much more modest:

| Scope | Slots | Ranking | Return | Closed DD | Taken | Skipped |
|---|---:|---|---:|---:|---:|---:|
| Test | `3` | `entry_gap_negative` | `-3.16%` | `13.84%` | `34` | `91` |
| Test | `5` | `entry_gap_negative` | `+5.07%` | `8.46%` | `42` | `83` |
| Test | `10` | `entry_gap_negative` | `+6.02%` | `6.81%` | `67` | `58` |
| Test | `10` | `liquidity_desc` | `+4.55%` | `6.81%` | `68` | `57` |

Worst Test cluster day for this subset: `2026-04-07`, with `22` simultaneous valid signals.

### All Confirmed Higher Low

Subset: `V2_All_Confirmed_Higher_Low`

The broader confirmed-higher-low set performed better than the narrow panic subset in the Test portfolio simulation:

| Scope | Slots | Ranking | Return | Closed DD | Taken | Skipped |
|---|---:|---|---:|---:|---:|---:|
| Test | `5` | `liquidity_desc` | `+13.64%` | `8.99%` | `74` | `203` |
| Test | `5` | `entry_gap_negative` | `+11.42%` | `8.05%` | `78` | `199` |
| Test | `3` | `liquidity_desc` | `+10.83%` | `8.50%` | `43` | `236` |
| Test | `5` | `random_100_avg` | `+9.86%` | `8.58%` | `73.92` | `203.08` |

This suggests the structural confirmation effect may be broader than the `Market_Panic` label alone.

### All Liquid Crash Events

Subset: `V2_All_Liquid_Events`

The full liquid crash universe remains weak. Test theoretical expectancy was approximately `-0.70%`, and most constrained portfolio rankings were negative. The best Test row found was:

| Scope | Slots | Ranking | Return | Closed DD | Taken | Skipped |
|---|---:|---|---:|---:|---:|---:|
| Test | `10` | `entry_gap_negative` | `+5.25%` | `8.87%` | `142` | `1,232` |

This is not enough to promote the full crash universe. The confirmation filter remains essential.

### Correct Portfolio Interpretation

The portfolio simulation supports the higher-low confirmation thesis, but it does not yet prove deployability.

What survived:

- Confirmed higher-low entries retain positive Test portfolio behavior under realistic slot limits.
- The broad confirmed-higher-low set appears more robust than the narrow panic-only subset.
- Blind/all-liquid crash exposure remains weak.

What did not survive as originally stated:

- The `+40.28%` result is full-history, not Test-only.
- A 3-slot panic-only sleeve did not survive Test-only under negative-gap ranking.
- Entry-gap ranking uses the official entry open to rank trades while also filling at that open; this is a useful diagnostic, but it may not be live-executable unless the open price is available through a pre-open auction or indicative open mechanism.
- Drawdown is closed-equity drawdown only, not daily mark-to-market drawdown.

Next required step: rebuild the portfolio simulator with daily mark-to-market equity using candle paths for open trades, and test live-executable ranking rules that are known before the entry fill.

## 20. True Mark-to-Market Portfolio Simulation

The portfolio simulator was upgraded into `mtm_portfolio_simulator.py` to calculate true daily mark-to-market equity instead of closed-trade-only equity. The simulator uses:

- Test split only.
- Cash and share accounting.
- Position sizing at entry: `equity / max_slots`.
- No rebalancing after entry.
- Daily close valuation for open positions.
- Ranking rules known before the entry open:
  - `liquidity_t1_desc`
  - `panic_severity_t1_asc`
  - `conf_day_return_desc`
  - `conf_day_return_asc`
  - `random_100_avg`

### Critical Simulator Correction

The first MTM implementation still had a hidden flaw: it only iterated dates that were entry dates or exit dates. That was not true daily MTM. The simulator was corrected to iterate every available trading day from the candle database between the first entry and last exit.

After this correction, missing MTM days were no longer zero. Missing candles were handled by carrying forward the last available close, with tracking columns:

- `missing_mtm_days`
- `missing_mtm_trade_count`
- `max_consecutive_missing_mtm_days`

The maximum consecutive missing streak was `3` days across the reported runs. This is acceptable for a research pass but must be kept visible.

### Test Market Panic + Confirmed Higher Low

Subset: `Test_Market_Panic_Confirmed`

| Slots | Ranking | Return | MTM Max DD | Taken | Skipped | Missing MTM Days |
|---:|---|---:|---:|---:|---:|---:|
| `5` | `panic_severity_t1_asc` | `+7.99%` | `10.65%` | `38` | `86` | `69` |
| `10` | `liquidity_t1_desc` | `+7.11%` | `9.07%` | `65` | `57` | `102` |
| `10` | `conf_day_return_desc` | `+6.39%` | `9.49%` | `63` | `58` | `104` |
| `3` | `liquidity_t1_desc` | `-2.19%` | `14.60%` | `35` | `90` | `31` |

The panic-only sleeve remains modest. It is not the strongest portfolio expression of the edge.

### Test All Confirmed Higher Low

Subset: `Test_All_Confirmed_Higher_Low`

| Slots | Ranking | Return | MTM Max DD | Taken | Skipped | Missing MTM Days |
|---:|---|---:|---:|---:|---:|---:|
| `3` | `conf_day_return_desc` | `+30.46%` | `18.50%` | `29` | `245` | `60` |
| `3` | `liquidity_t1_desc` | `+29.03%` | `20.43%` | `41` | `236` | `59` |
| `5` | `liquidity_t1_desc` | `+27.74%` | `16.06%` | `71` | `203` | `91` |
| `5` | `random_100_avg` | `+23.17%` | `16.13%` | `70.13` | `203.26` | `89.73` |
| `3` | `conf_day_return_asc` | `-17.57%` | `38.24%` | `41` | `234` | `54` |

The strongest result came from ranking by the strongest confirmation-day candle (`conf_day_return_desc`) in a 3-slot sleeve. The weakest confirmation-day ranking (`conf_day_return_asc`) failed badly in the 3-slot case. This supports the idea that the confirmation candle quality matters: a higher-low breakout needs decisive demand, not a barely confirmed structure.

However, liquidity ranking also performed very well, so the evidence does not support a single-factor conclusion yet. The ranking edge must be tested further before it is treated as a final rule.

### Correct MTM Interpretation

What survived:

- The broader `All Confirmed Higher Low` sleeve survived true daily MTM accounting in the Test split.
- The edge remains strongest under tight slot constraints, where selection quality matters.
- Ranking by confirmation-day strength appears promising and is known before the entry open.

What remains unresolved:

- Missing candle carry-forward is nonzero and must be monitored.
- MTM max drawdown is materially higher than closed-trade drawdown.
- Panic-only is weaker than the broader confirmed-higher-low sleeve.
- `conf_day_return_desc` is promising but not yet proven as a robust ranking rule.

Next required step: audit the taken-vs-skipped trade anatomy for the best MTM rows, especially `Test_All_Confirmed_Higher_Low` with 3 slots and `conf_day_return_desc`, to verify that the result is not dependent on one cluster, one month, or a few symbols.

## 21. Trade Anatomy Audit: Conf-Day Momentum Rejection

The best MTM row from Section 20 was `Test_All_Confirmed_Higher_Low`, 3 slots, ranked by `conf_day_return_desc`. It showed:

- **MTM total return:** `+30.46%`
- **MTM max drawdown:** `18.50%`
- **Taken trades:** `29`
- **Skipped trades:** `245`

This looked strong at the portfolio level, but the anatomy audit rejected the ranking rule.

### MTM vs Realized Return Split

The headline MTM result was not fully realized closed-trade profit:

- **Final equity:** `130,459.03`
- **Final cash:** `10,753.03`
- **Final open position value:** `119,706.00`
- **Closed realized return:** `+12.19%`
- **Final open unrealized return contribution:** `+18.26%`
- **MTM total return:** `+30.46%`

This means more than half of the headline return came from open-position mark-to-market value at the final candle date, not closed completed trades.

### Monthly Robustness

- **Best month:** `2025-05`, `+10.06%`
- **Return excluding best month:** `+2.13%`
- **Return excluding top 2 months:** `-1.52%`
- **Positive months / traded months:** `5 / 9`

The result fails the month-concentration rule. Removing the best month destroys most of the realized return.

### Symbol and Tail Concentration

- **Top symbol:** `MMTC`, `+3.71%`
- **Return excluding top symbol:** `+8.49%`
- **Return excluding top 3 symbols:** `+1.53%`
- **Symbols with only one trade:** `27 / 28`
- **Return excluding top 1 winning trade:** `+8.49%`
- **Return excluding top 3 winning trades:** `+1.53%`

The taken-trade set is diversified by symbol count, but the realized return is still too dependent on a small number of winners.

### Taken vs Skipped Validation

| Metric | Taken Trades | Skipped Trades |
|---|---:|---:|
| Count | `29` | `245` |
| Target WR | `31.03%` | `38.78%` |
| Positive-PnL WR | `44.83%` | `44.49%` |
| Average PnL | `+1.10%` | `+1.30%` |
| Median PnL | `-4.13%` | `-5.20%` |
| Average `conf_day_return` | `1.89%` | `1.39%` |
| Average Liquidity | `147.91 Cr` | `174.31 Cr` |

The ranking rule did not select better trades. The skipped trades had better target win rate and better average PnL. This fails the core ranking-validation rule.

### Verdict

`conf_day_return_desc` is rejected as a standalone ranking rule. The broader `Confirmed_Higher_Low` universe may still contain a real edge, but the `+30.46%` MTM result is not acceptable evidence for this ranking rule because:

- Much of the headline MTM return was unrealized at the data cutoff.
- Realized return collapses after removing the best month.
- Top winners dominate realized profit.
- Taken trades were not clearly better than skipped trades.

Next required step: audit `liquidity_t1_desc`, especially the 3-slot and 5-slot `Test_All_Confirmed_Higher_Low` rows, using the same anatomy framework. Liquidity ranking performed nearly as well in MTM and may be more stable because it is a market-microstructure filter rather than a price-action strength heuristic.

## 22. Trade Anatomy Audit: Liquidity Ranking Rejection

The next anatomy audit tested the 3-slot `Test_All_Confirmed_Higher_Low` portfolio ranked by `liquidity_t1_desc`. The MTM portfolio row looked strong:

- **MTM total return:** `+29.03%`
- **MTM max drawdown:** `20.43%`
- **Taken trades:** `41`
- **Skipped trades:** `236`

However, the anatomy audit rejected liquidity ranking as a standalone selection rule.

### MTM vs Realized Return Split

- **Final equity:** `129,026.78`
- **Final cash:** `41,987.86`
- **Final open position value:** `87,038.92`
- **Closed realized return:** `+12.21%`
- **Final open unrealized return contribution:** `+16.82%`
- **MTM total return:** `+29.03%`

As with the confirmation-momentum ranker, more than half of the headline MTM return was unrealized at the final candle date.

### Monthly Robustness

- **Best month:** `2026-04`, `+7.37%`
- **Return excluding best month:** `+4.84%`
- **Return excluding top 2 months:** `-1.58%`
- **Positive months / traded months:** `8 / 14`

The result again fails the top-month concentration check.

### Symbol Concentration

- **Top symbol:** `GODREJPROP`, `+7.36%`
- **Return excluding top symbol:** `+4.86%`
- **Return excluding top 3 symbols:** `-2.19%`
- **Symbols with only one trade:** `34 / 37`

The result is not concentrated by trade count, but realized return is highly dependent on a small number of winning symbols.

### Taken vs Skipped Validation

| Metric | Taken Trades | Skipped Trades |
|---|---:|---:|
| Count | `41` | `236` |
| Target WR | `34.15%` | `38.98%` |
| Positive-PnL WR | `41.46%` | `45.34%` |
| Average PnL | `+0.86%` | `+1.39%` |
| Median PnL | `-5.20%` | `-2.94%` |
| Average `conf_day_return` | `1.23%` | `1.48%` |
| Average Liquidity | `248.35 Cr` | `156.43 Cr` |

Liquidity ranking successfully selected more liquid trades, but those selected trades were worse than the skipped trades by target win rate, positive-PnL win rate, average PnL, and median PnL.

### Verdict

`liquidity_t1_desc` is rejected as a standalone ranking rule. It produced a strong MTM row, but the row does not prove ranking skill because:

- The selected trades underperformed the skipped trades.
- The headline return relied heavily on unrealized final MTM.
- Excluding the top 3 symbols turned realized return negative.
- Excluding the top 2 months turned realized return negative.

At this point, both tested capital-constrained ranking rules have failed anatomy:

- `conf_day_return_desc`: rejected.
- `liquidity_t1_desc`: rejected.

The remaining viable conclusion is that the broad `Confirmed_Higher_Low` universe has a trade-level edge, but no reliable capital-constrained pre-entry ranking rule has been proven yet.

## 23. V3 Ranking Features Audit

Five new T-1 compliant ranking variables were engineered in `v3_ranking_features.py` and written to `v3_ranked_events.csv`:

- `dist_to_support_asc`
- `conf_vol_expansion_desc`
- `relative_strength_desc`
- `reclaim_sma20_desc`
- `range_close_strength_desc`

The feature-generation bug involving SQLite parameter binding was corrected by casting SQLite instrument IDs to native Python `int`. After correction, the V3 features were available for most confirmed-higher-low events:

- `dist_to_support_asc`: `1,090 / 1,447` confirmed events; `270 / 279` Test confirmed events.
- Other V3 features: `1,429 / 1,447` confirmed events; `275 / 279` Test confirmed events.

The MTM simulator was then rerun using the V3-ranked event file.

### Best MTM Rows Before Anatomy

Several V3 rankers looked strong at the MTM portfolio level:

| Rule | Best Slots | MTM Return | MTM Max DD |
|---|---:|---:|---:|
| `range_close_strength_desc` | `3` | `+52.76%` | `12.95%` |
| `relative_strength_desc` | `5` | `+33.16%` | `15.40%` |
| `reclaim_sma20_desc` | `3` | `+30.45%` | `18.52%` |
| `conf_vol_expansion_desc` | `3` | `+26.33%` | `19.43%` |
| `dist_to_support_asc` | `5` | `+19.07%` | `19.24%` |

However, MTM strength alone is not a promotion gate. Each rule was audited using `v3_anatomy_auditor.py`, selecting the best MTM slot setting per rule and comparing taken trades against skipped trades.

### V3 Anatomy Summary

| Rule | Slots | MTM Return | Closed Realized | Open Unrealized | Taken Target WR | Skipped Target WR | Taken Avg PnL | Skipped Avg PnL | Ex Top 2 Months | Ex Top 3 Symbols |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `dist_to_support_asc` | `5` | `+19.07%` | `+5.90%` | `+13.17%` | `29.51%` | `40.76%` | `+0.37%` | `+1.60%` | `-8.69%` | `-0.67%` |
| `conf_vol_expansion_desc` | `3` | `+26.33%` | `+9.02%` | `+17.31%` | `31.03%` | `38.78%` | `+0.78%` | `+1.34%` | `+0.97%` | `-1.51%` |
| `relative_strength_desc` | `5` | `+33.16%` | `+16.79%` | `+16.37%` | `34.38%` | `39.42%` | `+1.14%` | `+1.38%` | `+1.05%` | `+9.81%` |
| `reclaim_sma20_desc` | `3` | `+30.45%` | `+12.20%` | `+18.25%` | `31.03%` | `38.78%` | `+1.10%` | `+1.30%` | `-1.52%` | `+1.53%` |
| `range_close_strength_desc` | `3` | `+52.76%` | `+19.15%` | `+33.61%` | `32.65%` | `39.38%` | `+1.01%` | `+1.37%` | `+1.42%` | `+7.20%` |

### Verdict

All five V3 ranking variables are rejected as standalone capital-constrained sorting rules.

The reason is not that every MTM curve was weak. Several MTM curves were strong. The rejection comes from the anatomy gate:

- Every V3 ranker selected trades with lower target win rate than the skipped trades.
- Every V3 ranker selected trades with lower average PnL than the skipped trades.
- A large portion of each headline MTM return came from open unrealized value at the final candle date.
- Most rankers were fragile after removing top months or top symbols.

The broad `Confirmed_Higher_Low` universe still has evidence of a trade-level edge, but V3 did not solve the capital-constrained selection problem.

### Next Steps

The strategy still lacks a reliable pre-entry ranking mechanism. To progress, we must either:

1. Engineer fundamentally different pre-entry variables, ideally involving sector breadth, sector relative strength, beta, or market-state context.
2. Expand historical candle coverage beyond the current candle-backed universe to increase opportunity breadth.
3. Relax capital constraints and accept that the base edge may require taking a wide basket of confirmed-higher-low trades during clusters.

## 24. Panic Basket Audit (Removing Ranking)

Following the failure of the V3 rankers, we tested Option 3: relaxing capital constraints and buying the entire basket of signals. The `panic_basket_mtm_simulator.py` was built to test if the raw structural edge survives without attempting to rank.

### Rules
- Allocates available cash equally across all new eligible signals on any given day.
- No limit on max slots (takes every trade).
- True daily MTM.

### Results
| Subset | Total Return | Closed Realized | Open Unrealized | Max DD | Max Open Pos |
|---|---:|---:|---:|---:|---:|
| `Test_Market_Panic_Confirmed` | `-5.24%` | `-7.20%` | `+1.96%` | `25.68%` | 26 |
| `Test_All_Confirmed_Higher_Low`| `+8.85%` | `-21.56%` | `+30.41%` | `24.58%` | 40 |

### Verdict
**FAILED.** The raw `Confirmed_Higher_Low` pattern is not portfolio-viable on its own.
When taking all trades, the portfolio's realized return plummets to deeply negative territory (-21.56%). This occurs because the base target win rate is ~39%, meaning 61% of signals result in stop-outs. Without a ranking rule to concentrate capital into the *best* signals, diluting capital across massive clusters of 61% losers bleeds the portfolio dry.

The "base edge" relies heavily on the average PnL being positive due to asymmetric wins. But in a capital-constrained, unranked portfolio, getting stuck in 40 simultaneous positions where 24 of them hit stop losses creates a massive drag that the remaining 16 winners fail to overcome realizedly.

### The True Next Step
With the Panic Basket failing, the structural pattern itself is proven insufficient without a powerful, fundamentally different pre-entry filter or a massive expansion of the data universe.

## 25. V4 Beta & Market State Audit

Testing the hypothesis that resilient stocks outperform during market panic clusters, we engineered 6 new Beta and Market-State variables over the prior 60 days up to the confirmation date. 

### Variables Tested
- `beta_60d_asc`: Prefer low-beta stocks
- `corr_60d_asc`: Prefer low correlation to the market
- `down_market_capture_60d_asc`: Prefer stocks that drop less than the market on down days
- `stock_vs_market_drawdown_resilience_desc`: Ratio of stock drawdown to market drawdown
- `market_breadth_at_confirmation_desc`: % of stocks above 50 SMA
- `breadth_recovery_5d_desc`: Change in breadth over 5 days prior

### Results (Best MTM Settings)

| Rule | Slots | MTM Return | Closed Realized | Taken WR | Skipped WR | Taken Avg PnL | Skipped Avg PnL | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `beta_60d_asc` | 3 | +26.07% | +9.04% | 31.03% | 38.78% | +0.78% | +1.34% | **REJECT** |
| `corr_60d_asc` | 5 | +36.07% | +22.26% | 34.85% | 39.13% | +1.48% | +1.25% | **REJECT** |
| `down_market_capture_60d_asc`| 5 | +41.62% | +28.66% | 37.84% | 38.00% | +1.63% | +1.15% | **REJECT** |
| `drawdown_resilience_desc` | 5 | +12.85% | +0.61% | 25.37% | 42.23% | -0.06% | +1.74% | **REJECT** |
| `market_breadth_desc` | 5 | +20.32% | +10.61% | 31.43% | 40.39% | +0.64% | +1.53% | **REJECT** |
| `breadth_recovery_desc` | 5 | +20.32% | +10.61% | 31.43% | 40.39% | +0.64% | +1.53% | **REJECT** |

### Verdict
**NOT PROMOTED, BUT NOT DEAD.** All 6 V4 rankers failed the original strict promotion rule because none clearly beat the skipped trades on Target Win Rate. However, V4 is materially different from the earlier V3 failures.

`down_market_capture_60d_asc` is a borderline candidate:

- **Taken Target WR:** `37.84%`
- **Skipped Target WR:** `38.00%`
- **Taken Positive-PnL WR:** `48.65%`
- **Skipped Positive-PnL WR:** `43.00%`
- **Taken Avg PnL:** `+1.63%`
- **Skipped Avg PnL:** `+1.15%`
- **Closed Realized Return:** `+28.66%`
- **Open Unrealized Return:** `+12.95%`
- **Return excluding top 2 months:** `+12.50%`
- **Return excluding top 3 symbols:** `+18.67%`

Unlike the V3 rankers, this did not merely win from final-day open MTM or one concentrated symbol/month. It failed the target-WR gate by only `0.16 percentage points`, while improving positive-PnL rate, average PnL, realized return, and concentration robustness.

`corr_60d_asc` also deserves caution rather than immediate disposal:

- **Taken Avg PnL:** `+1.48%`
- **Skipped Avg PnL:** `+1.25%`
- **Closed Realized Return:** `+22.26%`
- **Return excluding top 2 months:** `+10.74%`
- **Return excluding top 3 symbols:** `+13.11%`

The correct conclusion is therefore: no V4 ranker is deployable yet, but downside capture and low correlation are the first ranking families that show real expectancy improvement rather than pure MTM illusion.

### Next Steps

Do not jump directly to a 9,000-symbol data fetch yet. The next research step should be a **V4b robustness audit** focused on downside capture and correlation:

1. Test lookback sensitivity: `40d`, `60d`, `90d`, `120d`.
2. Compare ranking directions: ascending vs descending.
3. Compare promotion gates based on expectancy and positive-PnL WR, not only target WR, because this strategy has asymmetric +10%/-5% exits and timeouts.
4. Run Monte Carlo random-selection baselines against the same cluster sizes.
5. Recompute results excluding open positions at the final data date, or force-close all open trades at the final available close and report that separately.
6. Re-run concentration tests after removing top month, top 2 months, top symbol, and top 3 symbols.

Only if V4b fails should the research move to the expensive full-universe candle expansion.

## 26. V4b Robustness Audit

V4b focused only on the first V4 families that showed real expectancy improvement:

- `corr`
- `down_market_capture`

Both were tested across `40d`, `60d`, `90d`, and `120d` lookbacks, in both ascending and descending directions. The audit used the same `Test_All_Confirmed_Higher_Low` liquid event set and compared every ranker against a same-slot `random_100_avg` Monte Carlo baseline.

Open trades at the final data date were force-closed at their last available MTM close and included in trade statistics. This removed the prior open-MTM illusion from WR and average-PnL metrics.

### Best-Rule Summary

| Rule | Slots | Return | Return Edge | Positive-PnL WR Edge | Avg PnL Edge | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `corr_40d_asc` | `5` | `+28.59%` | `+5.42%` | `+2.85%` | `+0.35%` | PASS |
| `down_market_capture_40d_asc` | `5` | `+33.29%` | `+10.12%` | `+3.17%` | `+0.44%` | PASS |
| `corr_60d_asc` | `5` | `+36.07%` | `+12.90%` | `+7.02%` | `+0.80%` | PASS |
| `down_market_capture_60d_asc` | `5` | `+41.62%` | `+18.45%` | `+6.37%` | `+0.87%` | PASS |
| `corr_90d_asc` | `5` | `+33.32%` | `+10.15%` | `+5.59%` | `+0.64%` | PASS |
| `down_market_capture_90d_asc` | `5` | `+30.70%` | `+7.53%` | `+2.47%` | `+0.34%` | PASS |
| `corr_120d_asc` | `5` | `+29.72%` | `+6.55%` | `+4.24%` | `+0.39%` | PASS |
| `down_market_capture_120d_asc` | `5` | `+32.63%` | `+9.46%` | `+3.77%` | `+0.42%` | PASS |

The clearest finding is not one isolated row. It is the family pattern:

- 5-slot `corr_asc` passed across all tested lookbacks.
- 5-slot `down_market_capture_asc` passed across all tested lookbacks.
- 10-slot versions often passed but with weaker return.
- 3-slot versions were unstable and often failed concentration removal.
- Descending directions were inconsistent and should not be promoted as the core thesis.

### Strongest Candidate

`down_market_capture_60d_asc`, 5 slots:

- **Total force-closed return:** `+41.62%`
- **Random baseline return:** `+23.17%`
- **Return edge:** `+18.45%`
- **Positive-PnL WR edge:** `+6.37%`
- **Avg PnL edge:** `+0.87%`
- **Closed before final date:** `+28.66%`
- **Force-closed final-open PnL:** `+12.95%`
- **Return excluding top 2 months:** `+16.74%`
- **Return excluding top 3 symbols:** `+14.35%`

This is the first ranking family that passed the corrected anatomy gates without relying only on final-day open MTM or one concentrated symbol/month.

### Correct Interpretation

V4b does not yet prove deployability. The audit still used the Test split to compare many configurations, so there is multiple-comparison and post-hoc selection risk.

However, V4b materially changes the research state. The downside-capture and low-correlation ascending families are no longer simple mirages. They show stable, repeated improvement over same-slot Monte Carlo random selection across multiple lookbacks.

The strategy should now be treated as a **research candidate family**:

> Buy confirmed-higher-low crash reversals, but when signals cluster, prefer stocks with low prior market correlation and low downside capture over the preceding 40-120 trading days.

### Required Next Step

Before any deployment claim, freeze one simple rule without further tuning:

- Candidate: `down_market_capture_60d_asc`
- Slots: `5`
- Subset: `Test_All_Confirmed_Higher_Low`
- Execution: unchanged V2/V4b MTM engine

Then run a final locked-rule audit:

1. Reproduce exact event list and portfolio curve.
2. Export taken/skipped trades with ranking values.
3. Run month, symbol, entry-date, and force-close anatomy.
4. Compare against 1,000-run random Monte Carlo, not 100-run.
5. Report confidence intervals for random baseline return, average PnL, and positive-PnL WR.
6. Do not choose a new slot count or lookback after seeing the result.

Only after this locked-rule audit passes should the research move from candidate discovery to implementation planning.

## 27. V5 Locked-Rule Audit

The V5 audit froze the strongest V4b candidate before running the final statistical baseline:

- Rule: `down_market_capture_60d_asc`
- Slots: `5`
- Subset: `Test_All_Confirmed_Higher_Low`
- Eligible events: `279`
- Events without the 60-day downside-capture feature: `4`
- Monte Carlo baseline: `1,000` random same-slot portfolio simulations
- Open-position treatment: force-close remaining trades at the final available MTM close

This audit did not reselect the best lookback, slot count, or direction after seeing the result. It tested the locked rule exactly as chosen from V4b.

### Locked Rule Metrics

| Metric | Value |
|---|---:|
| Total force-closed return | `+41.62%` |
| Closed before final return | `+28.66%` |
| Force-closed final-open return | `+12.95%` |
| Avg PnL per trade | `+2.24%` |
| Positive-PnL WR | `49.35%` |
| Trades taken | `77` |
| Force-closed trades | `3` |
| MTM max drawdown | `12.02%` |
| Max cluster size | `21` |
| Worst cluster date | `2026-04-07` |

### 1,000-Run Monte Carlo Confidence

| Metric | Locked | MC p05 | MC median | MC p95 | Percentile | One-Sided p-value |
|---|---:|---:|---:|---:|---:|---:|
| Total Return | `+41.62%` | `+13.20%` | `+23.52%` | `+35.55%` | `99.10%` | `0.0100` |
| Avg PnL | `+2.24%` | `+0.78%` | `+1.40%` | `+2.05%` | `98.10%` | `0.0200` |
| Positive-PnL WR | `49.35%` | `38.36%` | `43.24%` | `48.00%` | `98.30%` | `0.0180` |

### V5 Verdict

The locked rule passed the promotion gate:

- Total return was above the 95th percentile of random portfolios.
- Average PnL was above the 95th percentile of random portfolios.
- Positive-PnL WR was above the 95th percentile of random portfolios.

Therefore, `down_market_capture_60d_asc` with `5` slots should be promoted to the next validation phase.

This still is not a live-deployable strategy. It remains a research result on the current candle-backed universe. The next phase should test implementation realism and robustness:

1. Add estimated costs, slippage, and liquidity-adjusted fill assumptions.
2. Run the same locked rule across expanded candle coverage if data becomes available.
3. Add a no-retuning holdout or paper-trading forward log.
4. Preserve the exact V5 rule unless a new research phase explicitly starts.

## 28. V6 Friction Sensitivity Audit

The corrected V6 audit tested whether the statistically significant V5 edge could survive realistic execution friction and liquidity caps. It compared the same locked rule against a 1,000-run Monte Carlo random baseline under three increasingly punitive scenarios.

The locked rule remained unchanged:

- Rule: `down_market_capture_60d_asc`
- Slots: `5`
- Subset: `Test_All_Confirmed_Higher_Low`
- Trade count: `77`
- Skipped events: `200`
- Equity curve rows per scenario: `300`
- Monte Carlo rows per scenario: `1,000`

### Friction Scenarios

| Scenario | Friction / Side | Max Position vs ADTV |
|---|---:|---:|
| **Base** | `0.25%` | `1.00%` |
| **Conservative** | `0.35%` | `0.75%` |
| **Harsh** | `0.50%` | `0.50%` |

Entry and exit prices were adjusted pessimistically:

- Effective entry price = raw entry price * `(1 + friction_per_side)`
- Effective exit price = raw exit price * `(1 - friction_per_side)`

The audit verified zero entry-friction formula violations, zero exit-friction formula violations, and zero liquidity-cap violations in all three scenarios.

### Return Results

| Scenario | Locked Return | MC p05 | MC Median | MC p95 | Percentile | p-value | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Base | `+31.22%` | `+5.39%` | `+14.92%` | `+26.08%` | `99.00%` | `0.0110` | `12.69%` |
| Conservative | `+27.28%` | `+2.45%` | `+11.70%` | `+22.55%` | `98.90%` | `0.0120` | `13.19%` |
| Harsh | `+21.60%` | `-1.81%` | `+7.03%` | `+17.16%` | `98.70%` | `0.0140` | `16.10%` |

### Trade-Quality Results

| Scenario | Locked Avg PnL | MC Avg PnL p95 | Avg PnL p-value | Locked Pos WR | MC Pos WR p95 | Pos WR p-value |
|---|---:|---:|---:|---:|---:|---:|
| Base | `+1.92%` | `+1.73%` | `0.0200` | `49.35%` | `48.00%` | `0.0180` |
| Conservative | `+1.72%` | `+1.53%` | `0.0200` | `49.35%` | `48.00%` | `0.0180` |
| Harsh | `+1.41%` | `+1.22%` | `0.0200` | `48.05%` | `46.58%` | `0.0150` |

### V6 Verdict

**PASS**. The edge survived the corrected friction audit.

Even under the Harsh scenario, which assumes `0.50%` friction per side and caps position size at `0.50%` of 20-day ADTV, the locked rule remained above the 95th percentile of the same-friction Monte Carlo baseline on all three required metrics:

- Total return
- Average PnL
- Positive-PnL WR

The harsh-case result was `+21.60%` versus a random median of `+7.03%`, with return p-value `0.0140`, average-PnL p-value `0.0200`, and positive-PnL WR p-value `0.0150`.

This does not make the strategy live-deployable. It means V6 no longer falsifies the candidate. The next clean research step is data expansion or forward paper logging using the exact same locked V6 rule, without retuning the lookback, slot count, ranking direction, exit model, or friction assumptions.

## Section 29: V7 Forward Paper Logging

With the strict strategy boundary drawn around the Nifty 500 and the edge empirically validated in V6, the final phase before live capital deployment is **Forward Paper Logging**.

`v7_forward_paper_logger.py` is the first paper-logging engine for the locked V6 rule.

### Strict Execution Rules
1. **Pending Entries:** The logger does not assume the open price of a new signal is tradable on the same day. If a stock confirms a structural setup on Day T, it issues a `PENDING_ENTRY` order. 
2. **Next-Day Fill:** On Day T+1, the logger fills the pending order using the *actual* Open price of Day T+1, accurately reflecting overnight gaps.
3. **Execution Friction:** Every fill instantly applies the Base V6 friction (0.25% per side) to the equity balance. Harsh friction (0.50%) is tracked redundantly for stress-testing.
4. **Liquidity Constraints:** Position sizing is strictly capped at `1.0%` of the 20-day Average Daily Traded Value up to Day T.
5. **No Retuning:** The strategy rules (`down_market_capture_60d_asc`, 5 slots, strict V2 exit logic) are completely locked.
6. **Raw Trigger / Friction PnL Separation:** Stop and target triggers remain based on the raw next-open V2 levels. Friction is applied only to execution prices and PnL, matching the V6 audit convention.

### State Files

The logger uses local paper-state files:

- `forward_paper_portfolio.json`
- `forward_paper_trade_ledger.csv`
- `forward_paper_daily_log.csv`

The script also supports a `--log-dir` override so historical replay tests do not pollute the live paper state.

### Audit Validation

The V7 engine includes a `--as-of-date` replay mode. A scratch replay over `2025-04-30` through `2025-05-06` verified:

- `SOBHA` was generated as a pending order on `2025-04-30`.
- The order waited through the missing/non-trading `2025-05-01` session.
- `SOBHA` filled on `2025-05-02` at the actual open with Base V6 friction.
- `SOBHA` exited on `2025-05-06` at the same effective stop exit price used by the V6 audit: `1255.51335`.
- `SHRIRAMFIN` was generated from the `2025-05-05` confirmation and filled on `2025-05-06`.

### Current Status

The V7 logger has been run for the latest cached confirmation date in the research artifacts (`2026-06-08`), identifying two valid pending signals:

- `CARTRADE`
- `ENGINERSIN`

These orders are pending execution for the next available trading day's open.

### Important Limitation

V7 currently reads eligible new signals from `v4b_ranked_events.csv`. That is acceptable for replay and for managing the current cached research endpoint, but it is not yet a self-contained live state miner.

If fresh daily candles are added after the max cached `confirmation_date`, V7 can still manage existing pending/open positions, but it will not discover brand-new confirmations unless either:

1. The V2/V4b event artifacts are regenerated before the paper-log run, or
2. A V7b live state miner is added to compute today's `Confirmed_Higher_Low` events directly from SQLite candles.

Therefore, V7 is **paper-log infrastructure**, not a fully autonomous live scanner yet.

## Section 30: Matsya API Bridge Discovery

The forward logger should not connect directly to Matsya PostgreSQL tables. The server-side Matsya branch already exposes a read-only market-data API over HTTP.

Discovered API contract:

- App: `app.matsya_api:app`
- Default deployment port: `8020`
- Route prefix: `/api/matsya`
- Health: `GET /api/matsya/health`
- Market data status: `GET /api/matsya/market-data/status`
- Nifty 500 symbols: `GET /api/matsya/market-data/symbols?universe=NIFTY_500&limit=50&offset=0`
- Historical OHLCV: `GET /api/matsya/market-data/ohlcv?symbol=RELIANCE&from=2026-01-01&to=2026-06-23&limit=250&order=asc`
- Latest OHLCV: `GET /api/matsya/market-data/ohlcv/latest?symbol=RELIANCE&days=365`
- Validation: `GET /api/matsya/market-data/validation`

The API responses expose normalized instruments, universe membership, OHLCV candles, and safe validation summaries. They intentionally do not expose Dhan tokens, encrypted token values, raw secrets, or database URLs.

A read-only probe script was added:

```bash
python backend/app/scripts/v7_matsya_api_probe.py --base-url http://127.0.0.1:8020 --symbol RELIANCE --days 5
```

Connection was later verified successfully from this local machine:

```bash
python backend/app/scripts/v7_matsya_api_probe.py --base-url http://100.76.218.124:8020 --symbol RELIANCE --days 5 --timeout 30
```

Verified server response:

- Health: `{"status": "ok", "app": "matsya-api"}`
- Latest candle date: `2026-06-30`
- Symbols with candles: `500`
- OHLCV rows: `556444`
- Duplicate count: `0`
- Null OHLCV count: `0`
- Bad OHLC count: `0`
- Sample symbol: `RELIANCE`
- Sample latest candle: `2026-06-30`, open `1306.9`, high `1306.9`, low `1290.0`, close `1293.9`, volume `15695263`
- Token state: initially `renew_failed`, later verified `active`

Token recheck after renewal:

- Token state: `active`
- Data plan: `Active`
- Data validity: `2026-07-16 13:34:22.0`
- Token expiry time: `2026-07-03T17:19:00Z`
- Last status check: `2026-07-02T17:19:52.040191Z`

The API is now healthy for both read-only access and future ingestion, subject to the normal Matsya worker schedule. As of the latest check, stored candle coverage still ends on `2026-06-30`.

### V7b Requirement

The API probe now passes. V7b can replace the `v4b_ranked_events.csv` dependency with live OHLCV reads from Matsya. The remaining operational check is whether the Matsya worker has ingested candles beyond `2026-06-30` before each paper-log run.

## Section 31: V7b Matsya-Backed Forward Logger

`v7b_matsya_forward_paper_logger.py` replaces V7's static `v4b_ranked_events.csv` signal source with live read-only OHLCV pulls from the Matsya API.

### Data Source

V7b consumes only these Matsya API endpoints:

- `GET /api/matsya/market-data/status`
- `GET /api/matsya/market-data/symbols?universe=NIFTY_500&limit=5000&offset=0`
- `GET /api/matsya/market-data/ohlcv/latest?symbol={symbol}&days=420`

It does not connect directly to Matsya PostgreSQL and does not call Dhan directly.

Important implementation correction: V7b fetches OHLCV using the `security_id` returned by the Nifty 500 symbols endpoint, not the symbol text alone. This avoids ambiguous symbol resolution. For example, `CHOLAFIN` and `MOTHERSON` initially returned empty candles when queried by symbol, because the OHLCV endpoint resolved them to non-universe security IDs. Querying by the universe security IDs (`685` and `4204`) returned valid candles.

### Signal Mining Logic

For every Nifty 500 symbol loaded from Matsya, V7b rebuilds the locked V2/V4b logic locally:

1. Compute the V2 crash state using the shifted 250-day low, 20-day high, 50-day SMA, 5-day low, and 15% crash threshold.
2. Scan forward with the frozen break-on-new-low higher-low logic.
3. Select only events where `confirmation_date == as_of_date`.
4. Apply the liquidity gate: 20-day ADTV greater than `10,000,000`.
5. Recompute `down_market_capture_60d` from the live Matsya candle set and live equal-weight market return series.
6. Rank ascending by `down_market_capture_60d`.
7. Create pending orders for the top available slots, max `5`.

For historical replay, V7b explicitly truncates all fetched candles to `trading_date <= as_of_date` before computing signals. This prevents future candles from leaking into replay tests.

### Execution Logic

V7b preserves the V7/V6 execution model:

- Signal on Day T creates `PENDING_ENTRY`.
- Fill occurs only when the next available candle exists.
- Entry uses actual open with Base V6 friction.
- Stop/target triggers use raw V2 levels.
- PnL applies Base V6 friction.
- Harsh friction shadow PnL is also tracked.
- State is stored in a separate Matsya-backed log folder by default: `D:\app\data\exports\forward_paper_log_matsya`.

### Replay Verification

V7b was tested against the known cached signal date `2026-06-08` using the live Matsya API.

Result:

- Eligible signals: `2`
- New pending orders: `CARTRADE`, `ENGINERSIN`
- Rank order: `CARTRADE` first, `ENGINERSIN` second
- This matches the V7 cached-artifact signal set.

The recomputed live downside-capture values were:

| Symbol | down_market_capture_60d | Liquidity Cap |
|---|---:|---:|
| `CARTRADE` | `0.5722072035679696` | `12877137.131349998` |
| `ENGINERSIN` | `1.4125824167804373` | `11177636.840115` |

The values differ slightly from the older cached `v4b_ranked_events.csv` values because V7b recomputes the equal-weight market return series from the live Matsya API candle set instead of reading the frozen research export. The selected symbols and rank order still matched.

### Latest API Run

A scratch run against the latest Matsya candle date initially produced:

- As-of date: `2026-06-30`
- Eligible signals: `0`
- Pending orders: `0`
- Open positions: `0`
- Failed symbol fetches: `2`

The failed symbols were `CHOLAFIN` and `MOTHERSON`; this led to the security-id lookup fix above.

After the fix, the official Matsya-backed paper run for `2026-07-01` produced:

- Matsya token state: `active`
- Matsya latest candle date: `2026-07-01`
- Symbols requested: `500`
- Symbols loaded: `500`
- Fetch failures: `0`
- Eligible signals: `0`
- New pending orders: `0`

V7b records fetch failures to `forward_paper_fetch_failures.json`. Any nonzero fetch failure count must be reviewed before trusting a daily no-signal result.

### V7b Verdict

V7b resolves the main V7 limitation. The forward logger is no longer dependent on static research event exports for new signal discovery.

The remaining operational requirement is daily health discipline:

1. Confirm Matsya token state is `active`.
2. Confirm `latest_candle_date` matches the expected latest trading session.
3. Confirm `fetch_failures == 0`, or inspect missing symbols before accepting the signal list.
4. Run V7b after market data ingestion is complete.

## Section 32: V8 Server Demo Trader

V8 converts the locked V7b paper logger into a server-runnable demo trading service with a clean broker boundary.

The goal is not to place real orders yet. The goal is to run the exact strategy in a persistent virtual account so the next 60-90 trading days create a real forward performance record.

### Architecture Boundary

V8 separates three concerns:

1. **Data Source:** Matsya read-only OHLCV API.
2. **Strategy Engine:** Locked `Confirmed_Higher_Low` + `down_market_capture_60d_asc` + 5-slot selection.
3. **Broker Adapter:** Paper broker now; future Dhan broker later.

The paper broker is implemented in `v8_demo_trader.py`. A `--broker dhan` mode exists only as an intentional disabled stub. It raises an error until live trading is explicitly approved after paper validation.

This means a future real broker adapter can be added behind the same interface without changing the strategy logic.

### Locked V8 Rules

- Universe: Matsya `NIFTY_500`
- OHLCV lookup: Matsya `security_id`, not symbol text
- Structure: `Confirmed_Higher_Low`
- Ranker: `down_market_capture_60d_asc`
- Slots: `5`
- Friction: Base V6, `0.25%` per side
- Health gate: token active, 500 symbols loaded, 0 fetch failures
- Broker mode: `paper`

### V8 Verification

A scratch run against the live Matsya API passed strict health:

- Date: `2026-07-01`
- Broker: `paper`
- Equity: `100000.00`
- Matsya token state: `active`
- Symbols loaded: `500`
- Fetch failures: `0`
- Eligible signals: `0`
- Orders placed: `0`

### Server Deployment Files

Added deployment helpers under `deploy/v8-demo-trader/`:

- `README.md`
- `v8-demo-trader.service`
- `v8-demo-trader.timer`

The timer is configured to run after market ingestion time. On the server it should point at the server-local Matsya API:

```bash
python backend/app/scripts/v8_demo_trader.py \
  --base-url http://127.0.0.1:8020 \
  --output-dir /home/hacker/apps/v8-demo-trader/state \
  --strict-health
```

### V8 Verdict

The research phase is complete and the operational demo phase can begin.

No live Dhan order placement should be implemented until the paper broker has produced a clean forward record and the promotion criteria are explicitly approved.

## Section 33: V8 Frontend Demo Dashboard

The V8 demo trader now has a read-only frontend dashboard path.

### Backend Endpoint

Added `V8DemoReportService` and a read-only API endpoint:

```text
GET /api/demo/v8/status?limit=100
```

The endpoint reads V8 output artifacts from:

```text
D:\app\data\exports\v8_demo_trader
```

Returned data includes:

- Latest daily report
- Paper broker account cash
- Pending orders
- Open positions
- Closed trades
- Order ledger
- Signals
- Daily report history
- Fetch failures
- Output file metadata

The endpoint is display-only. It does not run the strategy, place orders, mutate state, or connect to Dhan.

### Frontend

Added a new frontend tab:

```text
Demo Trader
```

The dashboard displays:

- Paper account equity, cash, open value, open positions, and pending orders
- Matsya health gate: token state, latest candle date, symbols loaded, fetch failures
- Pending orders table
- Open positions table
- Closed trades table
- Latest signals table
- Daily report table
- V8 output artifact status
- Fetch failure details

### Verification

The frontend production build passed:

```text
npm run build
```

The V8 report reader successfully parsed the current V8 output:

- Date: `2026-07-01`
- Broker: `paper`
- Equity: `100000.0`
- Cash: `100000.0`
- Open positions: `0`
- Pending orders: `0`
- Eligible signals: `0`
- Symbols loaded: `500`
- Fetch failures: `0`

### Startup Compatibility Fix

The local FastAPI route check initially exposed legacy SQLite schema drift in the historical data tables:

- `historical_fetch_items.status` was missing before an index attempted to use it.
- `daily_candles.security_id` was missing before the `daily_candles(security_id, trading_date)` index attempted to use it.

The startup migration guard in `backend/app/historical_data.py` now adds those missing columns before index creation. This is an infrastructure-only fix; it does not alter the strategy, ranking rules, broker adapter, paper ledger, or V8 execution logic.

### Route Verification

The V8 dashboard endpoint now passes route-level FastAPI verification:

```text
GET /api/demo/v8/status?limit=5 -> 200
```

Verified payload summary:

- Date: `2026-07-01`
- Broker: `paper`
- Equity: `100000.0`
- Cash: `100000.0`
- Open positions: `0`
- Pending orders: `0`
- Eligible signals: `0`
- Matsya token state: `active`
- Symbols loaded: `500`
- Fetch failures: `0`

### Server Matsya Dashboard Deployment

The first dashboard implementation landed in the main local frontend, but the live URL `http://100.76.218.124:5190/` is served by the separate `frontend-matsya` container and the `8020` API is served by `app.matsya_api:app`. The server deployment was therefore patched directly in the Matsya stack:

- Added `GET /api/matsya/demo/v8/status` to the Matsya API.
- Added a read-only V8 report reader under `backend/app/matsya/v8_demo_report.py`.
- Added a V8 Demo Trader panel to `frontend-matsya/src/main.tsx`.
- Mounted `../../data/v8_demo_trader` into the API container as `/app/data/v8_demo_trader:ro`.
- Rebuilt and restarted `matsya-api` and `matsya-ui`.

External verification passed:

```text
http://100.76.218.124:8020/api/matsya/demo/v8/status?limit=5 -> 200
http://100.76.218.124:5190/ -> bundle contains "V8 Demo Trader"
```

The server dashboard is still read-only and remains paper-only. It displays broker state and report files; it does not run the strategy or place live broker orders.

### Server Autonomy Upgrade

The V8 paper trader is now installed on the server, not dependent on the local laptop:

- Copied V8 scripts into the server backend image context under `backend/scripts/`.
- Added a Docker Compose one-shot service: `v8-demo-trader`.
- The service runs the locked paper strategy only:

```text
python scripts/run_v8_demo_trader_once.py
```

- The wrapper checks Matsya's latest candle date and skips if that date was already processed, preventing duplicate paper orders/reports on repeated runs.
- Output is written to:

```text
/home/hacker/apps/swing-trading-app/data/v8_demo_trader
```

- The Matsya API dashboard reads the same directory through `/app/data/v8_demo_trader`.
- The `hacker` user crontab now runs the service automatically:

```text
30 7 * * 1-6 cd /home/hacker/apps/swing-trading-app/deploy/matsya-setup && /usr/bin/docker compose --profile manual run --rm v8-demo-trader >> /home/hacker/apps/swing-trading-app/data/v8_demo_trader/v8_demo_trader_cron.log 2>&1
```

Manual server-side proof run completed:

```text
[2026-07-02] broker=paper equity=100000.00 open=0 pending=0 closed=0 signals=0 placed=[]
```

The dashboard endpoint now reports the server-generated latest state:

- Date: `2026-07-02`
- Broker: `paper`
- Equity: `100000.0`
- Matsya latest candle date: `2026-07-02`
- Matsya token state: `active`
- Symbols loaded: `500`
- Fetch failures: `0`

The live-order path remains disabled. This is still a paper-only autonomous demo runner.

## Section 34: Sideways Breakout Candidate (Discovery)

While the V8 crash-reversal demo trader runs autonomously on the server, a new parallel research track was opened to investigate sideways breakouts. 

### The Hypothesis
Instead of buying falling knives, can we find an edge by buying breakouts from tight consolidation bases?

### Discovery Scan Rules
A leakage-safe historical scan was built in `find_historical_sideways_10pct.py` to identify historical candidates. To prevent V1-style lookahead bias, the rules were strict from day one:
- **Universe**: NIFTY 500 (Current Universe - introduces survivorship bias, acceptable for initial discovery but not final backtesting).
- **Base**: The prior 30 completed candles (excluding the breakout day) must have a high-low range `<= 6%`.
- **Breakout**: The current close must be `>= base_high * 1.005`.
- **Volume & Liquidity**: Breakout volume `>= 1.5x` the 20-day average volume, and 20-day ADTV (Average Daily Traded Value) `>= 10,000,000` INR.
- **Entry**: Strict next-day open.
- **Exit Logic**: +10% target, using the `base_low` as the stop-loss level, with a 40-day timeout.
- **Pessimism**: If both target and stop are touched on the same day, the trade is counted as a STOP loss.
- **Deduplication**: Enforced a 15-trading-session deduplication window between setups on the same symbol, and strict 40-day forward window existence for MFE/MAE scoring.

### Results (2021 - 2026)
Out of 554,802 loaded NIFTY 500 candles, the scan found exactly **40 candidates**.

The outcomes over the next 40 days (using `base_low` as the strict stop level) were:
- **WIN_10PCT**: 11 (27.5%)
- **STOPPED_BEFORE_TARGET**: 11 (27.5%)
- **TIMEOUT**: 18 (45.0%)

*Pure MFE vs Strategy Effect:*
- **Touched 10% (Pure MFE)**: 12
- **Strategy Win**: 11

The strict pessimistic logic correctly demoted one trade that touched 10% but hit the `base_low` stop on the same day.

### Verdict
The sideways breakout candidate is **NOT** a high-win-rate holy grail. The target win rate was only `27.5%`, with timeouts representing the largest outcome category (`45.0%`).

However, this is only the first raw discovery pass. The `base_low` stop often creates extremely tight stop percentages when the base range is `<= 6%`. The script was refactored to export `max_return`, `max_drawdown`, `target_hit_date`, and `days_to_target` to `sideways_breakouts_10pct.csv`. The next research step should analyze these candidates to calculate the actual Expectancy (Avg PnL), evaluate if the timeout duration needs adjustment, or test alternative trailing stops using the rigorous MFE/MAE tracking.

## Section 35: Sideways Breakout Robustness Sweep (In-Sample)

To find a stable parameter zone, a full sweep was executed across 180 grid combinations of `base_duration`, `base_range`, `stop_variant`, and `round_trip_friction`. This required rewriting the evaluation logic using optimized NumPy vectorization (`sweep_sideways_expectancy.py`) to process 550,000 candles in under 90 seconds.

### In-Sample Findings
The matrix generation revealed that the 6% base was too restrictive and produced a small, lower-performing sample. The leading in-sample candidate zone centers around:
- **Base Duration:** 30 trading sessions
- **Base Range:** 8-10% 

For a 30-session, 8% base (with a strict `max_8pct_stop` and a harsh `0.50%` round-trip friction), the strategy generated:
- **Candidates:** 276
- **Win Rate:** ~40.9%
- **Expectancy:** 1.34% per trade

### Important Caveat

The current in-sample evidence points to 30-session sideways breakouts with 8-10% base ranges as the leading candidate zone. The best audited slice so far is 30 sessions / 8% range / max 8% stop / 0.50% friction, with 276 evaluated trades, ~41% win rate, and ~1.34% average realized PnL. This is promising, but not proven until it survives chronological validation and concentration audits.

> [!WARNING]
> This sweep was run on the *current* NIFTY 500 universe (which includes survivorship bias). It does NOT prove a statistically robust edge on its own. The candidate zone deserves promotion to the next stage, but it must pass chronological out-of-sample validation, walk-forward testing, and symbol/month concentration checks before it can be considered a valid trading edge.

## Section 36: Fragility and Concentration Audit (In-Sample)

To ensure the 30-session, 8% range candidate zone was not a statistical fluke driven by a single month or symbol, a full-trades fragility audit was performed on the `sweep_robustness_trades.csv` data (`audit_sideways_concentration.py`).

**Target Slice Evaluated:** 
- Base Duration: 30 sessions
- Base Range: 8%
- Stop Variant: `max_8pct_stop`
- Friction: `0.50%` round-trip
- Total Trades: 276
- Total Expectancy: `+1.34%` per trade

### Key Audit Metrics
1. **Symbol Broadness:** The 276 trades were spread across **147 unique symbols**.
2. **Profitable Symbols:** 93 of those 147 symbols (63.3%) generated a positive net PnL.
3. **Symbol Concentration:** The top 5 symbols by PnL (IOC, COALINDIA, MARUTI, JSWDULUX, COLPAL) contributed only **37.3%** of the total PnL.
4. **Symbol Fragility:** Removing the single best symbol (IOC) barely moved the expectancy (dropped from 1.34% to 1.22%). Removing the top 3 best symbols kept expectancy at a healthy **1.07%**.
5. **Temporal Fragility:** Removing the single most profitable month (May 2023) dropped expectancy to **0.98%**. Removing the two best months still left a positive expectancy of **0.64%**.
6. **Regime Distribution:** Median monthly expectancy across all active months remained positive at **0.50%**.

### Verdict: PROMOTABLE TO WALK-FORWARD
The edge survived the fragility and concentration audits. The profitability is not an illusion created by a single localized market event or a handful of momentum stocks. 

However, there are important **caution flags**:
- 2023 contributes the vast majority of the net PnL (+3.213 out of +3.701).
- 2024 and the 2026 slice were both negative expectancy years (-2.46% and -2.70%).
- Only 25 out of 47 active months were profitable.

Because the edge is not evenly distributed across all years, it cannot be promoted as a validated strategy yet. It is explicitly **promoted to walk-forward validation** where it must prove it can survive chronological out-of-sample data.

## Section 37: Chronological Out-of-Sample Validation

To definitively test whether the 30-session, 8% range candidate was a robust market edge or an artifact of the 2023 bull market, a strict fixed-parameter chronological split was performed (`test_chronological_split.py`).

The fixed candidate (`30 duration / 0.08 range / max_8pct_stop / 0.50% friction`) was tested across two distinct time buckets:
- **Train/Discovery Window**: 2021-06-17 to 2023-12-31
- **Blind Test Window**: 2024-01-01 to 2026-06-17

### Results
**Train/Discovery (2021-2023)**
- Trades: 156
- Win Rate: 47.44%
- Total PnL: +3.9917
- Expectancy: **+2.56%**

**Blind Test (2024-2026)**
- Trades: 120
- Win Rate: 32.50%
- Total PnL: -0.2903
- Expectancy: **-0.24%**

### Verdict: FAILED OUT-OF-SAMPLE
The fixed 30/8 setup failed the 2024-2026 blind test and is rejected as a standalone backtest champion. The in-sample edge was materially dependent on the 2021-2023 discovery window, especially 2023, and did not generalize across the full blind period.

### 37.1 Blind Grid Diagnostic
Before moving to dynamic rolling optimization or abandoning the setup, a strict diagnostic (`test_blind_grid_survival.py`) was run over the 2024-2026 blind period to see if *any* of the 180 parameter combinations survived naturally. 

**Criteria for Survival in Blind Period:**
- Trade count >= 100
- Expectancy > 0
- Profit Factor > 1
- Profitable months >= 50%
- Unique symbols >= 30

**Findings:**
Out of 180 grid combinations, **7 survived** the diagnostic blind test. 

Fascinatingly, the top 5 surviving setups were all exactly **30-session duration and 8% base range**. 

```text
base_duration  base_range    stop_variant  round_trip_friction  trade_count  expectancy  profit_factor
30             0.08  max_10pct_stop               0.0015          120    +0.53%       1.15
30             0.08   base_low_stop               0.0015          120    +0.50%       1.14
30             0.08  max_10pct_stop               0.0030          120    +0.38%       1.10
30             0.08   base_low_stop               0.0030          120    +0.35%       1.09
30             0.08  max_10pct_stop               0.0050          120    +0.18%       1.05
```

**Diagnostic Conclusion:**
The blind grid diagnostic found that the 30/8 structure remains the least-bad and most interesting sideways breakout family, but the surviving edge is thin and fragile. It does **not** confirm durability. It reclassifies the idea from "failed fixed stop" to "still exploratory, requires a fresh untouched validation layer."

30/8 with wider stops is the only blind-period survivor, but the harsh-friction edge is marginal and fails fragility removal checks.

## Section 38: Prior Uptrend Filter Rejection

We hypothesized that the sideways-breakout setup was blindly trading both continuation setups (good) and bottom-basing reversals (bad) because it lacked a prior trend requirement. If the edge was truly in "continuation breakouts", forcing a prior uptrend should enhance the win rate and expectancy.

To test this, strict trend-filters were implemented in the discovery sweep. We tested both a `15%` and a softer `10%` 60-day prebase return threshold, combined with a `> 100-day SMA` gate (`sweep_sideways_expectancy.py --trend-filter sma100_and_prebase_60d_return_10`).

### Results (10% Threshold)
Even when relaxing the required prior trend to a modest 10% return over 60 sessions, the results strongly indicate a rejection of the sideways breakout continuation thesis for static systematic testing:
1. **Drop in Noise**: The total grid trades across all 180 configurations plummeted from 606,906 to 184,023. Approximately 70% of the setups previously identified were bottom-basing or weak-trend trades.
2. **The 30/8 Candidate Size Collapse**: The original fixed `30/0.08/max_8pct_stop` champion dropped from 276 unfiltered trades down to just **70 total trades** over the entire 5-year dataset.
3. **Edge Evaporated**: The 70 filtered trades for the 30/8 champion produced a train expectancy of `+1.08%` (2021-2023) but flipped to a **negative expectancy** (`-0.93%`) in the Blind Test set (2024-2026).
4. **Blind Grid Survival**: The diagnostic scan over the blind period (2024-2026) found **0 surviving combinations**. None of the 180 parameter combinations maintained a diagnostic edge out-of-sample.

### Conclusion
The 10% prior-uptrend filter fails to rescue the 30/8 continuation breakout thesis. It reduces sample size sharply, leaves the 30/8 blind period negative, and produces no blind-grid survivors under the diagnostic rules. The evidence strongly indicates that the original 30/8 "edge" was heavily dependent on bottom-basing reversal setups during the 2023 bull-run.

The **static systematic continuation-breakout version** of this setup is rejected. (This does not rule out every possible discretionary breakout pattern, but it proves the systematic rule is not robust). 

The research will pivot away from breakout variants and investigate **pullback entries within established trends**, as a pullback/reclaim structure may give a much better entry location and risk parameters than buying breakouts.

## Section 39: Sideways Uptrend Branch Split

The full sideways sweep was deduplicated into **24,675 unique sideways instances** across the 5-year current NIFTY 500 universe.

Regime split by `pre_structure_return_60d`:
- **Uptrend sideways:** 7,618 instances
- **Neutral sideways:** 13,138 instances
- **Downtrend sideways:** 3,919 instances

For the **7,618 uptrend-sideways instances**, the first confirmed branch focus is the subset that eventually moved upward.

Among the **4,288 uptrend-sideways instances that eventually went upward**:
- **4,280** broke upward out of the sideways range first.
- **8** broke both upward and downward on the same day.
- **0** clearly broke downward first before going upward.

Entry-relative path note from the representative sweep rows:
- **4,234** dipped below the representative entry price at some point before or while going up.
- **4,171** moved downward first relative to the representative entry price before moving upward.

Research branch split:
- **Branch A:** 4,280 upward-first uptrend-sideways instances.
- **Branch B:** 8 same-day both-side break instances.

Current focus: **Branch A**.

Reproducible artifact:
- Script: `backend/app/scripts/analyze_uptrend_sideways_branch.py`
- Summary: `D:\app\data\exports\sweep_sideways_expectancy\uptrend_sideways_branch\uptrend_sideways_branch_summary.json`
- Branch A rows: `D:\app\data\exports\sweep_sideways_expectancy\uptrend_sideways_branch\branch_a_upward_first.csv`
- Branch B rows: `D:\app\data\exports\sweep_sideways_expectancy\uptrend_sideways_branch\branch_b_same_day_both.csv`

## Section 40: Uptrend Sideways Paper Deployment

The earlier one-day latest scanner was too narrow because it only checked a single `30-session / 8%` definition. It did not represent the full Branch A research universe.

A paper-only server runner was created for the broader **uptrend-sideways branch**:
- Script: `backend/app/scripts/uptrend_sideways_paper_trader.py`
- Deploy files: `deploy/uptrend-sideways-paper-trader/`
- Data source: existing Matsya read-only market-data API
- Broker mode: paper only; `--broker dhan` intentionally raises an error

Deployment rule:
- Universe: Matsya `NIFTY_500`
- Regime bucket: prior 60-session return before the sideways base is `>= +10%`
- Sideways base grid: `10/15/20/30` sessions and max range `6/8/10/12/15%`
- Watch state: in-base or near-breakout uptrend-sideways structures are recorded
- Signal state: latest candle breaks above `base_high` and closes at least `0.5%` above `base_high`
- Paper target: `base_high * 1.10`
- Paper failure exit: low below `base_low`
- Time exit: `40` bars

Live API dry-run verification:
- Server API: `http://100.76.218.124:8020`
- Latest candle date: `2026-07-03`
- Symbols loaded: `500`
- Watch candidates found: `190`
- Upward-breakout paper signals found: `21`
- Orders placed: `0` because the run used `--dry-run`

Planned server state path:
- `/home/hacker/apps/swing-trading-app/data/uptrend_sideways_paper_trader`

Safety boundary: this is a forward paper-trading deployment only. It is not approved for live broker execution.
