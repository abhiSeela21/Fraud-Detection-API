# Model improvement protocol (v2)

The v1 test was inspected and is now development evidence. Its report and model
remain in Git at commit c27b589. No later result will be described as an untouched
v1 test improvement.

Before running new experiments, freeze this protocol:

- Keep generator-v1 and its label assumptions unchanged. Do not simplify labels or
  increase separability to improve metrics.
- Improve causal account-history features: median-relative amount, category and
  channel frequency, and time since previous activity. Include current channel.
  Remove exact history count from model inputs to reduce dependence on the
  generator's periodic incident schedule. No scenario/profile/run/seed/index inputs.
- Compare regularized logistic and bounded random forests. Probability calibration
  uses a separate chronological cohort. Selection and threshold tuning use separate
  later development cohorts. No fitting on those cohorts.
- Select by precision subject to 80% recall on selection; use Brier loss to break
  ties. Set the final threshold independently on the threshold cohort with the
  same recall objective. Report other operating points rather than hiding tradeoffs.
- Reserve `final_test` with different deterministic seeds and a 2028 calendar window
  until candidate, calibration, and threshold are frozen. Do not change configuration
  after inspecting final results. Missed targets remain visible.
- Report per-scenario/profile errors, probability calibration, false alerts, volume,
  and cluster-bootstrap uncertainty by simulation run. Runs are dependent sequences;
  treating individual events as independent would overstate certainty.
- Compare old logistic, new model-only, rules-only and combined on the same final
  cohort. The old logistic uses its original feature version and threshold; it is
  a historical operating point, not a newly threshold-tuned competitor.
- Export data-only JSON and test it against scikit-learn before shipping. Recheck
  model size, local HTTP latency, artifact rejection, and online/offline parity.

All measurements remain synthetic and establish no real-world payment performance.
