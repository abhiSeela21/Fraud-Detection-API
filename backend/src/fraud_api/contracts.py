from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Category(StrEnum):
    groceries = "groceries"
    dining = "dining"
    transport = "transport"
    hotel = "hotel"
    airfare = "airfare"
    software = "software"
    equipment = "equipment"
    entertainment = "entertainment"


class Channel(StrEnum):
    in_person = "in_person"
    online = "online"


class Location(Contract):
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class Transaction(Contract):
    client_transaction_id: UUID
    account_id: Annotated[str, Field(pattern=r"^syn_[a-zA-Z0-9_-]{1,80}$")]
    run_id: UUID | None = None
    amount: Annotated[Decimal, Field(gt=0, le=100000, max_digits=10, decimal_places=2)]
    currency: Literal["USD"] = "USD"
    timestamp: AwareDatetime
    merchant_category: Category
    location: Location
    channel: Channel

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        value = value.astimezone(UTC)
        if not 2020 <= value.year <= 2100:
            raise ValueError("Synthetic event year must be between 2020 and 2100")
        return value
