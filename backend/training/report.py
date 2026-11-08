"""Evaluate an already frozen model; this module never fits or selects an estimator."""

import hashlib
import json

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss

from fraud_api.artifacts import ARTIFACT_DIR, load_artifact
from training.data import dataset, metrics, summary


def evaluate(config, development, payload, output):
    from training.train import bootstrap, breakdown, calibration_bins, historical_scores, vectors

    raw = (ARTIFACT_DIR / "model.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != development["artifact_sha256"]:
        raise ValueError("Artifact changed after development freeze")
    artifact = load_artifact(ARTIFACT_DIR)
    if artifact.model_version != development["model_version"]:
        raise ValueError("Frozen model version changed")
    # This is the first point in the pipeline where the reserved cohort is generated.
    test = dataset(config, "final_test")
    assert development["partitions"]["threshold"]["end"] < test["start"]
    probabilities = np.array([artifact.probability(row.tolist()) for row in test["x"]])
    uncalibrated = np.array([artifact.raw_probability(row.tolist()) for row in test["x"]])
    model, combined = vectors(probabilities, test["rules"])
    old_scores, old_threshold = historical_scores(test)
    scores = {
        "historical_v1": old_scores,
        "rules_only": test["rules"],
        "model_only": model,
        "combined": combined,
    }
    thresholds = {**development["thresholds"], "historical_v1": old_threshold}
    results = {
        name: metrics(test["y"], values, thresholds[name]) for name, values in scores.items()
    }
    intervals = {
        name: bootstrap(
            test, values, thresholds[name], config["bootstrap_repetitions"], config["seed"] + 91
        )
        for name, values in scores.items()
    }
    report = {
        "warning": "Synthetic data only; no real-world performance claim.",
        "protocol": "improvement-plan.md; final cohort not used for selection or tuning",
        "config": config,
        "model_version": artifact.model_version,
        "artifact_sha256": development["artifact_sha256"],
        "artifact_bytes": len(raw),
        "winner": development["winner"],
        "partitions": {**development["partitions"], "final_test": summary(test)},
        "test": results,
        "cluster_bootstrap_95_intervals": intervals,
        "test_model_brier": float(brier_score_loss(test["y"], probabilities)),
        "test_raw_brier": float(brier_score_loss(test["y"], uncalibrated)),
        "test_constant_prior_brier": float(
            brier_score_loss(
                test["y"],
                np.full(len(test["y"]), development["partitions"]["training"]["prevalence"]),
            )
        ),
        "test_average_precision": float(average_precision_score(test["y"], probabilities)),
        "calibration_bins": calibration_bins(test["y"], probabilities),
        "raw_calibration_bins": calibration_bins(test["y"], uncalibrated),
        "scenario_errors": breakdown(test, combined, thresholds["combined"], "scenario"),
        "profile_errors": breakdown(test, combined, thresholds["combined"], "profile"),
        "combined_threshold_table": [metrics(test["y"], combined, t) for t in range(101)],
        "environment": development["environment"],
    }
    (output / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Synthetic fraud evaluation — model v2",
        "",
        report["warning"],
        "",
        "## Reproduction and evaluation boundary",
        "",
        "From `backend/`: `uv sync --group training` then `uv run --group training python training/train.py`. This recreates development cohorts, candidate selection, calibration, threshold tuning, the artifact and final report. Use `--development-only` to stop before final testing, then `--evaluate-frozen` to evaluate the frozen artifact. Original v1 evidence is in `baseline-v1/`; its implementation is preserved at Git commit `c27b589`.",
        "",
        "The original 2026 test was inspected and became development evidence. Model v2 reserves a new 2028 cohort, with distinct seeds and run IDs. The protocol was committed before experiments. Candidate, calibration and thresholds were frozen before this cohort was generated. Final results below did not change those choices. Repeated runs verify reproducibility, not independent replications.",
        "",
        "## Synthetic assumptions and leakage controls",
        "",
        "Generator-v1 and label assumptions were retained. Invented profiles are commuter, traveler and business. Incident windows create amount spikes, repeated transactions, geographic changes or category/channel shifts. Labels are fraud with probability 0.8 inside those windows and 0.005 elsewhere. Twenty percent of incident-looking events are legitimate lookalikes; normal runs can have legitimate amount outliers. These are invented rates, not observed payment statistics. Labels never enter inputs or API responses.",
        "",
        "All historical features use earlier event timestamps within the same account/run. A fresh run starts with no history. No scaler or estimator is fitted outside training. A separate calibration cohort fits a sigmoid to held-out raw model logits; it has no class weighting. Separate later cohorts choose the candidate and final operating thresholds. No oversampling or balancing of evaluation cohorts occurs.",
        "",
        "| Cohort | Runs | Events | Fraud | Prevalence | Calendar range |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, row in report["partitions"].items():
        lines.append(
            f"| {name} | {row['runs']} | {row['count']} | {row['fraud']} | {row['prevalence']:.2%} | {row['start'][:10]} – {row['end'][:10]} |"
        )
    lines += [
        "",
        "## Features and candidate selection",
        "",
        "Added median-relative amount, historical category/channel frequency, elapsed time since prior activity, and current channel. Exact history count was replaced in model inputs with a has-history indicator to reduce dependence on the generator's fixed incident positions. Seed, scenario, profile, run ID, account ID, event index and visitor feedback are excluded. Rules still use the same versioned rule logic. This is a joint feature/model/calibration/training-size update, not an isolated causal test of any one change.",
        "",
        "Four regularized logistic configurations and three bounded random forests were compared. Every candidate receives separate-cohort sigmoid calibration. Selection maximizes precision subject to 80% selection recall, breaking exact ties by lower calibrated Brier loss. Threshold ties favor recall, then higher threshold. The selected model is not refitted on later cohorts. Final thresholds are independently selected on the threshold cohort under the same recall constraint.",
        "",
        "| Candidate | Selection precision | Recall | Threshold | Raw Brier | Calibrated Brier |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in development["candidates"]:
        metric = row["selection"]
        lines.append(
            f"| {row['name']} | {metric['precision']:.4f} | {metric['recall']:.4f} | {metric['threshold']} | {row['raw_brier']:.4f} | {row['calibrated_brier']:.4f} |"
        )
    lines += [
        "",
        f"Selected **{development['winner']}**; version `{artifact.model_version}`; artifact {len(raw):,} bytes. Candidate precision differences near the top are tiny and do not establish statistical superiority of one family. The predefined criterion was retained even where another candidate had a better Brier score.",
        "",
        "## Fresh final cohort",
        "",
        "Historical v1 is the frozen original model, original eight-feature contract and original threshold. All other thresholds come from the new threshold cohort. Comparisons use the same final events and labels. The combined score is rounded model probability × 100 plus rule adjustments capped at 40, capped overall at 100. The score is an index, not a probability. Rules are not explanations of the classifier.",
        "",
        "| Approach | Threshold | Precision | Recall | False alerts | Missed fraud | Total alerts | Alert rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in results.items():
        lines.append(
            f"| {name} | {row['threshold']} | {row['precision']:.3f} | {row['recall']:.3f} | {row['false_alerts']} | {row['missed_fraud']} | {row['alert_volume']} | {row['alert_rate']:.2%} |"
        )
    achieved = results["combined"]["recall"] >= config["validation_recall_floor"]
    lines += [
        "",
        f"The combined point estimate **{'meets' if achieved else 'misses'}** the 80% recall objective. That does not guarantee future recall. Rules at threshold zero review everything; this exposes their inability to achieve the recall floor usefully. Compare model-only with combined directly before claiming hybrid value.",
        "",
        "### Run-cluster bootstrap uncertainty",
        "",
        f"Approximate 95% percentile intervals from {config['bootstrap_repetitions']} deterministic resamples of entire simulation runs, preserving within-run dependence. The same run samples are used across approaches. These intervals reflect the synthetic cohort and generator only; they are not real-world confidence bounds and do not include model-selection uncertainty.",
        "",
        "| Approach | Precision interval | Recall interval | Alert-rate interval |",
        "|---|---|---|---|",
    ]
    for name, interval in intervals.items():
        cells = [
            f"{interval[key][0]:.3f}–{interval[key][1]:.3f}"
            for key in ["precision", "recall", "alert_rate"]
        ]
        lines.append(f"| {name} | {' | '.join(cells)} |")
    lines += [
        "",
        "## Probability calibration",
        "",
        f"Final Brier loss: raw **{report['test_raw_brier']:.4f}**, calibrated **{report['test_model_brier']:.4f}**, constant training-prevalence reference **{report['test_constant_prior_brier']:.4f}** (lower is better). Final average precision: **{report['test_average_precision']:.4f}**. Calibration was fitted without final labels; an improvement is measured, not assumed.",
        "",
        "| Probability bin | Count | Mean probability | Observed fraud rate |",
        "|---|---:|---:|---:|",
    ]
    for row in report["calibration_bins"]:
        lines.append(
            f"| {row['lower']:.1f}–{row['lower'] + 0.1:.1f} | {row['count']} | {row['mean_probability']:.3f} | {row['observed_fraud_rate']:.3f} |"
        )
    for title, key in [
        ("Scenario errors", "scenario_errors"),
        ("Profile errors", "profile_errors"),
    ]:
        lines += [
            "",
            f"## {title} (combined)",
            "",
            "| Group | Events | Fraud | Precision | Recall | False alerts | Missed fraud |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, row in report[key].items():
            lines.append(
                f"| {name} | {row['events']} | {row['fraud']} | {row['precision']:.3f} | {row['recall']:.3f} | {row['false_alerts']} | {row['missed_fraud']} |"
            )
    lines += [
        "",
        "Background fraud labels in normal behavior often have no observable signal; these misses remain in reported recall. Burst/travel windows also label the first event before subsequent velocity evidence exists. This irreducible ambiguity is intentional. Strong category/channel results also reflect simple generator patterns; they do not prove resistance to real adversaries.",
        "",
        "## Combined threshold tradeoffs (descriptive final evidence)",
        "",
        "The deployed threshold was frozen earlier; this table is not used to retune it.",
        "",
        "| Threshold | Precision | Recall | False alerts | Total alerts |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["combined_threshold_table"]:
        if row["threshold"] % 10 == 0 or row["threshold"] == artifact.review_threshold:
            lines.append(
                f"| {row['threshold']} | {row['precision']:.3f} | {row['recall']:.3f} | {row['false_alerts']} | {row['alert_volume']} |"
            )
    lines += [
        "",
        "## Runtime and remaining limitations",
        "",
        "The artifact is data-only JSON, protected against accidental corruption by SHA-256 and checked for feature, input, rule, formula and structural compatibility. Exported calibrated predictions for every candidate match scikit-learn on the selection cohort within 1e-12 absolute tolerance. Forest inference reproduces sklearn's float32 input conversion and validates acyclic tree topology. Only the selected model is shipped; sklearn and NumPy remain training-only dependencies.",
        "",
        "The generator still uses a fixed periodic incident schedule, few locations and limited merchant behavior. No concept drift, delayed labels, novel adversaries or independent real-data validation is modeled. Disjoint calendar windows are chronological synthetic cohorts, not evidence of real temporal drift robustness. Larger numbers of synthetic events do not remove these limitations. See `latency.md` for warm local API measurements; hosting wake-up is unmeasured.",
        "",
        "References: [scikit-learn calibration and disjoint fitting data](https://scikit-learn.org/stable/modules/calibration.html), [model persistence](https://scikit-learn.org/stable/model_persistence.html), [random forests](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html).",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "model_version": artifact.model_version,
                "test": results,
                "brier": report["test_model_brier"],
                "intervals": intervals,
            },
            indent=2,
        )
    )
