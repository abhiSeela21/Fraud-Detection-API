from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FRAUD_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/fraud")
    frontend_origin: str = "http://localhost:5173"
    cookie_secure: bool = True
    session_ttl_hours: int = Field(default=24, ge=1, le=168)
    max_transactions_per_session: int = Field(default=500, ge=1, le=10000)

    @model_validator(mode="after")
    def require_secure_production(self) -> "Settings":
        if self.environment == "production" and (
            not self.cookie_secure or not self.frontend_origin.startswith("https://")
        ):
            raise ValueError("Production requires secure cookies and an HTTPS frontend origin")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
