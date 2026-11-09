"""Recall operating-point selection must not silently trade away precision."""

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from training.tune_recall import audit_gate, select_policy  # noqa: E402


def policy():
    return {
        "bootstrap_seed": 17,
        "bootstrap_repetitions": 100,
        "development_recall_target": 0.85,
        "development_recall_lower_bound": 0.8,
        "maximum_precision_loss": 0.02,
        "minimum_audit_precision": 0.75,
    }


def test_selection_finds_recall_margin_without_precision_loss():
    # Identical independent groups make the bootstrap bound easy to verify.
    labels = np.tile([1, 1, 1, 1, 1, 0], 10)
    scores = np.tile([90, 90, 90, 90, 30, 10], 10)
    data = {"y": labels, "group": np.repeat(np.arange(10), 6)}
    decision = select_policy(data, scores, 45, policy())
    assert decision["baseline"]["recall"] == 0.8
    assert decision["selected"]["threshold"] == 30
    assert decision["selected"]["precision"] == 1
    assert decision["selected"]["recall_lower_bound"] == 1


def test_selection_rejects_unacceptable_precision_loss():
    labels = np.tile([1, 1, 0, 0, 0], 10)
    scores = np.tile([90, 10, 40, 40, 40], 10)
    data = {"y": labels, "group": np.repeat(np.arange(10), 5)}
    with pytest.raises(ValueError, match="No threshold"):
        select_policy(data, scores, 45, policy())


@pytest.mark.parametrize(
    "precision,recall,passed",
    [(0.79, 0.81, True), (0.79, 0.8, False), (0.77, 0.9, False), (0.74, 0.9, False)],
)
def test_audit_gate_requires_strict_recall_and_precision_guard(precision, recall, passed):
    assert (
        audit_gate({"precision": 0.8}, {"precision": precision, "recall": recall}, policy())
        is passed
    )


def test_promoted_policy_preserves_weights_and_calibration():
    from fraud_api.artifacts import ARTIFACT_DIR, ModelArtifact, load_artifact

    output = Path(__file__).parents[2] / "docs/evaluation/recall-policy"
    prior = ModelArtifact.model_validate_json((output / "prior-model.json").read_bytes())
    promoted = load_artifact(ARTIFACT_DIR)
    excluded = {"model_version", "review_threshold"}
    assert prior.model_dump(exclude=excluded) == promoted.model_dump(exclude=excluded)
    decision = json.loads((output / "frozen-decision.json").read_text())
    assert promoted.review_threshold == decision["selected"]["threshold"]
    assert promoted.review_threshold < prior.review_threshold
