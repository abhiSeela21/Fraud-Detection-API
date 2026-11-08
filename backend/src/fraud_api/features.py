"""Event-time features shared by offline evaluation and online scoring."""

import math
from collections.abc import Iterable
from datetime import timedelta
from statistics import mean, median

from fraud_api.contracts import Contract, Location, Transaction

FEATURE_VERSION = "features-v2"


class Features(Contract):
    history_count: int
    amount_ratio: float
    transactions_last_5m: int
    distance_from_previous_km: float
    travel_speed_kmh: float
    unusual_category: bool
    unusual_channel: bool
    amount_to_median: float
    category_frequency: float
    channel_frequency: float
    seconds_since_previous: float


def distance_km(a: Location, b: Location) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def calculate_features(current: Transaction, history: Iterable[Transaction]) -> Features:
    # Same-time/future events, other accounts and other simulation runs are excluded.
    prior = sorted(
        (
            item
            for item in history
            if item.account_id == current.account_id
            and item.run_id == current.run_id
            and item.timestamp < current.timestamp
        ),
        key=lambda item: (item.timestamp, str(item.client_transaction_id)),
    )
    enough = len(prior) >= 5
    distance = 0.0
    speed = 0.0
    # Online purchases do not establish physical travel.
    physical = [item for item in prior if item.channel == "in_person"]
    if current.channel == "in_person" and physical:
        previous = physical[-1]
        distance = distance_km(previous.location, current.location)
        hours = (current.timestamp - previous.timestamp).total_seconds() / 3600
        speed = distance / hours
    return Features(
        history_count=len(prior),
        amount_ratio=float(current.amount) / mean(float(item.amount) for item in prior)
        if prior
        else 1.0,
        transactions_last_5m=sum(
            item.timestamp >= current.timestamp - timedelta(minutes=5) for item in prior
        ),
        distance_from_previous_km=distance,
        travel_speed_kmh=speed,
        unusual_category=enough
        and all(item.merchant_category != current.merchant_category for item in prior),
        unusual_channel=enough and all(item.channel != current.channel for item in prior),
        amount_to_median=float(current.amount) / median(float(item.amount) for item in prior)
        if prior
        else 1.0,
        category_frequency=sum(
            item.merchant_category == current.merchant_category for item in prior
        )
        / len(prior)
        if prior
        else 0.0,
        channel_frequency=sum(item.channel == current.channel for item in prior) / len(prior)
        if prior
        else 0.0,
        seconds_since_previous=(current.timestamp - prior[-1].timestamp).total_seconds()
        if prior
        else 0.0,
    )
