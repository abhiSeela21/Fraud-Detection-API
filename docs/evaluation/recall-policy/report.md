# Recall policy audit

Synthetic data only; no real-world performance claim.

## Selection boundary

Weights, features, calibration and label assumptions are unchanged. The 2028 results were inspected previously and were not used to pick this threshold. The expanded 2027 development cohort selects the maximum-precision threshold satisfying 82% point recall, a run-cluster bootstrap lower recall bound of 80%, and precision within two percentage points of the original policy. The initial stricter 85% attempt failed on development; its evidence is preserved. The revised decision was saved before generating the new 2029 audit cohort.

Selected threshold: **38**. Development precision **79.32%**, recall **82.24%**, recall lower bound **80.22%**.

Fresh audit: **30,000 events**, **150 runs**, **3,702 fraud labels**. The same events and scores are compared at both thresholds.

| Policy | Threshold | Precision | Recall | False alerts | Missed fraud | Total reviews |
|---|---:|---:|---:|---:|---:|---:|
| Previous | 45 | 79.77% | 79.79% | 749 | 748 | 3703 |
| Recall-focused | 38 | 79.39% | 81.79% | 786 | 674 | 3814 |

Promotion gate **passed**: audit recall strictly above 80%, precision at least 75%, and precision loss at most two percentage points versus the previous policy on this same cohort. No audit-based retuning follows a failed gate.

## Uncertainty and limits

Approximate 95% run-cluster bootstrap intervals; 1,000 whole-run resamples preserve sequential dependence. Development threshold search means these empirical intervals are not a formal guarantee of future recall. Audit intervals exclude model-selection and real-world distribution uncertainty.

| Policy | Precision interval | Recall interval |
|---|---|---|
| baseline | 78.27%–81.32% | 76.63%–82.66% |
| candidate | 77.87%–80.97% | 78.78%–84.43% |

The generator remains limited and periodic. This audit measures an operating-point tradeoff, not a newly trained model. All prior v2 evidence remains intact. Stored scores are immutable and retain their original threshold/version.

## Reproduce

From `backend/`: `uv run --group training python training/tune_recall.py --select-only`, then `uv run --group training python training/tune_recall.py`. The preserved `prior-model.json` anchors the original weights and threshold so reruns do not tune against an already-promoted model. Retraining v2 with `training/train.py` restores its original policy; run these two policy commands afterward to reproduce the promoted policy.
