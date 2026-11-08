# Model v2 audit notes

- `d69e811` recorded the protocol and preserved baseline evidence before experiments.
- `d5111ec` committed the selected calibrated artifact and development metadata
  before the 2028 final cohort was generated. Selection chose logistic C=1.0,
  balanced training, held-out sigmoid calibration, and final review threshold 45.
- Final results missed 80% recall. No model, threshold, label assumption or cohort
  was changed in response. The report retains the miss and its uncertainty.
- A compatibility review found that old score snapshots needed their original
  seven-field schema. `3d5fdc1` fixed reads/retries without recomputing old scores.
- A reporting-only boundary test found that float arithmetic could omit an exact
  probability bin boundary. Bins now use a shared edge array and assign every
  probability once. Reproduction after that fix regenerated the same selected
  model, artifact checksum, thresholds and detection results. Source hashes were
  refreshed to capture the reporting correction; no statistical tuning changed.
- Candidate export parity was checked on selection data to 1e-12 absolute tolerance.
  Separate tests cover forest float32 split boundaries, malformed topology,
  feature incompatibility, corruption, temporal leakage and online/offline parity.
- Bootstrap intervals resample whole runs, not individual transactions. They
  exclude model-selection uncertainty and real-world distribution uncertainty.

The current model is a stronger synthetic demonstration, with a documented
precision/recall tradeoff. It is not a validated real-payment detector.
