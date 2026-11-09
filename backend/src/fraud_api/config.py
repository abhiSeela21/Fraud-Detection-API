from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="FRAUD_", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/fraud")
    frontend_origin: str = "http://localhost:5173"
    cookie_secure: bool = True
    session_ttl_hours: int = Field(default=24, ge=1, le=168)
    max_transactions_per_session: int = Field(default=500, ge=1, le=10000)
    model_directory: Path = Path(__file__).resolve().parent / "model_artifact"
    requests_per_minute_ip: int = Field(default=240, ge=1, le=10000)
    requests_per_minute_token: int = Field(default=180, ge=1, le=10000)
    sessions_per_minute_ip: int = Field(default=10, ge=1, le=1000)
    rate_limit_max_keys: int = Field(default=10000, ge=10, le=100000)
    trusted_proxy_cidrs: list[str] = []
    max_request_bytes: int = Field(default=32768, ge=1024, le=1048576)
    cleanup_batch_size: int = Field(default=100, ge=1, le=1000)
    cleanup_interval_seconds: int = Field(default=60, ge=1, le=3600)

    @model_validator(mode="after")
    def require_secure_production(self) -> "Settings":
        origin = urlsplit(self.frontend_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError(
                "Frontend origin must be an HTTP(S) origin without credentials or path"
            )
        for value in self.trusted_proxy_cidrs:
            if ip_network(value).prefixlen == 0:
                raise ValueError("Trust specific proxy networks, not all Internet addresses")
        if self.environment == "production" and (
            not self.cookie_secure or not self.frontend_origin.startswith("https://")
        ):
            raise ValueError("Production requires secure cookies and an HTTPS frontend origin")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
