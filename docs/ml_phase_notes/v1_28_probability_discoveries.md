# V1.28 Probability Discoveries — Kurma 3 / Varaha 3

These are probability-space discoveries, not deployable trading rules.

## 1. Scope

Dataset: stock_opportunity_ohlcv_regime_v3

Split: timesplit_regime_v3

Train rows: 367,071

Test rows: 91,797

Test date range: 2025-07-09 to 2026-05-18

Target: hit_7pct_before_down_3pct_20d

WIN = hit +7% before -3% within 20 trading sessions

LOSS/TIMEOUT = non-win for training/evaluation

## 2. Locked Test-Set Context

Test outcome counts:

- WIN: 22,325
- LOSS: 63,727
- TIMEOUT: 5,745

## 3. Model Context

Kurma 3 = LogisticRegression baseline trained on Dataset v3 / timesplit_regime_v3

Varaha 3 = HistGradientBoostingClassifier challenger trained on Dataset v3 / timesplit_regime_v3

## 4. Baseline Model Results

Kurma 3:

- predicted_positive_count: 1,255
- precision: 0.41115537848605577
- recall: 0.023113101903695407
- f1: 0.04376590330788804
- roc_auc: 0.5235607765217262

Varaha 3:

- predicted_positive_count: 1,958
- precision: 0.38100102145045966
- recall: 0.033415453527435614
- f1: 0.061442161182720424
- roc_auc: 0.5110878703442456

## 5. Phase 4B Individual Probability-Band Discovery

Best Kurma 3 threshold with count >= 100:

- kurma_prob >= 0.55
- selected_count: 339
- win_count: 156
- precision: 0.46017699115044247

Best Varaha 3 threshold with count >= 100:

- varaha_prob >= 0.60
- selected_count: 119
- win_count: 55
- precision: 0.46218487394957986

MVP candidate thresholds: none

Interpretation:

Individual win probabilities carried usable signal but did not cross 50% precision with meaningful count.

## 6. Phase 4C Combined Probability Multiverse Discovery

Main count-qualified discovery:

- Rule: kurma_prob >= 0.55 AND varaha_prob < 0.30
- selected_count: 106
- win_count: 56
- non_win_count: 50
- precision: 0.5283018867924528
- status: diagnostic MVP candidate, not deployable rule

Also:

- Four rules beat 46.22% with count >= 100.
- One rule crossed 50% precision with count >= 100.
- The only 50%+ rule came from confidence disagreement, not model agreement.

## 7. Phase 4D Heatmap Confirmation

- Total heatmap cells: 400
- Non-empty cells: 130
- MVP candidate exact cells: 0
- MVP candidate aggregate zones: 1

Phase 4C rule recomputed exactly:

- selected_count: 106
- win_count: 56
- loss/non_win_count: 50
- precision: 0.5283018867924528

Best exact 0.05 x 0.05 cell with count >= 100:

- Kurma 0.35-0.40 / Varaha 0.55-0.60
- selected_count: 135
- win_count: 62
- precision: 0.45925925925925926

Strongest exact cell inside the Phase 4C winning region:

- Kurma 0.55-0.60 / Varaha 0.15-0.20
- selected_count: 23
- win_count: 14
- precision: 0.6086956521739131
- not count-qualified

Interpretation:

The 52.83% rule is structurally real as an aggregate disagreement pocket, but it is fragmented across small cells and is not one clean count-qualified 0.05 x 0.05 probability cell.

## 8. Current Probability Discoveries To Preserve

Discovery 1:

Name: Kurma-Strong / Varaha-Reject Aggregate Pocket

Rule: kurma_prob >= 0.55 AND varaha_prob < 0.30

Count: 106

Wins: 56

Non-winners: 50

Precision: 52.83%

Source: Phase 4C, confirmed by Phase 4D

Status: valid for anatomy; not valid for deployment

Discovery 2:

Name: Kurma 0.55-0.60 / Varaha 0.15-0.20 Micro Pocket

Rule: 0.55 <= kurma_prob < 0.60 AND 0.15 <= varaha_prob < 0.20

Count: 23

Wins: 14

Non-winners: 9

Precision: 60.87%

Source: Phase 4D heatmap

Status: interesting micro-pocket only; not count-qualified

## 9. Why This Matters

Hard labels were too crude.

Win probability has become a central diagnostic signal.

Kurma and Varaha appear to behave as different diagnostic instruments, not simply duplicate classifiers.

The strongest count-qualified discovery came from model disagreement, not model agreement.

## 10. Why Not Deploy

The rule was found on one locked out-of-time test split.

It has not been validated on a later unseen split.

It may not survive retraining, Dataset v4 changes, or live/demo conditions.

It is a microscope for anatomy, not a trading trigger.

## 11. Next Decision

Proceed to Kurma-Strong / Varaha-Reject Pocket Anatomy.

Study the 106 rows:

56 winners vs 50 non-winners.

Goal: identify trap-removal features and Dataset v4 design candidates.

## 12. Artifact References

Paths only, not raw data:

- /app/data/evaluations/probability_band_anatomy_kurma3_varaha3_v1
- /app/data/evaluations/combined_probability_multiverse_kurma3_varaha3_v1
- /app/data/evaluations/matsya_probability_heatmap_v1

## 13. Safety Status

No deployment.

No champion selection.

No DB mutation.

No model artifact mutation.

No dataset regeneration.

No Dataset v4 created yet.