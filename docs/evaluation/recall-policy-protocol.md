# Recall-focused threshold policy

The 2028 cohort has been inspected. Its descriptive threshold table is not used
to pick the new operating point. Model weights, feature logic, calibration, generator
and label assumptions remain fixed. This experiment changes only the review policy.

Before opening any new audit data:

The initial 60-run attempt required 85% recall and was infeasible; its full results
are retained in `recall-policy/selection-failure.json`. Before opening audit data,
development was expanded to 300 runs and its point objective revised to 82%.
The precision guard and 80% bootstrap lower-bound requirement remain unchanged.

1. Extend the 2027 threshold-development cohort to 300 runs. Score all integer thresholds using
   the frozen v2 model. Require at least 82% development recall and a run-cluster
   bootstrap 2.5th-percentile recall bound of at least 80%. These are empirical
   safety margins, not formal coverage guarantees after threshold search.
2. Require development precision within two percentage points of the original
   threshold-45 precision on that same cohort. Among feasible thresholds choose
   highest precision, then recall, then higher threshold. If none qualifies, do
   not silently relax the constraints or generate audit data.
3. Save a frozen decision containing source model checksum, configuration, cohort
   fingerprint, threshold table, and selected threshold before generating the
   new `recall_audit` partition. That partition has independent deterministic seeds,
   150 runs, and a 2029 event-time window, after all previously inspected cohorts.
4. Compare the new threshold with threshold 45 on the identical audit transactions.
   Promote only if audit recall is strictly above 80%, precision is at least 75%,
   and precision is within two percentage points of the old policy on that cohort.
   Report failure rather than tune again on audit labels.
5. Report point metrics and run-cluster uncertainty. A single successful synthetic
   audit does not guarantee future recall or establish real-world performance.

Regeneration for reproducibility is permitted; audit results must not alter the
selection criteria, thresholds, model, labels or seed. Prior v2 reports stay intact.
