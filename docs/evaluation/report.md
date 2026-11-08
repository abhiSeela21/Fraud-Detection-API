# Synthetic fraud evaluation — model v2

Synthetic data only; no real-world performance claim.

## Reproduction and evaluation boundary

From `backend/`: `uv sync --group training` then `uv run --group training python training/train.py`. This recreates development cohorts, candidate selection, calibration, threshold tuning, the artifact and final report. Use `--development-only` to stop before final testing, then `--evaluate-frozen` to evaluate the frozen artifact. Original v1 evidence is in `baseline-v1/`; its implementation is preserved at Git commit `c27b589`.

The original 2026 test was inspected and became development evidence. Model v2 reserves a new 2028 cohort, with distinct seeds and run IDs. The protocol was committed before experiments. Candidate, calibration and thresholds were frozen before this cohort was generated. Final results below did not change those choices. Repeated runs verify reproducibility, not independent replications.

## Synthetic assumptions and leakage controls

Generator-v1 and label assumptions were retained. Invented profiles are commuter, traveler and business. Incident windows create amount spikes, repeated transactions, geographic changes or category/channel shifts. Labels are fraud with probability 0.8 inside those windows and 0.005 elsewhere. Twenty percent of incident-looking events are legitimate lookalikes; normal runs can have legitimate amount outliers. These are invented rates, not observed payment statistics. Labels never enter inputs or API responses.

All historical features use earlier event timestamps within the same account/run. A fresh run starts with no history. No scaler or estimator is fitted outside training. A separate calibration cohort fits a sigmoid to held-out raw model logits; it has no class weighting. Separate later cohorts choose the candidate and final operating thresholds. No oversampling or balancing of evaluation cohorts occurs.

| Cohort | Runs | Events | Fraud | Prevalence | Calendar range |
|---|---:|---:|---:|---:|---|
| training | 120 | 24000 | 2360 | 9.83% | 2024-01-01 – 2024-02-09 |
| calibration | 60 | 12000 | 1232 | 10.27% | 2025-01-01 – 2025-02-09 |
| selection | 60 | 12000 | 1219 | 10.16% | 2026-01-01 – 2026-02-09 |
| threshold | 60 | 12000 | 1412 | 11.77% | 2027-01-01 – 2027-02-09 |
| final_test | 90 | 18000 | 1820 | 10.11% | 2028-01-01 – 2028-02-09 |

## Features and candidate selection

Added median-relative amount, historical category/channel frequency, elapsed time since prior activity, and current channel. Exact history count was replaced in model inputs with a has-history indicator to reduce dependence on the generator's fixed incident positions. Seed, scenario, profile, run ID, account ID, event index and visitor feedback are excluded. Rules still use the same versioned rule logic. This is a joint feature/model/calibration/training-size update, not an isolated causal test of any one change.

Four regularized logistic configurations and three bounded random forests were compared. Every candidate receives separate-cohort sigmoid calibration. Selection maximizes precision subject to 80% selection recall, breaking exact ties by lower calibrated Brier loss. Threshold ties favor recall, then higher threshold. The selected model is not refitted on later cohorts. Final thresholds are independently selected on the threshold cohort under the same recall constraint.

| Candidate | Selection precision | Recall | Threshold | Raw Brier | Calibrated Brier |
|---|---:|---:|---:|---:|---:|
| logistic-C=0.1-weight=None | 0.7994 | 0.8072 | 48 | 0.0347 | 0.0346 |
| logistic-C=0.1-weight=balanced | 0.8005 | 0.8162 | 44 | 0.0527 | 0.0347 |
| logistic-C=1.0-weight=None | 0.7989 | 0.8080 | 49 | 0.0346 | 0.0346 |
| logistic-C=1.0-weight=balanced | 0.8005 | 0.8130 | 45 | 0.0528 | 0.0348 |
| forest-depth=4 | 0.7364 | 0.8023 | 38 | 0.0383 | 0.0383 |
| forest-depth=6 | 0.7905 | 0.8015 | 52 | 0.0338 | 0.0338 |
| forest-depth=8 | 0.7994 | 0.8171 | 68 | 0.0297 | 0.0296 |

Selected **logistic-C=1.0-weight=balanced**; version `model-v2-3e3ceea77cf2`; artifact 1,375 bytes. Candidate precision differences near the top are tiny and do not establish statistical superiority of one family. The predefined criterion was retained even where another candidate had a better Brier score.

## Fresh final cohort

Historical v1 is the frozen original model, original eight-feature contract and original threshold. All other thresholds come from the new threshold cohort. Comparisons use the same final events and labels. The combined score is rounded model probability × 100 plus rule adjustments capped at 40, capped overall at 100. The score is an index, not a probability. Rules are not explanations of the classifier.

| Approach | Threshold | Precision | Recall | False alerts | Missed fraud | Total alerts | Alert rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| historical_v1 | 42 | 0.234 | 0.810 | 4827 | 345 | 6302 | 35.01% |
| rules_only | 0 | 0.101 | 1.000 | 16180 | 0 | 18000 | 100.00% |
| model_only | 42 | 0.794 | 0.776 | 367 | 407 | 1780 | 9.89% |
| combined | 45 | 0.796 | 0.767 | 357 | 424 | 1753 | 9.74% |

