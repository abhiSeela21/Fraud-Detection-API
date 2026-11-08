"""Stable model input order shared by training and inference; no scenario/label inputs."""

import math

from fraud_api.contracts import Transaction
from fraud_api.features import Features

INPUT_NAMES = [
    "log_amount",
    "log_amount_ratio",
    "has_history",
    "transactions_last_5m",
    "log_distance_km",
    "log_travel_speed_kmh",
    "unusual_category",
    "unusual_channel",
    "log_amount_to_median",
    "category_frequency",
    "channel_frequency",
    "log_seconds_since_previous",
    "is_online",
]
INPUT_VERSION = "model-inputs-v2"


def model_inputs(transaction: Transaction, features: Features) -> list[float]:
    return [
        math.log1p(float(transaction.amount)),
        math.log1p(features.amount_ratio),
        float(features.history_count > 0),
        float(features.transactions_last_5m),
        math.log1p(features.distance_from_previous_km),
        math.log1p(features.travel_speed_kmh),
        float(features.unusual_category),
        float(features.unusual_channel),
        math.log1p(features.amount_to_median),
        features.category_frequency,
        features.channel_frequency,
        math.log1p(features.seconds_since_previous),
        float(transaction.channel == "online"),
    ]
