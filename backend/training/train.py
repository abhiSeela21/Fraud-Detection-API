"""Chronological model improvement, frozen threshold selection and final evaluation."""

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from fraud_api.artifacts import ARTIFACT_DIR, ModelArtifact  # noqa: E402
from fraud_api.features import FEATURE_VERSION  # noqa: E402
from fraud_api.formula import SCORING_VERSION, combined_score  # noqa: E402
from fraud_api.model_inputs import INPUT_NAMES, INPUT_VERSION  # noqa: E402
from fraud_api.rules import RULE_VERSION  # noqa: E402
from training.data import dataset as dataset  # noqa: E402
from training.data import metrics, summary  # noqa: E402
from training.data import select_threshold as select_threshold  # noqa: E402


def source_hashes():
    files = [
        "training/train.py",
        "training/data.py",
        "training/report.py",
        *[
            f"src/fraud_api/{name}.py"
            for name in ["features", "model_inputs", "artifacts", "formula", "rules", "simulation"]
        ],
    ]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}


def logits(probabilities):
    p = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def vectors(probabilities, rules):
    return np.rint(100 * probabilities).astype(int), np.array(
        [combined_score(float(p), int(r)) for p, r in zip(probabilities, rules, strict=True)]
    )


def export(estimator, calibrator, threshold):
    payload = {
        "format": "calibrated-forest-v1",
        "model_version": "pending",
        "feature_version": FEATURE_VERSION,
        "input_version": INPUT_VERSION,
        "rule_version": RULE_VERSION,
        "scoring_version": SCORING_VERSION,
        "input_names": INPUT_NAMES,
        "review_threshold": threshold,
        "calibration_slope": float(calibrator.coef_[0, 0]),
        "calibration_intercept": float(calibrator.intercept_[0]),
    }
    if hasattr(estimator, "estimators_"):
        payload["trees"] = []
        for item in estimator.estimators_:
            tree = item.tree_
            values = tree.value[:, 0, :]
            payload["trees"].append(
                {
                    "left": tree.children_left.tolist(),
                    "right": tree.children_right.tolist(),
                    "feature": tree.feature.tolist(),
                    "threshold": tree.threshold.tolist(),
                    "probability": (values[:, 1] / values.sum(axis=1)).tolist(),
                }
            )
    else:
        scaler, classifier = estimator.steps[0][1], estimator.steps[1][1]
        payload.update(
            format="standardized-logistic-v2",
            means=scaler.mean_.tolist(),
            scales=scaler.scale_.tolist(),
            coefficients=classifier.coef_[0].tolist(),
            intercept=float(classifier.intercept_[0]),
        )
    return payload


def breakdown(data, scores, threshold, field):
    return {
        str(value): {
            "events": int(sum(data[field] == value)),
            "fraud": int(sum(data["y"][data[field] == value])),
            **metrics(data["y"][data[field] == value], scores[data[field] == value], threshold),
        }
        for value in np.unique(data[field])
    }


def calibration_bins(labels, probabilities):
    result = []
    edges = np.linspace(0.0, 1.0, 11)
    assigned = np.clip(np.searchsorted(edges, probabilities, side="right") - 1, 0, 9)
    for index, lower in enumerate(edges[:-1]):
        mask = assigned == index
        if mask.any():
            result.append(
                {
                    "lower": float(lower),
                    "count": int(sum(mask)),
                    "mean_probability": float(np.mean(probabilities[mask])),
                    "observed_fraud_rate": float(np.mean(labels[mask])),
                }
            )
    return result


def bootstrap(data, scores, threshold, repetitions, seed):
    rng = np.random.default_rng(seed)
    groups = np.unique(data["group"])
    samples = []
    for _ in range(repetitions):
        selected = rng.choice(groups, size=len(groups), replace=True)
        indices = np.concatenate([np.flatnonzero(data["group"] == g) for g in selected])
        row = metrics(data["y"][indices], scores[indices], threshold)
        samples.append([row["precision"], row["recall"], row["alert_rate"]])
    intervals = np.quantile(np.array(samples), [0.025, 0.975], axis=0)
    return {
        name: intervals[:, i].tolist()
        for i, name in enumerate(["precision", "recall", "alert_rate"])
    }


def historical_scores(data):
    old = json.loads((ROOT.parent / "docs/evaluation/baseline-v1/model.json").read_text())
    z = old["intercept"] + (
        (data["legacy_x"] - np.array(old["means"])) / np.array(old["scales"])
    ) @ np.array(old["coefficients"])
    p = np.array([1 / (1 + math.exp(-v)) if v >= 0 else math.exp(v) / (1 + math.exp(v)) for v in z])
    return vectors(p, data["rules"])[1], old["review_threshold"]


