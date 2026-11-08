"""Training checks are enabled with `uv sync --group training`."""

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from training.train import dataset, export, logits, select_threshold  # noqa: E402  # noqa: E402


def test_threshold_selection_uses_recall_constraint():
    labels = np.array([0, 1, 1, 0])
    scores = np.array([1, 60, 80, 70])
    assert select_threshold(labels, scores, 1.0)["threshold"] == 60
    assert select_threshold(labels, scores, 0.5)["threshold"] == 80


def test_later_partition_changes_cannot_affect_training_features_or_labels():
    config = json.loads((Path(__file__).parents[1] / "training/config.json").read_text())
    config.update(training_runs=3, validation_runs=3, test_runs=3, transactions_per_run=30)
    original = dataset(config, "training")
    modified = dataset({**config, "test_start": "2027-01-01T00:00:00+00:00"}, "training")
    np.testing.assert_array_equal(original["x"], modified["x"])
    np.testing.assert_array_equal(original["y"], modified["y"])
    validation = dataset(config, "validation")
    test = dataset(config, "test")
    assert original["end"] < validation["start"] < validation["end"] < test["start"]


def test_small_forest_export_matches_sklearn_with_calibration():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    from fraud_api.artifacts import ModelArtifact
    from fraud_api.model_inputs import INPUT_NAMES

    rng = np.random.default_rng(17)
    x = rng.normal(size=(300, len(INPUT_NAMES)))
    y = ((x[:, 0] > 0) & (x[:, 1] < 0)).astype(int)
    model = RandomForestClassifier(n_estimators=4, max_depth=3, random_state=17).fit(
        x[:100], y[:100]
    )
    calibrator = LogisticRegression(C=1e6).fit(
        logits(model.predict_proba(x[100:200])[:, 1]), y[100:200]
    )
    artifact = ModelArtifact.model_validate(export(model, calibrator, 50))
    actual = [artifact.probability(row.tolist()) for row in x[200:]]
    expected = calibrator.predict_proba(logits(model.predict_proba(x[200:])[:, 1]))[:, 1]
    np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)
