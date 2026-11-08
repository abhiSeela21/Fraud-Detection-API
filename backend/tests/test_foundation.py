import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fraud_api.config import Settings
from fraud_api.main import app


def test_missing_model_does_not_claim_readiness(monkeypatch) -> None:
    from fraud_api.errors import ApiError

    def unavailable():
        raise ApiError(503, "MODEL_UNAVAILABLE", "Unavailable")

    monkeypatch.setattr("fraud_api.main.verified_artifact", unavailable)
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_production_rejects_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="secure cookies"):
        Settings(environment="production", cookie_secure=False)


def test_database_credentials_are_redacted() -> None:
    settings = Settings(database_url="postgresql+psycopg://demo:private@localhost/fraud")
    assert "private" not in repr(settings)
