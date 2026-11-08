"""Deterministic cohort generation and threshold metrics; no estimator fitting."""

import hashlib
import math
import random
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from fraud_api.features import calculate_features
from fraud_api.model_inputs import model_inputs
from fraud_api.rules import rule_signals, rules_score
from fraud_api.simulation import SimulationConfig, generate_transaction


def dataset(config, partition):
    rng = random.Random(f"{config['seed']}:{partition}")
    records = []
    profiles = ["commuter", "traveler", "business"]
    scenarios = ["burst", "travel", "amount", "category_channel", "mixed"]
    for run in range(config[f"{partition}_runs"]):
        scenario = (
            "normal" if rng.random() < config["normal_run_fraction"] else rng.choice(scenarios)
        )
        simulation = SimulationConfig(
            run_id=uuid5(
                NAMESPACE_URL, f"{config['dataset_version']}:{config['seed']}:{partition}:{run}"
            ),
            seed=rng.randrange(2**32),
            profile=profiles[run % 3],
            scenario=scenario,
            start_time=datetime.fromisoformat(config[f"{partition}_start"]),
        )
        history = []
        for index in range(config["transactions_per_run"]):
            transaction = generate_transaction(simulation, index)
            features = calculate_features(transaction, history)
            incident = scenario != "normal" and index >= 10 and index % 10 >= 6
            probability = (
                config["incident_fraud_probability"]
                if incident
                else config["background_fraud_probability"]
            )
            label = int(rng.random() < probability)
            legacy = [
                math.log1p(float(transaction.amount)),
                math.log1p(features.amount_ratio),
                math.log1p(features.history_count),
                float(features.transactions_last_5m),
                math.log1p(features.distance_from_previous_km),
                math.log1p(features.travel_speed_kmh),
                float(features.unusual_category),
                float(features.unusual_channel),
            ]
            records.append(
                (
                    transaction.timestamp,
                    model_inputs(transaction, features),
                    label,
                    rules_score(rule_signals(features)),
                    run,
                    scenario,
                    simulation.profile,
                    legacy,
                )
            )
            history.append(transaction)
    records.sort(key=lambda row: row[0])
    result = {
        "x": np.array([r[1] for r in records]),
        "y": np.array([r[2] for r in records]),
        "rules": np.array([r[3] for r in records]),
        "group": np.array([r[4] for r in records]),
        "scenario": np.array([r[5] for r in records]),
        "profile": np.array([r[6] for r in records]),
        "legacy_x": np.array([r[7] for r in records]),
        "start": records[0][0].isoformat(),
        "end": records[-1][0].isoformat(),
    }
    result["sha256"] = hashlib.sha256(result["x"].tobytes() + result["y"].tobytes()).hexdigest()
    return result


def metrics(labels, scores, threshold):
    predicted = scores >= threshold
    true = int(np.sum(predicted & (labels == 1)))
    false = int(np.sum(predicted & (labels == 0)))
    positives = int(np.sum(labels))
    return {
        "threshold": int(threshold),
        "precision": true / max(1, true + false),
        "recall": true / max(1, positives),
        "true_alerts": true,
        "false_alerts": false,
        "missed_fraud": positives - true,
        "alert_volume": true + false,
        "alert_rate": (true + false) / len(labels),
    }


def select_threshold(labels, scores, recall_floor):
    feasible = [metrics(labels, scores, t) for t in range(101)]
    feasible = [r for r in feasible if r["recall"] >= recall_floor]
    if not feasible:
        raise ValueError("No threshold satisfies the recall floor")
    return max(feasible, key=lambda r: (r["precision"], r["recall"], r["threshold"]))


def summary(data):
    return {
        "count": len(data["y"]),
        "fraud": int(sum(data["y"])),
        "prevalence": float(np.mean(data["y"])),
        "start": data["start"],
        "end": data["end"],
        "runs": len(np.unique(data["group"])),
        "sha256": data["sha256"],
    }
