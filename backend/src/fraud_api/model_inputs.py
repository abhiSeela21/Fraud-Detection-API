"""Stable model input order shared by training and inference; no scenario/label inputs."""

import math

from fraud_api.contracts import Transaction
from fraud_api.features import Features

INPUT_NAMES = [
    "log_amount",
    "log_amount_ratio",
    "log_history_count",
    "transactions_last_5m",
    "log_distance_km",
    "log_travel_speed_kmh",
    "unusual_category",
    "unusual_channel",
]
INPUT_VERSION = "model-inputs-v1"


def model_inputs(transaction: Transaction, features: Features) -> list[float]:
    return [
        math.log1p(float(transaction.amount)),
        math.log1p(features.amount_ratio),
        math.log1p(features.history_count),
        float(features.transactions_last_5m),
        math.log1p(features.distance_from_previous_km),
        math.log1p(features.travel_speed_kmh),
        float(features.unusual_category),
        float(features.unusual_channel),
    ]
