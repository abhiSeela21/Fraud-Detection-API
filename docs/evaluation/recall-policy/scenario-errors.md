# Scoring errors by scenario

On the 30,000-transaction synthetic audit, threshold 38 missed 674 fraud cases and raised 786 false alerts. The **burst** scenario contributed the most misses (239). The **amount** scenario contributed the most false alerts (205).

The table compares cutoffs 45 and 38 using the same scores. Rates are for threshold 38. Miss rate divides missed fraud by fraud events. False alert rate divides false alerts by legitimate events.

| Scenario | Events | Fraud | Missed fraud (45 → 38) | Miss rate | False alerts (45 → 38) | False alert rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| amount | 2,800 | 844 | 193 → 145 | 17.2% | 179 → 205 | 10.48% |
| burst | 3,200 | 952 | 239 → 239 | 25.1% | 199 → 199 | 8.85% |
| category channel | 1,400 | 439 | 7 → 4 | 0.9% | 95 → 95 | 9.89% |
| mixed | 2,200 | 687 | 33 → 21 | 3.1% | 148 → 154 | 10.18% |
| normal | 18,200 | 96 | 96 → 96 | 100.0% | 4 → 5 | 0.03% |
| travel | 2,200 | 684 | 180 → 169 | 24.7% | 124 → 128 | 8.44% |
| **All** | 30,000 | 3,702 | 748 → 674 | 18.2% | 749 → 786 | 2.99% |

Scenario describes the entire simulation run. Even runs labeled normal can contain randomly assigned background fraud labels. Those labels can lack observable warning signals. The counts describe this synthetic cohort and depend on its scenario mix and label assumptions.

From `backend/`, run `uv run --group training python training/analyze_errors.py` to regenerate this report. The script checks the frozen inputs, cohort fingerprint, and aggregate metrics against the [published audit](report.md).