The combined point estimate **misses** the 80% recall objective. That does not guarantee future recall. Rules at threshold zero review everything; this exposes their inability to achieve the recall floor usefully. Compare model-only with combined directly before claiming hybrid value.

### Run-cluster bootstrap uncertainty

Approximate 95% percentile intervals from 400 deterministic resamples of entire simulation runs, preserving within-run dependence. The same run samples are used across approaches. These intervals reflect the synthetic cohort and generator only; they are not real-world confidence bounds and do not include model-selection uncertainty.

| Approach | Precision interval | Recall interval | Alert-rate interval |
|---|---|---|---|
| historical_v1 | 0.168–0.291 | 0.733–0.877 | 0.312–0.387 |
| rules_only | 0.073–0.128 | 1.000–1.000 | 1.000–1.000 |
| model_only | 0.779–0.808 | 0.742–0.812 | 0.070–0.126 |
| combined | 0.782–0.811 | 0.731–0.804 | 0.069–0.125 |

## Probability calibration

Final Brier loss: raw **0.0541**, calibrated **0.0383**, constant training-prevalence reference **0.0909** (lower is better). Final average precision: **0.6962**. Calibration was fitted without final labels; an improvement is measured, not assumed.

| Probability bin | Count | Mean probability | Observed fraud rate |
|---|---:|---:|---:|
| 0.0–0.1 | 15911 | 0.020 | 0.019 |
| 0.1–0.2 | 162 | 0.135 | 0.160 |
| 0.2–0.3 | 70 | 0.246 | 0.557 |
| 0.3–0.4 | 71 | 0.352 | 0.606 |
| 0.4–0.5 | 109 | 0.454 | 0.706 |
| 0.5–0.6 | 159 | 0.556 | 0.849 |
| 0.6–0.7 | 286 | 0.654 | 0.822 |
| 0.7–0.8 | 481 | 0.754 | 0.780 |
| 0.8–0.9 | 558 | 0.845 | 0.799 |
| 0.9–1.0 | 193 | 0.967 | 0.772 |

## Scenario errors (combined)

| Group | Events | Fraud | Precision | Recall | False alerts | Missed fraud |
|---|---:|---:|---:|---:|---:|---:|
| amount | 2000 | 608 | 0.801 | 0.766 | 116 | 142 |
| burst | 1600 | 486 | 0.805 | 0.755 | 89 | 119 |
| category_channel | 600 | 185 | 0.801 | 0.978 | 45 | 4 |
| mixed | 400 | 120 | 0.789 | 0.967 | 31 | 4 |
| normal | 12200 | 57 | 0.000 | 0.000 | 0 | 57 |
| travel | 1200 | 364 | 0.778 | 0.731 | 76 | 98 |

## Profile errors (combined)

| Group | Events | Fraud | Precision | Recall | False alerts | Missed fraud |
|---|---:|---:|---:|---:|---:|---:|
| business | 6000 | 682 | 0.796 | 0.716 | 125 | 194 |
| commuter | 6000 | 683 | 0.791 | 0.794 | 143 | 141 |
| traveler | 6000 | 455 | 0.804 | 0.804 | 89 | 89 |

Background fraud labels in normal behavior often have no observable signal; these misses remain in reported recall. Burst/travel windows also label the first event before subsequent velocity evidence exists. This irreducible ambiguity is intentional. Strong category/channel results also reflect simple generator patterns; they do not prove resistance to real adversaries.

## Combined threshold tradeoffs (descriptive final evidence)

The deployed threshold was frozen earlier; this table is not used to retune it.

| Threshold | Precision | Recall | False alerts | Total alerts |
|---|---:|---:|---:|---:|
| 0 | 0.101 | 1.000 | 16180 | 18000 |
| 10 | 0.646 | 0.842 | 839 | 2372 |
| 20 | 0.701 | 0.830 | 644 | 2154 |
| 30 | 0.782 | 0.809 | 410 | 1883 |
| 40 | 0.794 | 0.785 | 371 | 1800 |
| 45 | 0.796 | 0.767 | 357 | 1753 |
| 50 | 0.800 | 0.743 | 338 | 1691 |
| 60 | 0.795 | 0.693 | 325 | 1586 |
| 70 | 0.796 | 0.633 | 296 | 1448 |
| 80 | 0.795 | 0.483 | 226 | 1105 |
| 90 | 0.779 | 0.276 | 143 | 646 |
| 100 | 0.776 | 0.234 | 123 | 548 |

## Runtime and remaining limitations

The artifact is data-only JSON, protected against accidental corruption by SHA-256 and checked for feature, input, rule, formula and structural compatibility. Exported calibrated predictions for every candidate match scikit-learn on the selection cohort within 1e-12 absolute tolerance. Forest inference reproduces sklearn's float32 input conversion and validates acyclic tree topology. Only the selected model is shipped; sklearn and NumPy remain training-only dependencies.

The generator still uses a fixed periodic incident schedule, few locations and limited merchant behavior. No concept drift, delayed labels, novel adversaries or independent real-data validation is modeled. Disjoint calendar windows are chronological synthetic cohorts, not evidence of real temporal drift robustness. Larger numbers of synthetic events do not remove these limitations. See `latency.md` for warm local API measurements; hosting wake-up is unmeasured.

References: [scikit-learn calibration and disjoint fitting data](https://scikit-learn.org/stable/modules/calibration.html), [model persistence](https://scikit-learn.org/stable/model_persistence.html), [random forests](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html).
