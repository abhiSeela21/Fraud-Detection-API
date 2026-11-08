from collections.abc import Iterable
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from fraud_api.contracts import Contract, Transaction
from fraud_api.errors import ApiError
from fraud_api.features import FEATURE_VERSION, Features, calculate_features
from fraud_api.rules import RULE_VERSION, RuleSignal, rule_signals, rules_score

SCORING_VERSION = "combined-v1"


class Prediction(Contract):
    probability: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    review_threshold: Annotated[int, Field(ge=0, le=100)]
    model_version: str


class ScoreResult(Contract):
    transaction_id: UUID
    client_transaction_id: UUID
    risk_score: int
    recommendation: Literal["clear", "review"]
    rule_signals: list[RuleSignal]
    rule_score: int
    rule_adjustment: int
    model_probability: float
    review_threshold: int
    features: Features
    model_version: str
    feature_version: str = FEATURE_VERSION
    rule_version: str = RULE_VERSION
    scoring_version: str = SCORING_VERSION
    alert_id: UUID | None


class Scorer:
    def predict(self, transaction: Transaction, features: Features) -> Prediction:
        # Replaced by the verified artifact loader in the model milestone.
        raise ApiError(503, "MODEL_UNAVAILABLE", "A verified scoring model is not available")

    def score(
        self, transaction: Transaction, history: Iterable[Transaction], transaction_id: UUID
    ) -> ScoreResult:
        features = calculate_features(transaction, history)
        prediction = self.predict(transaction, features)
        signals = rule_signals(features)
        baseline = rules_score(signals)
        adjustment = min(40, baseline)
        score = min(100, round(prediction.probability * 100) + adjustment)
        return ScoreResult(
            transaction_id=transaction_id,
            client_transaction_id=transaction.client_transaction_id,
            risk_score=score,
            recommendation="review" if score >= prediction.review_threshold else "clear",
            rule_signals=signals,
            rule_score=baseline,
            rule_adjustment=adjustment,
            model_probability=prediction.probability,
            review_threshold=prediction.review_threshold,
            features=features,
            model_version=prediction.model_version,
            alert_id=None,
        )


def get_scorer() -> Scorer:
    return Scorer()
