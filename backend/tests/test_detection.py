from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from fraud_api.contracts import Transaction
from fraud_api.features import calculate_features
from fraud_api.rules import rule_signals
from fraud_api.simulation import SimulationConfig, generate_transaction


def configuration(**kwargs):
    return SimulationConfig(run_id=UUID("00000000-0000-0000-0000-000000000042"), **kwargs)


def test_generation_is_reproducible_across_batches_and_runs():
    config = configuration()
    events = [generate_transaction(config, i) for i in range(50)]
    assert events == [generate_transaction(config, i) for i in range(50)]
    assert events[20:30] == [generate_transaction(config, i) for i in range(20, 30)]
    rerun = config.model_copy(update={"run_id": uuid4()})
    repeated = generate_transaction(rerun, 20)
    assert repeated.client_transaction_id != events[20].client_transaction_id
    assert repeated.model_dump(exclude={"run_id", "client_transaction_id"}) == events[
        20
    ].model_dump(exclude={"run_id", "client_transaction_id"})


@pytest.mark.parametrize("profile", ["commuter", "traveler", "business"])
@pytest.mark.parametrize(
    "scenario", ["normal", "burst", "travel", "amount", "category_channel", "mixed"]
)
def test_simulation_is_valid_and_time_ordered(profile, scenario):
    config = configuration(profile=profile, scenario=scenario)
    events = [generate_transaction(config, i) for i in range(500)]
    assert len({item.client_transaction_id for item in events}) == 500
    assert [item.timestamp for item in events] == sorted(item.timestamp for item in events)
    for item in events:
        assert Transaction.model_validate_json(item.model_dump_json()) == item


def test_features_ignore_future_other_accounts_and_other_runs():
    config = configuration(scenario="amount")
    history = [generate_transaction(config, i) for i in range(16)]
    current = generate_transaction(config, 16)
    expected = calculate_features(current, history)
    unrelated = history[0].model_copy(update={"account_id": "syn_other"})
    other_run = history[0].model_copy(update={"run_id": uuid4()})
    same_time = current.model_copy(update={"client_transaction_id": uuid4()})
    future = generate_transaction(config, 30)
    assert (
        calculate_features(current, [*history, unrelated, other_run, same_time, future]) == expected
    )
    assert calculate_features(current, reversed(history)) == expected
    assert "AMOUNT_SPIKE" in {item.code for item in rule_signals(expected)}


def test_online_transactions_do_not_imply_physical_travel():
    config = configuration(scenario="travel")
    prior = generate_transaction(config, 16)
    current = generate_transaction(config, 17)
    physical = calculate_features(current, [prior])
    assert physical.travel_speed_kmh > 1000
    online = current.model_copy(update={"channel": "online"})
    assert calculate_features(online, [prior]).travel_speed_kmh == 0


def test_cold_start_is_explicit_without_fabricated_history():
    features = calculate_features(generate_transaction(configuration(), 0), [])
    signals = rule_signals(features)
    assert [s.code for s in signals] == ["LIMITED_HISTORY"]
    assert signals[0].adjustment == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"amount": "1.001"},
        {"amount": "NaN"},
        {"currency": "EUR"},
        {"account_id": "real@example.com"},
        {"timestamp": "2026-01-01T12:00:00"},
        {"card_number": "not-allowed"},
        {"location": {"country": "US", "latitude": 91, "longitude": 0}},
    ],
)
def test_transaction_rejects_invalid_or_sensitive_fields(changes):
    data = generate_transaction(configuration(), 0).model_dump(mode="json")
    with pytest.raises(ValidationError):
        Transaction.model_validate({**data, **changes})


def test_timestamp_normalizes_to_utc():
    data = generate_transaction(configuration(), 0).model_dump(mode="json")
    transaction = Transaction.model_validate({**data, "timestamp": "2026-01-01T12:00:00-06:00"})
    assert transaction.timestamp.hour == 18
    assert transaction.timestamp.utcoffset() == timedelta(0)
