"""Training checks are enabled with `uv sync --group training`."""

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from training.train import dataset, select_threshold  # noqa: E402


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
