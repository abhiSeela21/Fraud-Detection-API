import hashlib
import json
from uuid import UUID

import pytest

from fraud_api.artifacts import ARTIFACT_DIR, load_artifact, verified_artifact
from fraud_api.features import calculate_features
from fraud_api.model_inputs import model_inputs
from fraud_api.scoring import Scorer
from fraud_api.simulation import SimulationConfig, generate_transaction


def test_artifact_scores_deterministically_with_real_model():
    config = SimulationConfig(run_id=UUID(int=42))
    history = [generate_transaction(config, i) for i in range(19)]
    current = generate_transaction(config, 19)
    scorer = Scorer()
    score = scorer.score(current, history, UUID(int=1))
    assert score == scorer.score(current, reversed(history), UUID(int=1))
    assert score.model_version.startswith("logistic-v1-")
    assert 0 <= score.model_probability <= 1
    assert score.recommendation == "review"
    future = generate_transaction(config, 40)
    assert score == scorer.score(current, [*history, future], UUID(int=1))


def test_corrupt_artifact_is_rejected(tmp_path):
    for name in ["model.json", "manifest.json"]:
        (tmp_path / name).write_bytes((ARTIFACT_DIR / name).read_bytes())
    (tmp_path / "model.json").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(tmp_path)


def test_incompatible_schema_rejected_even_with_matching_checksum(tmp_path):
    payload = json.loads((ARTIFACT_DIR / "model.json").read_text())
    payload["input_names"] = list(reversed(payload["input_names"]))
    raw = json.dumps(payload).encode()
    (tmp_path / "model.json").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "model_version": payload["model_version"],
            }
        )
    )
    with pytest.raises(ValueError, match="schema"):
        load_artifact(tmp_path)


def test_model_handles_extreme_finite_inputs():
    config = SimulationConfig(run_id=UUID(int=42))
    transaction = generate_transaction(config, 0)
    features = calculate_features(transaction, [])
    artifact = verified_artifact()
    values = model_inputs(transaction, features)
    values[5] = 1000000.0
    assert 0 <= artifact.probability(values) <= 1
