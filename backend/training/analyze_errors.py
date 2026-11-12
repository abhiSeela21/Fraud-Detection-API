"""Break down the frozen recall audit by scenario without training or tuning."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from fraud_api.artifacts import ModelArtifact  # noqa: E402
from training.data import dataset, metrics, summary  # noqa: E402
from training.train import vectors  # noqa: E402
from training.tune_recall import OUTPUT, source_hashes  # noqa: E402


def analyze():
    audit = json.loads((OUTPUT / "results.json").read_text())
    decision_raw = (OUTPUT / "frozen-decision.json").read_bytes()
    decision = json.loads(decision_raw)
    prior_raw = (OUTPUT / "prior-model.json").read_bytes()
    if (
        hashlib.sha256(decision_raw).hexdigest() != audit["frozen_decision_sha256"]
        or hashlib.sha256(prior_raw).hexdigest() != audit["prior_model_sha256"]
        or decision["source_sha256"] != source_hashes()
    ):
        raise ValueError("Audit inputs differ from the frozen evaluation")

    config = json.loads((ROOT / "training/improved_config.json").read_text())
    data = dataset({**config, **audit["policy"]}, "recall_audit")
    if summary(data) != audit["cohort"]:
        raise ValueError("Regenerated audit cohort does not match the published audit")

    prior = ModelArtifact.model_validate_json(prior_raw)
    probabilities = np.array([prior.probability(row.tolist()) for row in data["x"]])
    scores = vectors(probabilities, data["rules"])[1]
    for policy in ("baseline", "candidate"):
        expected = audit[policy]
        if metrics(data["y"], scores, expected["threshold"]) != expected:
            raise ValueError(f"Regenerated {policy} metrics do not match the published audit")

    rows = []
    for scenario in np.unique(data["scenario"]):
        mask = data["scenario"] == scenario
        labels, subset_scores = data["y"][mask], scores[mask]
        rows.append(
            {
                "scenario": str(scenario).replace("_", " "),
                "events": len(labels),
                "fraud": int(labels.sum()),
                "old": metrics(labels, subset_scores, audit["baseline"]["threshold"]),
                "new": metrics(labels, subset_scores, audit["candidate"]["threshold"]),
            }
        )
    return audit, rows


def render(audit, rows):
    old, new = audit["baseline"], audit["candidate"]
    old_threshold, new_threshold = old["threshold"], new["threshold"]
    top_misses = max(rows, key=lambda row: row["new"]["missed_fraud"])
    top_false = max(rows, key=lambda row: row["new"]["false_alerts"])
    lines = [
        "# Scoring errors by scenario",
        "",
        f"On the {audit['cohort']['count']:,}-transaction synthetic audit, "
        f"threshold {new_threshold} missed {new['missed_fraud']:,} fraud cases and raised "
        f"{new['false_alerts']:,} false alerts. "
        f"The **{top_misses['scenario']}** scenario contributed the most misses "
        f"({top_misses['new']['missed_fraud']:,}). "
        f"The **{top_false['scenario']}** scenario contributed the most false alerts "
        f"({top_false['new']['false_alerts']:,}).",
        "",
        f"The table compares cutoffs {old_threshold} and {new_threshold} using the same scores. "
        f"Rates are for threshold {new_threshold}. Miss rate divides missed fraud by fraud events. "
        "False alert rate divides false alerts by legitimate events.",
        "",
        f"| Scenario | Events | Fraud | Missed fraud ({old_threshold} → {new_threshold}) | "
        f"Miss rate | False alerts ({old_threshold} → {new_threshold}) | False alert rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        before, after = row["old"], row["new"]
        fraud, events = row["fraud"], row["events"]
        lines.append(
            f"| {row['scenario']} | {events:,} | {fraud:,} | "
            f"{before['missed_fraud']:,} → {after['missed_fraud']:,} | "
            f"{after['missed_fraud'] / fraud:.1%} | "
            f"{before['false_alerts']:,} → {after['false_alerts']:,} | "
            f"{after['false_alerts'] / (events - fraud):.2%} |"
        )
    lines += [
        f"| **All** | {audit['cohort']['count']:,} | {audit['cohort']['fraud']:,} | "
        f"{old['missed_fraud']:,} → {new['missed_fraud']:,} | {1 - new['recall']:.1%} | "
        f"{old['false_alerts']:,} → {new['false_alerts']:,} | "
        f"{new['false_alerts'] / (audit['cohort']['count'] - audit['cohort']['fraud']):.2%} |",
        "",
        "Scenario describes the entire simulation run. Even runs labeled normal can contain "
        "randomly assigned background fraud labels. Those labels can lack observable warning "
        "signals. The counts describe this synthetic cohort and depend on its scenario mix "
        "and label assumptions.",
        "",
        "From `backend/`, run `uv run --group training python training/analyze_errors.py` "
        "to regenerate this report. The script checks the frozen inputs, cohort fingerprint, "
        "and aggregate metrics against the [published audit](report.md).",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the saved report")
    args = parser.parse_args()
    report = render(*analyze())
    output = OUTPUT / "scenario-errors.md"
    if args.check:
        if output.read_text() != report:
            raise SystemExit("Scenario report differs from regenerated results")
    else:
        output.write_text(report)
    print("Scenario breakdown verified against the frozen audit")


if __name__ == "__main__":
    main()
