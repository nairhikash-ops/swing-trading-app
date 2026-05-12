# Drishti Signal 01 Wrong Early Detections

Generated from the latest saved Drishti run on the development server.

Signal: `DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL`

Definition of wrong for this note:

- A signal is counted as a wrong early detection if it did not reach `+10%` from the trigger close inside the available historical window.
- This does not mean the stock never moved from the anchor low. It means the alert was not good enough from the actual trigger close.

Run snapshot:

- Run id: `2`
- Window: `2026-01-12` to `2026-05-12`
- Total hits: `53`
- Hits reaching `+10%` from trigger close: `43`
- Wrong early detections: `10`
- Current follow-through rate: `81.13%`

## Wrong Early Detections

| Symbol | Company | Industry | Anchor | Trigger | Anchor Low | Anchor High | Trigger Close | Volume Ratio | Vol/SMA | Future High | Future High Date | Trigger Outcome | Anchor Outcome |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| CANHLIFE | Canara HSBC Life Insurance Company Ltd. | Financial Services | 2026-04-28 | 2026-04-29 | 133.21 | 139.73 | 146.17 | 3.82x | 6.06x | 149.69 | 2026-04-29 | 2.41% | 12.37% |
| BANKINDIA | Bank of India | Financial Services | 2026-03-19 | 2026-03-20 | 144.72 | 149.91 | 150.49 | 1.81x | 1.37x | 154.34 | 2026-04-22 | 2.56% | 6.65% |
| FORCEMOT | Force Motors Ltd. | Automobile and Auto Components | 2026-05-05 | 2026-05-06 | 18835.00 | 19535.00 | 20173.00 | 1.95x | 1.61x | 21180.00 | 2026-05-08 | 4.99% | 12.45% |
| UNITDSPR | United Spirits Ltd. | Fast Moving Consumer Goods | 2026-03-23 | 2026-03-24 | 1266.40 | 1288.90 | 1328.00 | 1.43x | 1.49x | 1414.40 | 2026-04-27 | 6.51% | 11.69% |
| SUNPHARMA | Sun Pharmaceutical Industries Ltd. | Healthcare | 2026-04-24 | 2026-04-27 | 1613.60 | 1673.30 | 1733.50 | 2.81x | 7.09x | 1857.80 | 2026-05-06 | 7.17% | 15.13% |
| MAPMYINDIA | C.E. Info Systems Ltd. | Information Technology | 2026-03-19 | 2026-03-20 | 853.00 | 879.70 | 915.70 | 8.47x | 4.61x | 981.65 | 2026-05-07 | 7.20% | 15.08% |
| BANKINDIA | Bank of India | Financial Services | 2026-04-02 | 2026-04-06 | 134.52 | 139.80 | 143.05 | 1.55x | 1.49x | 154.34 | 2026-04-22 | 7.89% | 14.73% |
| IOB | Indian Overseas Bank | Financial Services | 2026-03-19 | 2026-03-20 | 31.55 | 32.24 | 33.72 | 7.02x | 3.91x | 36.39 | 2026-04-29 | 7.92% | 15.34% |
| IIFL | IIFL Finance Ltd. | Financial Services | 2026-04-24 | 2026-04-27 | 411.85 | 423.55 | 434.00 | 3.20x | 4.90x | 473.50 | 2026-05-04 | 9.10% | 14.97% |
| INFY | Infosys Ltd. | Information Technology | 2026-03-19 | 2026-03-20 | 1215.10 | 1255.00 | 1255.90 | 2.98x | 2.18x | 1376.90 | 2026-04-08 | 9.63% | 13.32% |

## First Observations

- The misses are not all useless alerts. Most still moved more than `10%` from the anchor low, but not from the trigger close.
- This suggests the current trigger may sometimes arrive too late or too extended for a clean `+10%` follow-through target.
- Financial Services appears repeatedly in the misses: `CANHLIFE`, `BANKINDIA`, `IOB`, `IIFL`.
- Several misses had very strong volume spikes, so volume alone is not enough to improve the signal.
- `BANKINDIA` appeared twice as a wrong early detection. Duplicate signals for the same stock may need a cooldown rule.
- Near-misses like `INFY`, `IIFL`, and `IOB` should be treated differently from weak misses like `CANHLIFE` and the first `BANKINDIA` signal.

## Improvement Questions

- Should Signal 01 count success from trigger close only, or should it also track anchor-low opportunity separately?
- Should we add a cooldown after one signal fires for the same stock?
- Should we reject signals where the trigger close is already too far above the anchor low?
- Should Financial Services be reviewed as a separate behavior bucket instead of mixed with all sectors?
- Should we add max drawdown after trigger before judging a signal as usable or unusable?
