# Synthetic detection evaluation

All data is synthetic. Results do not establish real-world fraud detection performance.

Reproduce from `backend/`: `uv sync --group training && uv run --group training python training/train.py`.

## Dataset and leakage controls

The generator invents commuter, traveler and business spending. Incident windows inject amount spikes, bursts, travel or category/channel shifts. Eighty percent of incident-window events are labeled fraud; the remainder are legitimate lookalikes. A 0.5% background fraud probability introduces low-signal fraud. These probabilities are simulation assumptions, not observed payment statistics. Labels are never returned by the scoring API or included in model inputs.

Each cohort has disjoint account/run seeds and a later non-overlapping calendar window. Every feature uses only earlier events from its own account/run. Entire run histories are generated in order, including cold starts. No scaling, weighting or fitting uses validation/test data. This measures future synthetic cohorts, not performance on recurring real customers.

| Partition | Events | Fraud | Prevalence | Start | End |
|---|---:|---:|---:|---|---|
| training | 18000 | 1839 | 10.22% | 2024-01-01T00:00:00+00:00 | 2024-02-09T08:00:00+00:00 |
| validation | 6000 | 678 | 11.30% | 2025-01-01T00:00:00+00:00 | 2025-02-09T08:00:00+00:00 |
| test | 6000 | 694 | 11.57% | 2026-01-01T00:00:00+00:00 | 2026-02-09T08:00:00+00:00 |

## Validation selection

Candidates are standardized scikit-learn logistic classifiers with three regularization strengths and optional training-only class weighting. Select maximum validation combined-score precision subject to 80% recall; break candidate ties by lower Brier loss. Threshold ties favor recall then the higher threshold. The recall floor is a demo objective, not a real financial cost model. No test-based retuning or refit occurs.

| Candidate | Precision | Recall | Threshold | Brier loss |
|---|---:|---:|---:|---:|
| logistic-C=0.1-weight=None | 0.240 | 0.824 | 8 | 0.0689 |
| logistic-C=0.1-weight=balanced | 0.256 | 0.802 | 42 | 0.1498 |
| logistic-C=1.0-weight=None | 0.241 | 0.826 | 8 | 0.0689 |
| logistic-C=1.0-weight=balanced | 0.256 | 0.804 | 42 | 0.1497 |
| logistic-C=10.0-weight=None | 0.241 | 0.826 | 8 | 0.0689 |
| logistic-C=10.0-weight=balanced | 0.256 | 0.804 | 42 | 0.1497 |

Selected `logistic-C=0.1-weight=balanced`; model version `logistic-v1-cdc4def66121`.

## Untouched later test period

The validation recall floor is a selection constraint, not a test guarantee. Combined test recall is 66.4% against the 80% validation objective. Rules select threshold 0 and review 100.0% of test events. The combined minus model-only precision difference is 0.0010. Inspect these results before claiming that the target generalizes or that hybrid scoring adds useful value.

Each approach's threshold was selected independently on validation under the same recall floor. The final score is rounded model probability × 100 plus rule adjustments capped at 40, capped overall at 100. That score is a ranking index, not a calibrated fraud probability. Rule signals describe rules and do not explain the classifier.

| Approach | Threshold | Precision | Recall | False alerts | Total alerts | Alert rate |
|---|---:|---:|---:|---:|---:|---:|
| rules_only | 0 | 0.116 | 1.000 | 5306 | 6000 | 100.00% |
| model_only | 42 | 0.227 | 0.659 | 1556 | 2013 | 33.55% |
| combined | 42 | 0.228 | 0.664 | 1561 | 2022 | 33.70% |

Model probability Brier loss: 0.1565; average precision: 0.4987. Brier loss is a calibration diagnostic, not a guarantee of calibrated probabilities. No separate probability calibrator was fitted.

A constant training-prevalence predictor has test Brier loss 0.1025. Lower Brier loss is better. Class weighting changes the training prior; the selected classifier's raw probability outputs are uncalibrated. Model selection prioritized validation precision at the recall constraint, not calibration alone.

## Combined threshold tradeoff (test; descriptive only)

| Threshold | Precision | Recall | False alerts | Total alerts |
|---|---:|---:|---:|---:|
| 0 | 0.116 | 1.000 | 5306 | 6000 |
| 10 | 0.117 | 0.999 | 5229 | 5922 |
| 20 | 0.127 | 0.941 | 4502 | 5155 |
| 30 | 0.151 | 0.807 | 3159 | 3719 |
| 40 | 0.211 | 0.684 | 1777 | 2252 |
| 42 | 0.228 | 0.664 | 1561 | 2022 |
| 50 | 0.326 | 0.584 | 839 | 1244 |
| 60 | 0.508 | 0.530 | 357 | 725 |
| 70 | 0.639 | 0.451 | 177 | 490 |
| 80 | 0.690 | 0.385 | 120 | 387 |
| 90 | 0.708 | 0.336 | 96 | 329 |
| 100 | 0.768 | 0.287 | 60 | 259 |

## Limitations and artifact

Generator assumptions dominate these results. Labels overlap but lack realistic adversaries, merchant diversity, feedback delay or concept drift. No confidence interval or independent real-data validation is claimed. A combined approach may not outperform model-only; retain that evidence rather than changing the test-based decision. Run/account ID, seed, scenario, profile and label are excluded from the eight numeric model inputs.

Only standardized logistic coefficients are exported as a small data-only JSON file. Runtime inference is checked against scikit-learn to 1e-12 on validation. A SHA-256 manifest detects accidental corruption, not a malicious replacement of both files. Startup validates feature/input/rule/formula versions and dimensions; loading does not execute pickle. Full configuration, environment and all 101 threshold rows are in `results.json`.

API latency is measured separately by `training/benchmark.py` against the running API and PostgreSQL; see `latency.md` when available. Training runtime is not API latency.

References: [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html), [held-out model selection](https://scikit-learn.org/stable/modules/grid_search.html), [model persistence](https://scikit-learn.org/stable/model_persistence.html).
