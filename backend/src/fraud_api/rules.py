from fraud_api.contracts import Contract
from fraud_api.features import Features

RULE_VERSION = "rules-v1"


class RuleSignal(Contract):
    code: str
    message: str
    adjustment: int


def rule_signals(features: Features) -> list[RuleSignal]:
    signals: list[RuleSignal] = []
    if features.history_count < 5:
        signals.append(
            RuleSignal(
                code="LIMITED_HISTORY",
                message="Fewer than five earlier transactions are available.",
                adjustment=0,
            )
        )
    if features.history_count >= 5 and features.amount_ratio >= 4:
        signals.append(
            RuleSignal(
                code="AMOUNT_SPIKE",
                message="Amount is at least four times the earlier account average.",
                adjustment=20,
            )
        )
    if features.transactions_last_5m >= 3:
        signals.append(
            RuleSignal(
                code="RAPID_ACTIVITY",
                message="At least three earlier transactions occurred within five minutes.",
                adjustment=20,
            )
        )
    if features.distance_from_previous_km >= 100 and features.travel_speed_kmh > 1000:
        signals.append(
            RuleSignal(
                code="IMPOSSIBLE_TRAVEL",
                message="In-person locations imply travel faster than 1,000 km/h.",
                adjustment=30,
            )
        )
    if features.unusual_category:
        signals.append(
            RuleSignal(
                code="NEW_CATEGORY",
                message="Merchant category differs from all earlier account activity.",
                adjustment=10,
            )
        )
    if features.unusual_channel:
        signals.append(
            RuleSignal(
                code="NEW_CHANNEL",
                message="Channel differs from all earlier account activity.",
                adjustment=10,
            )
        )
    return signals


def rules_score(signals: list[RuleSignal]) -> int:
    return min(100, sum(signal.adjustment for signal in signals))
