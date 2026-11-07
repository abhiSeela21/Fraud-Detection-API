"""Invented synthetic spending profiles; no real account data is used."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, Field, field_validator

from fraud_api.contracts import Category, Channel, Contract, Location, Transaction
from fraud_api.models import DemoSession
from fraud_api.sessions import require_session

GENERATOR_VERSION = "generator-v1"
router = APIRouter(prefix="/v1/simulations", tags=["simulations"])

CHICAGO = Location(country="US", latitude=41.8781, longitude=-87.6298)
NEW_YORK = Location(country="US", latitude=40.7128, longitude=-74.0060)
LONDON = Location(country="GB", latitude=51.5074, longitude=-0.1278)


class SimulationConfig(Contract):
    run_id: UUID
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    profile: Literal["commuter", "traveler", "business"] = "commuter"
    scenario: Literal["normal", "burst", "travel", "amount", "category_channel", "mixed"] = "mixed"
    start_time: AwareDatetime = datetime(2026, 1, 1, tzinfo=UTC)

    @field_validator("start_time")
    @classmethod
    def validate_start(cls, value: datetime) -> datetime:
        value = value.astimezone(UTC)
        if not 2020 <= value.year <= 2099:
            raise ValueError("Simulation start year must be between 2020 and 2099")
        return value


class BatchRequest(SimulationConfig):
    offset: int = Field(default=0, ge=0, le=499)
    count: int = Field(default=10, ge=1, le=50)


class BatchResponse(Contract):
    generator_version: str = GENERATOR_VERSION
    transactions: list[Transaction]


def generate_transaction(config: SimulationConfig, index: int) -> Transaction:
    # Index-local RNG makes batching/retries independent of request order.
    rng = random.Random(
        f"{GENERATOR_VERSION}:{config.seed}:{config.profile}:{config.scenario}:{index}"
    )
    categories = {
        "commuter": [Category.transport, Category.dining, Category.groceries],
        "traveler": [Category.hotel, Category.airfare, Category.dining, Category.transport],
        "business": [Category.software, Category.equipment, Category.hotel, Category.dining],
    }[config.profile]
    scale = {"commuter": 30, "traveler": 130, "business": 350}[config.profile]
    amount = min(99999, max(1, rng.lognormvariate(0, 0.7) * scale))
    category = rng.choice(categories)
    channel = Channel.in_person
    # Travel occurs on separate days; each five-event block is in one city.
    location = (
        [CHICAGO, NEW_YORK, LONDON][(index // 5) % 3] if config.profile == "traveler" else CHICAGO
    )
    timestamp = config.start_time + timedelta(days=index // 5, hours=(index % 5) * 2)
    anomalous = index >= 10 and index % 10 >= 6
    if anomalous:
        if config.scenario in {"amount", "mixed"}:
            amount = min(99999, amount * 15)
        if config.scenario in {"category_channel", "mixed"}:
            category = Category.entertainment
            channel = Channel.online
        if config.scenario in {"travel", "mixed"}:
            location = LONDON if index % 2 else CHICAGO
            channel = Channel.in_person
        if config.scenario in {"burst", "travel", "mixed"}:
            timestamp = config.start_time + timedelta(
                days=index // 5,
                hours=2,
                seconds=(index % 5) * 20,
            )
    # Legitimate outliers keep normal activity from being perfectly predictable.
    if config.scenario == "normal" and rng.random() < 0.03:
        amount *= 4
    return Transaction(
        client_transaction_id=uuid5(config.run_id, str(index)),
        run_id=config.run_id,
        account_id=f"syn_{config.profile}",
        amount=Decimal(str(min(amount, 100000))).quantize(Decimal("0.01")),
        timestamp=timestamp,
        merchant_category=category,
        location=location,
        channel=channel,
    )


@router.post("/batch", response_model=BatchResponse)
def batch(
    body: BatchRequest, session: Annotated[DemoSession, Depends(require_session)]
) -> BatchResponse:
    return BatchResponse(
        transactions=[
            generate_transaction(body, index)
            for index in range(body.offset, min(500, body.offset + body.count))
        ]
    )
