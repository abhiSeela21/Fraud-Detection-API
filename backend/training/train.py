"""Reproduce data, candidate selection, artifact export and held-out evaluation.

Run from backend: uv run --group training python training/train.py
"""

import hashlib
import json
import platform
import random
import sys
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fraud_api.artifacts import ARTIFACT_DIR, ModelArtifact  # noqa: E402
from fraud_api.features import FEATURE_VERSION, calculate_features  # noqa: E402
from fraud_api.formula import combined_score  # noqa: E402
from fraud_api.model_inputs import INPUT_NAMES, INPUT_VERSION, model_inputs  # noqa: E402
from fraud_api.rules import RULE_VERSION, rule_signals, rules_score  # noqa: E402
from fraud_api.scoring import SCORING_VERSION  # noqa: E402
from fraud_api.simulation import GENERATOR_VERSION, SimulationConfig, generate_transaction  # noqa: E402


def dataset(config, partition):
    """Disjoint account/run cohorts in non-overlapping time windows, sorted by event time."""
    rng = random.Random(f"{config['seed']}:{partition}")
    records = []
    profiles = ["commuter", "traveler", "business"]
    scenarios = ["burst", "travel", "amount", "category_channel", "mixed"]
    for run in range(config[f"{partition}_runs"]):
        scenario = (
            "normal" if rng.random() < config["normal_run_fraction"] else rng.choice(scenarios)
        )
        simulation = SimulationConfig(
            run_id=uuid5(
                NAMESPACE_URL, f"{config['dataset_version']}:{config['seed']}:{partition}:{run}"
            ),
            seed=rng.randrange(2**32),
            profile=profiles[run % 3],
            scenario=scenario,
            start_time=datetime.fromisoformat(config[f"{partition}_start"]),
        )
        history = []
        for index in range(config["transactions_per_run"]):
            transaction = generate_transaction(simulation, index)
            features = calculate_features(transaction, history)
            # The generator's latent incident window is ground truth, not a rule output.
            # Some incident-looking events are legitimate; low-signal fraud also exists.
            incident = scenario != "normal" and index >= 10 and index % 10 >= 6
            probability = (
                config["incident_fraud_probability"]
                if incident
                else config["background_fraud_probability"]
            )
            label = int(rng.random() < probability)
            records.append(
                (
                    transaction.timestamp,
                    model_inputs(transaction, features),
                    label,
                    rules_score(rule_signals(features)),
                )
            )
            history.append(transaction)
    records.sort(key=lambda row: row[0])
    return {
        "x": np.array([row[1] for row in records]),
        "y": np.array([row[2] for row in records]),
        "rules": np.array([row[3] for row in records]),
        "start": records[0][0].isoformat(),
        "end": records[-1][0].isoformat(),
    }


def metrics(labels, scores, threshold):
    predicted = scores >= threshold
    true = int(np.sum(predicted & (labels == 1)))
    false = int(np.sum(predicted & (labels == 0)))
    positives = int(np.sum(labels))
    return {
        "threshold": int(threshold),
        "precision": true / max(1, true + false),
        "recall": true / max(1, positives),
        "true_alerts": true,
        "false_alerts": false,
        "missed_fraud": positives - true,
        "alert_volume": true + false,
        "alert_rate": (true + false) / len(labels),
    }


def select_threshold(labels, scores, recall_floor):
    feasible = [metrics(labels, scores, threshold) for threshold in range(101)]
    feasible = [row for row in feasible if row["recall"] >= recall_floor]
    if not feasible:
        raise ValueError("No threshold satisfies the configured validation recall floor")
    return max(feasible, key=lambda row: (row["precision"], row["recall"], row["threshold"]))


def score_vectors(probabilities, rules):
    model = np.rint(100 * probabilities).astype(int)
    combined = np.array(
        [combined_score(float(p), int(r)) for p, r in zip(probabilities, rules, strict=True)]
    )
    return model, combined