def develop(config):
    parts = {
        name: dataset(config, name)
        for name in ["training", "calibration", "selection", "threshold"]
    }
    ordered = list(parts.values())
    assert all(a["end"] < b["start"] for a, b in zip(ordered, ordered[1:], strict=False))
    train, calibration, selection, threshold_data = ordered
    estimators = []
    for c in config["logistic_candidates"]:
        for weight in [None, "balanced"]:
            estimators.append(
                (
                    f"logistic-C={c}-weight={weight}",
                    make_pipeline(
                        StandardScaler(),
                        LogisticRegression(
                            C=c, class_weight=weight, max_iter=2000, random_state=config["seed"]
                        ),
                    ),
                )
            )
    for depth in config["forest_depth_candidates"]:
        estimators.append(
            (
                f"forest-depth={depth}",
                RandomForestClassifier(
                    n_estimators=config["forest_trees"],
                    max_depth=depth,
                    min_samples_leaf=config["forest_min_samples_leaf"],
                    max_features=1.0,
                    random_state=config["seed"],
                    n_jobs=1,
                ),
            )
        )
    candidates = []
    for name, estimator in estimators:
        estimator.fit(train["x"], train["y"])
        calibrator = LogisticRegression(C=1e6, max_iter=1000, random_state=config["seed"])
        calibrator.fit(logits(estimator.predict_proba(calibration["x"])[:, 1]), calibration["y"])
        raw = estimator.predict_proba(selection["x"])[:, 1]
        p = calibrator.predict_proba(logits(raw))[:, 1]
        _, combined = vectors(p, selection["rules"])
        metric = select_threshold(selection["y"], combined, config["validation_recall_floor"])
        artifact = ModelArtifact.model_validate(export(estimator, calibrator, metric["threshold"]))
        exported = np.array([artifact.probability(row.tolist()) for row in selection["x"]])
        np.testing.assert_allclose(exported, p, atol=1e-12, rtol=0)
        row = {
            "name": name,
            "selection": metric,
            "raw_brier": float(brier_score_loss(selection["y"], raw)),
            "calibrated_brier": float(brier_score_loss(selection["y"], p)),
            "average_precision": float(average_precision_score(selection["y"], p)),
            "scenario_errors": breakdown(selection, combined, metric["threshold"], "scenario"),
            "payload": artifact.model_dump(),
        }
        candidates.append(row)
        print(
            json.dumps({k: v for k, v in row.items() if k not in {"payload", "scenario_errors"}}),
            flush=True,
        )
    winner = max(candidates, key=lambda r: (r["selection"]["precision"], -r["calibrated_brier"]))
    artifact = ModelArtifact.model_validate(winner["payload"])
    p = np.array([artifact.probability(row.tolist()) for row in threshold_data["x"]])
    model, combined = vectors(p, threshold_data["rules"])
    thresholds = {
        "model_only": select_threshold(
            threshold_data["y"], model, config["validation_recall_floor"]
        )["threshold"],
        "combined": select_threshold(
            threshold_data["y"], combined, config["validation_recall_floor"]
        )["threshold"],
        "rules_only": select_threshold(
            threshold_data["y"], threshold_data["rules"], config["validation_recall_floor"]
        )["threshold"],
    }
    payload = {**winner["payload"], "review_threshold": thresholds["combined"]}
    digest = hashlib.sha256(
        json.dumps({"config": config, "payload": payload}, sort_keys=True).encode()
    ).hexdigest()
    payload["model_version"] = f"model-v2-{digest[:12]}"
    development = {
        "config": config,
        "winner": winner["name"],
        "model_version": payload["model_version"],
        "partitions": {name: summary(data) for name, data in parts.items()},
        "candidates": [{k: v for k, v in r.items() if k != "payload"} for r in candidates],
        "thresholds": thresholds,
        "threshold_metrics": metrics(threshold_data["y"], combined, thresholds["combined"]),
        "environment": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
        },
    }
    development["source_sha256"] = source_hashes()
    return payload, development


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-only", action="store_true")
    parser.add_argument("--evaluate-frozen", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "training/improved_config.json").read_text())
    output = ROOT.parent / "docs/evaluation"
    if args.evaluate_frozen:
        payload = json.loads((ARTIFACT_DIR / "model.json").read_text())
        development = json.loads((output / "development.json").read_text())
        if development["config"] != config:
            raise ValueError("Frozen development configuration changed")
        if development["source_sha256"] != source_hashes():
            raise ValueError("Frozen training/evaluation/inference source changed")
    else:
        payload, development = develop(config)
        raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "model.json").write_bytes(raw)
        manifest = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "model_version": payload["model_version"],
        }
        (ARTIFACT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        development["artifact_sha256"] = manifest["sha256"]
        (output / "development.json").write_text(
            json.dumps(development, indent=2, sort_keys=True) + "\n"
        )
    if args.development_only:
        print("Development frozen; final_test has not been generated.")
        return
    from training.report import evaluate

    evaluate(config, development, payload, output)


if __name__ == "__main__":
    main()
