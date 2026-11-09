"""Select on development, freeze, audit once, then promote only if gates pass."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from fraud_api.artifacts import ARTIFACT_DIR, ModelArtifact  # noqa: E402
from training.data import dataset, metrics, summary  # noqa: E402
from training.train import bootstrap, vectors  # noqa: E402

OUTPUT = ROOT.parent / "docs/evaluation/recall-policy"


def source_hashes():
    files = [
        "training/data.py",
        "training/train.py",
        *[
            f"src/fraud_api/{name}.py"
            for name in ["features", "model_inputs", "rules", "formula", "simulation", "artifacts"]
        ],
    ]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}


class PolicyInfeasible(ValueError):
    def __init__(self, diagnostic):
        super().__init__(
            "No threshold meets the frozen recall and precision constraints; no promotion"
        )
        self.diagnostic = diagnostic


def select_policy(data, scores, old_threshold, policy):
    baseline = metrics(data["y"], scores, old_threshold)
    minimum_precision = baseline["precision"] - policy["maximum_precision_loss"]
    groups, inverse = np.unique(data["group"], return_inverse=True)
    rng = np.random.default_rng(policy["bootstrap_seed"])
    samples = rng.integers(0, len(groups), size=(policy["bootstrap_repetitions"], len(groups)))
    positives = np.bincount(inverse, weights=data["y"], minlength=len(groups))
    denominators = positives[samples].sum(axis=1)
    if np.any(denominators == 0):
        raise ValueError("Recall uncertainty cannot be estimated from zero-fraud resamples")
    table = []
    for threshold in range(101):
        row = metrics(data["y"], scores, threshold)
        true_positives = np.bincount(
            inverse, weights=(data["y"] == 1) & (scores >= threshold), minlength=len(groups)
        )
        recalls = true_positives[samples].sum(axis=1) / denominators
        row["recall_lower_bound"] = float(np.quantile(recalls, 0.025))
        table.append(row)
    feasible = [
        row
        for row in table
        if row["recall"] >= policy["development_recall_target"]
        and row["recall_lower_bound"] >= policy["development_recall_lower_bound"]
        and row["precision"] >= minimum_precision
    ]
    if not feasible:
        raise PolicyInfeasible(
            {"baseline": baseline, "minimum_precision": minimum_precision, "threshold_table": table}
        )
    selected = max(feasible, key=lambda row: (row["precision"], row["recall"], row["threshold"]))
    return {
        "baseline": baseline,
        "minimum_precision": minimum_precision,
        "selected": selected,
        "threshold_table": table,
    }


def audit_gate(baseline, candidate, policy):
    return (
        candidate["recall"] > 0.8
        and candidate["precision"] >= policy["minimum_audit_precision"]
        and candidate["precision"] >= baseline["precision"] - policy["maximum_precision_loss"]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    policy = json.loads((ROOT / "training/recall_policy.json").read_text())
    config = json.loads((ROOT / "training/improved_config.json").read_text())
    raw = (OUTPUT / "prior-model.json").read_bytes()
    prior = ModelArtifact.model_validate_json(raw)
    model_hash = hashlib.sha256(raw).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps({"policy": policy, "data": config}, sort_keys=True).encode()
    ).hexdigest()
    if args.select_only:
        development = dataset({**config, "threshold_runs": policy["development_runs"]}, "threshold")
        probabilities = np.array([prior.probability(row.tolist()) for row in development["x"]])
        scores = vectors(probabilities, development["rules"])[1]
        try:
            decision = select_policy(development, scores, prior.review_threshold, policy)
        except PolicyInfeasible as exc:
            (OUTPUT / f"selection-failure-{policy['development_runs']}.json").write_text(
                json.dumps(
                    {
                        "policy": policy,
                        "cohort": summary(development),
                        **exc.diagnostic,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            raise
        decision.update(
            policy=policy,
            config_sha256=config_hash,
            prior_model_sha256=model_hash,
            cohort=summary(development),
            selector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            source_sha256=source_hashes(),
        )
        (OUTPUT / "frozen-decision.json").write_text(
            json.dumps(decision, indent=2, sort_keys=True) + "\n"
        )
        print(
            json.dumps(
                {"baseline": decision["baseline"], "selected": decision["selected"]}, indent=2
            )
        )
        return
    decision = json.loads((OUTPUT / "frozen-decision.json").read_text())
    if (
        decision["config_sha256"] != config_hash
        or decision["prior_model_sha256"] != model_hash
        or decision["selector_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or decision["source_sha256"] != source_hashes()
    ):
        raise ValueError("Frozen policy, selector or source model changed")
    # Fresh audit data is created only after the operating point is frozen on disk.
    audit = dataset({**config, **policy}, "recall_audit")
    if decision["cohort"]["end"] >= audit["start"]:
        raise ValueError("Audit must occur after development")
    p = np.array([prior.probability(row.tolist()) for row in audit["x"]])
    scores = vectors(p, audit["rules"])[1]
    threshold = decision["selected"]["threshold"]
    baseline = metrics(audit["y"], scores, prior.review_threshold)
    candidate = metrics(audit["y"], scores, threshold)
    passed = audit_gate(baseline, candidate, policy)
    intervals = {
        name: bootstrap(audit, scores, t, policy["bootstrap_repetitions"], policy["bootstrap_seed"])
        for name, t in [("baseline", prior.review_threshold), ("candidate", threshold)]
    }
    report = {
        "policy": policy,
        "cohort": summary(audit),
        "baseline": baseline,
        "candidate": candidate,
        "intervals": intervals,
        "promotion_passed": passed,
        "prior_model_sha256": model_hash,
        "frozen_decision_sha256": hashlib.sha256(
            (OUTPUT / "frozen-decision.json").read_bytes()
        ).hexdigest(),
    }
    if passed:
        payload = prior.model_dump()
        payload["review_threshold"] = threshold
        payload["model_version"] = f"model-v2-recall-{report['frozen_decision_sha256'][:12]}"
        promoted = ModelArtifact.model_validate(payload)
        promoted_raw = (
            json.dumps(promoted.model_dump(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        (ARTIFACT_DIR / "model.json").write_bytes(promoted_raw)
        (ARTIFACT_DIR / "manifest.json").write_text(
            json.dumps(
                {
                    "model_version": promoted.model_version,
                    "sha256": hashlib.sha256(promoted_raw).hexdigest(),
                },
                indent=2,
            )
            + "\n"
        )
        report["promoted_model_version"] = promoted.model_version
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Recall policy audit",
        "",
        "Synthetic data only; no real-world performance claim.",
        "",
        "## Selection boundary",
        "",
        "Weights, features, calibration and label assumptions are unchanged. The 2028 results were inspected previously and were not used to pick this threshold. "
        f"The expanded 2027 development cohort selects the maximum-precision threshold satisfying {policy['development_recall_target']:.0%} point recall, "
        f"a run-cluster bootstrap lower recall bound of {policy['development_recall_lower_bound']:.0%}, "
        "and precision within two percentage points of the original policy. The initial stricter 85% attempt failed on development; its evidence is preserved. "
        "The revised decision was saved before generating the new 2029 audit cohort.",
        "",
        f"Selected threshold: **{threshold}**. Development precision **{decision['selected']['precision']:.2%}**, recall **{decision['selected']['recall']:.2%}**, recall lower bound **{decision['selected']['recall_lower_bound']:.2%}**.",
        "",
        f"Fresh audit: **{len(audit['y']):,} events**, **{len(np.unique(audit['group']))} runs**, **{sum(audit['y']):,} fraud labels**. The same events and scores are compared at both thresholds.",
        "",
        "| Policy | Threshold | Precision | Recall | False alerts | Missed fraud | Total reviews |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in [("Previous", baseline), ("Recall-focused", candidate)]:
        lines.append(
            f"| {name} | {row['threshold']} | {row['precision']:.2%} | {row['recall']:.2%} | {row['false_alerts']} | {row['missed_fraud']} | {row['alert_volume']} |"
        )
    lines += [
        "",
        f"Promotion gate **{'passed' if passed else 'failed'}**: audit recall strictly above 80%, precision at least 75%, and precision loss at most two percentage points versus the previous policy on this same cohort. No audit-based retuning follows a failed gate.",
        "",
        "## Uncertainty and limits",
        "",
        "Approximate 95% run-cluster bootstrap intervals; 1,000 whole-run resamples preserve sequential dependence. Development threshold search means these empirical intervals are not a formal guarantee of future recall. Audit intervals exclude model-selection and real-world distribution uncertainty.",
        "",
        "| Policy | Precision interval | Recall interval |",
        "|---|---|---|",
    ]
    for name, row in intervals.items():
        lines.append(
            f"| {name} | {row['precision'][0]:.2%}–{row['precision'][1]:.2%} | {row['recall'][0]:.2%}–{row['recall'][1]:.2%} |"
        )
    lines += [
        "",
        "The generator remains limited and periodic. This audit measures an operating-point tradeoff, not a newly trained model. All prior v2 evidence remains intact. Stored scores are immutable and retain their original threshold/version.",
        "",
        "## Reproduce",
        "",
        "From `backend/`: `uv run --group training python training/tune_recall.py --select-only`, then `uv run --group training python training/tune_recall.py`. The preserved `prior-model.json` anchors the original weights and threshold so reruns do not tune against an already-promoted model. Retraining v2 with `training/train.py` restores its original policy; run these two policy commands afterward to reproduce the promoted policy.",
        "",
    ]
    (OUTPUT / "report.md").write_text("\n".join(lines))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