def main():
    config = json.loads((ROOT / "training/config.json").read_text())
    train, validation = (dataset(config, part) for part in ["training", "validation"])
    assert train["end"] < validation["start"]
    candidates = []
    for c in config["regularization_candidates"]:
        for weight in [None, "balanced"]:
            pipeline = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=c,
                    class_weight=weight,
                    max_iter=2000,
                    random_state=config["seed"],
                ),
            )
            pipeline.fit(train["x"], train["y"])
            probabilities = pipeline.predict_proba(validation["x"])[:, 1]
            _, combined = score_vectors(probabilities, validation["rules"])
            selected = select_threshold(
                validation["y"], combined, config["validation_recall_floor"]
            )
            brier = float(brier_score_loss(validation["y"], probabilities))
            candidates.append(
                {
                    "name": f"logistic-C={c}-weight={weight}",
                    "pipeline": pipeline,
                    "validation": selected,
                    "brier": brier,
                }
            )
    winner = max(candidates, key=lambda row: (row["validation"]["precision"], -row["brier"]))
    pipeline = winner["pipeline"]
    scaler, classifier = pipeline.steps[0][1], pipeline.steps[1][1]
    # No refit on validation: exported coefficients are exactly those evaluated.
    payload = {
        "format": "standardized-logistic-v1",
        "model_version": "pending",
        "feature_version": FEATURE_VERSION,
        "input_version": INPUT_VERSION,
        "rule_version": RULE_VERSION,
        "scoring_version": SCORING_VERSION,
        "input_names": INPUT_NAMES,
        "means": scaler.mean_.tolist(),
        "scales": scaler.scale_.tolist(),
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "review_threshold": winner["validation"]["threshold"],
    }
    version_hash = hashlib.sha256(
        json.dumps({"config": config, "model": payload}, sort_keys=True).encode()
    ).hexdigest()
    payload["model_version"] = f"logistic-v1-{version_hash[:12]}"
    artifact = ModelArtifact.model_validate(payload)
    exported_probabilities = np.array(
        [artifact.probability(row.tolist()) for row in validation["x"]]
    )
    np.testing.assert_allclose(
        exported_probabilities, pipeline.predict_proba(validation["x"])[:, 1], atol=1e-12, rtol=0
    )
    # Freeze candidate and thresholds before creating or inspecting test data.
    val_model, _ = score_vectors(exported_probabilities, validation["rules"])
    thresholds = {
        "rules_only": select_threshold(
            validation["y"], validation["rules"], config["validation_recall_floor"]
        )["threshold"],
        "model_only": select_threshold(
            validation["y"], val_model, config["validation_recall_floor"]
        )["threshold"],
        "combined": payload["review_threshold"],
    }
    test = dataset(config, "test")
    assert validation["end"] < test["start"]
    probabilities = np.array([artifact.probability(row.tolist()) for row in test["x"]])
    model, combined = score_vectors(probabilities, test["rules"])
    results = {
        "rules_only": metrics(test["y"], test["rules"], thresholds["rules_only"]),
        "model_only": metrics(test["y"], model, thresholds["model_only"]),
        "combined": metrics(test["y"], combined, thresholds["combined"]),
    }
    report = {
        "warning": "All data is synthetic. Results do not establish real-world fraud detection performance.",
        "config": config,
        "generator_version": GENERATOR_VERSION,
        "environment": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "partitions": {
            name: {
                "count": len(data["y"]),
                "fraud": int(sum(data["y"])),
                "prevalence": float(np.mean(data["y"])),
                "start": data["start"],
                "end": data["end"],
            }
            for name, data in [("training", train), ("validation", validation), ("test", test)]
        },
        "candidates": [
            {key: value for key, value in row.items() if key != "pipeline"} for row in candidates
        ],
        "winner": winner["name"],
        "model_version": payload["model_version"],
        "validation_thresholds": thresholds,
        "test": results,
        "test_model_brier": float(brier_score_loss(test["y"], probabilities)),
        "test_constant_prior_brier": float(
            brier_score_loss(test["y"], np.full(len(test["y"]), float(np.mean(train["y"]))))
        ),
        "test_average_precision": float(average_precision_score(test["y"], probabilities)),
        "combined_threshold_table": [metrics(test["y"], combined, t) for t in range(101)],
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (ARTIFACT_DIR / "model.json").write_bytes(raw)
    (ARTIFACT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "model_version": payload["model_version"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    output = ROOT.parent / "docs/evaluation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Synthetic detection evaluation",
        "",
        report["warning"],
        "",
        "Reproduce from `backend/`: `uv sync --group training && uv run --group training python training/train.py`.",
        "",
        "## Dataset and leakage controls",
        "",
        "The generator invents commuter, traveler and business spending. Incident windows inject amount spikes, bursts, travel or category/channel shifts. Eighty percent of incident-window events are labeled fraud; the remainder are legitimate lookalikes. A 0.5% background fraud probability introduces low-signal fraud. These probabilities are simulation assumptions, not observed payment statistics. Labels are never returned by the scoring API or included in model inputs.",
        "",
        "Each cohort has disjoint account/run seeds and a later non-overlapping calendar window. Every feature uses only earlier events from its own account/run. Entire run histories are generated in order, including cold starts. No scaling, weighting or fitting uses validation/test data. This measures future synthetic cohorts, not performance on recurring real customers.",
        "",
        "| Partition | Events | Fraud | Prevalence | Start | End |",
        "|---|---:|---:|---:|---|---|",
    ]
    for name, row in report["partitions"].items():
        lines.append(
            f"| {name} | {row['count']} | {row['fraud']} | {row['prevalence']:.2%} | {row['start']} | {row['end']} |"
        )
    lines += [
        "",
        "## Validation selection",
        "",
        "Candidates are standardized scikit-learn logistic classifiers with three regularization strengths and optional training-only class weighting. Select maximum validation combined-score precision subject to 80% recall; break candidate ties by lower Brier loss. Threshold ties favor recall then the higher threshold. The recall floor is a demo objective, not a real financial cost model. No test-based retuning or refit occurs.",
        "",
        "| Candidate | Precision | Recall | Threshold | Brier loss |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["candidates"]:
        val = row["validation"]
        lines.append(
            f"| {row['name']} | {val['precision']:.3f} | {val['recall']:.3f} | {val['threshold']} | {row['brier']:.4f} |"
        )
    lines += [
        "",
        f"Selected `{winner['name']}`; model version `{payload['model_version']}`.",
        "",
        "## Untouched later test period",
        "",
        "The validation recall floor is a selection constraint, not a test guarantee. "
        f"Combined test recall is {results['combined']['recall']:.1%} against the "
        f"{config['validation_recall_floor']:.0%} validation objective. "
        f"Rules select threshold {thresholds['rules_only']} and review "
        f"{results['rules_only']['alert_rate']:.1%} of test events. "
        f"The combined minus model-only precision difference is "
        f"{results['combined']['precision'] - results['model_only']['precision']:.4f}. "
        "Inspect these results before claiming that the target generalizes or that "
        "hybrid scoring adds useful value.",
        "",
        "Each approach's threshold was selected independently on validation under the same recall floor. The final score is rounded model probability × 100 plus rule adjustments capped at 40, capped overall at 100. That score is a ranking index, not a calibrated fraud probability. Rule signals describe rules and do not explain the classifier.",
        "",
        "| Approach | Threshold | Precision | Recall | False alerts | Total alerts | Alert rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in results.items():
        lines.append(
            f"| {name} | {row['threshold']} | {row['precision']:.3f} | {row['recall']:.3f} | {row['false_alerts']} | {row['alert_volume']} | {row['alert_rate']:.2%} |"
        )
    lines += [
        "",
        f"Model probability Brier loss: {report['test_model_brier']:.4f}; average precision: {report['test_average_precision']:.4f}. Brier loss is a calibration diagnostic, not a guarantee of calibrated probabilities. No separate probability calibrator was fitted.",
        "",
        f"A constant training-prevalence predictor has test Brier loss "
        f"{report['test_constant_prior_brier']:.4f}. Lower Brier loss is better. "
        "Class weighting changes the training prior; the selected classifier's "
        "raw probability outputs are uncalibrated. Model selection prioritized "
        "validation precision at the recall constraint, not calibration alone.",
        "",
        "## Combined threshold tradeoff (test; descriptive only)",
        "",
        "| Threshold | Precision | Recall | False alerts | Total alerts |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["combined_threshold_table"]:
        if row["threshold"] % 10 == 0 or row["threshold"] == payload["review_threshold"]:
            lines.append(
                f"| {row['threshold']} | {row['precision']:.3f} | {row['recall']:.3f} | {row['false_alerts']} | {row['alert_volume']} |"
            )
    lines += [
        "",
        "## Limitations and artifact",
        "",
        "Generator assumptions dominate these results. Labels overlap but lack realistic adversaries, merchant diversity, feedback delay or concept drift. No confidence interval or independent real-data validation is claimed. A combined approach may not outperform model-only; retain that evidence rather than changing the test-based decision. Run/account ID, seed, scenario, profile and label are excluded from the eight numeric model inputs.",
        "",
        "Only standardized logistic coefficients are exported as a small data-only JSON file. Runtime inference is checked against scikit-learn to 1e-12 on validation. A SHA-256 manifest detects accidental corruption, not a malicious replacement of both files. Startup validates feature/input/rule/formula versions and dimensions; loading does not execute pickle. Full configuration, environment and all 101 threshold rows are in `results.json`.",
        "",
        "API latency is measured separately by `training/benchmark.py` against the running API and PostgreSQL; see `latency.md` when available. Training runtime is not API latency.",
        "",
        "References: [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html), [held-out model selection](https://scikit-learn.org/stable/modules/grid_search.html), [model persistence](https://scikit-learn.org/stable/model_persistence.html).",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "selected": winner["name"],
                "model_version": payload["model_version"],
                "test": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
