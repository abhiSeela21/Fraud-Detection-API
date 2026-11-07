import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fraud_api.config import Settings
from fraud_api.main import app


def test_unfinished_service_does_not_claim_readiness() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_INITIALIZING"


def test_production_rejects_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="secure cookies"):
        Settings(environment="production", cookie_secure=False)


def test_database_credentials_are_redacted() -> None:
    settings = Settings(database_url="postgresql+psycopg://demo:private@localhost/fraud")
    assert "private" not in repr(settings)
