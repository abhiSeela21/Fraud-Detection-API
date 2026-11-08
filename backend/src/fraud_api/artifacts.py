"""Validate and execute bounded data-only models. No pickle or sklearn at runtime."""

import hashlib
import json
import math
import struct
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fraud_api.features import FEATURE_VERSION
from fraud_api.formula import SCORING_VERSION
from fraud_api.model_inputs import INPUT_NAMES, INPUT_VERSION
from fraud_api.rules import RULE_VERSION

ARTIFACT_DIR = Path(__file__).resolve().parent / "model_artifact"
Finite = Annotated[float, Field(allow_inf_nan=False)]


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


class Tree(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    left: list[int]
    right: list[int]
    feature: list[int]
    threshold: list[Finite]
    probability: list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]]

    @model_validator(mode="after")
    def valid_tree(self) -> "Tree":
        size = len(self.left)
        if not 1 <= size <= 2047 or any(
            length != size
            for length in (
                len(self.right),
                len(self.feature),
                len(self.threshold),
                len(self.probability),
            )
        ):
            raise ValueError("Invalid tree dimensions")
        for node in range(size):
            if self.left[node] == self.right[node] == -1:
                continue
            if not (
                node < self.left[node] < size
                and node < self.right[node] < size
                and 0 <= self.feature[node] < len(INPUT_NAMES)
            ):
                raise ValueError("Invalid tree topology or feature")
        return self

    def predict(self, values: list[float]) -> float:
        node = 0
        while self.left[node] != -1:
            node = (
                self.left[node]
                if values[self.feature[node]] <= self.threshold[node]
                else self.right[node]
            )
        return self.probability[node]


class ModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["standardized-logistic-v2", "calibrated-forest-v1"]
    model_version: str
    feature_version: Literal["features-v2"]
    input_version: Literal["model-inputs-v2"]
    rule_version: Literal["rules-v1"]
    scoring_version: Literal["combined-v1"]
    input_names: list[str]
    means: list[Finite] = []
    scales: list[Finite] = []
    coefficients: list[Finite] = []
    intercept: Finite = 0
    trees: Annotated[list[Tree], Field(max_length=128)] = []
    calibration_slope: Finite
    calibration_intercept: Finite
    review_threshold: Annotated[int, Field(ge=0, le=100)]

    @model_validator(mode="after")
    def compatible(self) -> "ModelArtifact":
        if self.input_names != INPUT_NAMES:
            raise ValueError("Incompatible model input schema")
        if (self.feature_version, self.input_version, self.rule_version, self.scoring_version) != (
            FEATURE_VERSION,
            INPUT_VERSION,
            RULE_VERSION,
            SCORING_VERSION,
        ):
            raise ValueError("Incompatible scoring code version")
        if self.format == "standardized-logistic-v2":
            if (
                any(
                    len(v) != len(INPUT_NAMES) for v in [self.means, self.scales, self.coefficients]
                )
                or any(s <= 0 for s in self.scales)
                or self.trees
            ):
                raise ValueError("Incompatible logistic dimensions")
        elif not self.trees or self.coefficients or self.means or self.scales:
            raise ValueError("Invalid forest dimensions")
        return self

    def raw_probability(self, values: list[float]) -> float:
        if len(values) != len(INPUT_NAMES) or not all(math.isfinite(v) for v in values):
            raise ValueError("Invalid model inputs")
        if self.format == "calibrated-forest-v1":
            quantized = [struct.unpack("f", struct.pack("f", value))[0] for value in values]
            return sum(tree.predict(quantized) for tree in self.trees) / len(self.trees)
        logit = self.intercept + sum(
            w * (v - m) / s
            for v, m, s, w in zip(
                values,
                self.means,
                self.scales,
                self.coefficients,
                strict=True,
            )
        )
        return sigmoid(logit)

    def probability(self, values: list[float]) -> float:
        p = max(1e-6, min(1 - 1e-6, self.raw_probability(values)))
        return sigmoid(self.calibration_slope * math.log(p / (1 - p)) + self.calibration_intercept)


def load_artifact(directory: Path) -> ModelArtifact:
    raw = (directory / "model.json").read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("Model exceeds artifact size budget")
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
    except (OSError, ValueError, KeyError) as exc:
        from fraud_api.errors import ApiError

        raise ApiError(
            503, "MODEL_UNAVAILABLE", "Verified scoring artifact is unavailable"
        ) from exc
