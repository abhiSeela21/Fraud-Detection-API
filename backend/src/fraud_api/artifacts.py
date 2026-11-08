"""Load data-only logistic coefficients; no pickle/joblib execution at startup."""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fraud_api.features import FEATURE_VERSION
from fraud_api.formula import SCORING_VERSION
from fraud_api.model_inputs import INPUT_NAMES, INPUT_VERSION
from fraud_api.rules import RULE_VERSION

ARTIFACT_DIR = Path(__file__).resolve().parent / "model_artifact"
Finite = Annotated[float, Field(allow_inf_nan=False)]


class ModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["standardized-logistic-v1"]
    model_version: str
    feature_version: Literal["features-v1"]
    input_version: Literal["model-inputs-v1"]
    rule_version: Literal["rules-v1"]
    scoring_version: Literal["combined-v1"]
    input_names: list[str]
    means: list[Finite]
    scales: list[Finite]
    coefficients: list[Finite]
    intercept: Finite
    review_threshold: Annotated[int, Field(ge=0, le=100)]

    @model_validator(mode="after")
    def compatible(self) -> "ModelArtifact":
        if (
            self.input_names != INPUT_NAMES
            or any(
                len(values) != len(INPUT_NAMES)
                for values in [self.means, self.scales, self.coefficients]
            )
            or any(scale <= 0 for scale in self.scales)
        ):
            raise ValueError("Incompatible model input schema")
        if (self.feature_version, self.input_version, self.rule_version) != (
            FEATURE_VERSION,
            INPUT_VERSION,
            RULE_VERSION,
        ):
            raise ValueError("Incompatible scoring code version")
        if self.scoring_version != SCORING_VERSION:
            raise ValueError("Incompatible formula version")
        return self

    def probability(self, values: list[float]) -> float:
        if len(values) != len(self.coefficients) or not all(math.isfinite(v) for v in values):
            raise ValueError("Invalid model inputs")
        logit = self.intercept + sum(
            weight * (value - mean) / scale
            for value, mean, scale, weight in zip(
                values,
                self.means,
                self.scales,
                self.coefficients,
                strict=True,
            )
        )
        # Stable sigmoid, including extreme synthetic amounts/velocities.
        return 1 / (1 + math.exp(-logit)) if logit >= 0 else math.exp(logit) / (1 + math.exp(logit))


def load_artifact(directory: Path) -> ModelArtifact:
    raw = (directory / "model.json").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text())
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Model checksum mismatch")
    model = ModelArtifact.model_validate_json(raw)
    if manifest["model_version"] != model.model_version:
        raise ValueError("Model version mismatch")
    return model


@lru_cache(maxsize=1)
def verified_artifact() -> ModelArtifact:
    from fraud_api.config import get_settings

    try:
        return load_artifact(get_settings().model_directory)
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        from fraud_api.errors import ApiError

        raise ApiError(
            503, "MODEL_UNAVAILABLE", "Verified scoring artifact is unavailable"
        ) from exc
