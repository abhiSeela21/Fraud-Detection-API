import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from fraud_api.config import get_settings
from fraud_api.database import get_db
from fraud_api.main import app
from fraud_api.models import DemoSession
from fraud_api.scoring import Prediction, Scorer, get_scorer
from fraud_api.sessions import hash_token, require_session
from fraud_api.simulation import SimulationConfig, generate_transaction


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL test database")
    if url == "compose":
        from sqlalchemy.engine import make_url

        url = make_url(get_settings().database_url.get_secret_value()).set(
            host="localhost", port=5433
        )
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    # Test-only protected route exercises the shared authorization dependency.
    from fastapi import APIRouter

    probe = APIRouter()

    @probe.api_route("/session-probe", methods=["GET", "POST"])
    def identity(session: Annotated[DemoSession, Depends(require_session)]):
        return {"id": str(session.id)}

    app.include_router(probe)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.router.routes[:] = [
        r for r in app.router.routes if getattr(r, "path", "") != "/session-probe"
    ]


def test_bearer_tokens_are_hashed_and_isolated(client, db):
    first = client.post("/v1/sessions", json={"mode": "api"})
    second = client.post("/v1/sessions", json={"mode": "api"})
    assert first.status_code == second.status_code == 201
    token = first.json()["token"]
    assert "no-store" in first.headers["cache-control"]
    stored = db.scalar(select(DemoSession).where(DemoSession.token_hash == hash_token(token)))
    assert stored.token_hash != token
    a = client.get("/session-probe", headers={"Authorization": f"Bearer {token}"})
    b = client.get("/session-probe", headers={"Authorization": f"Bearer {second.json()['token']}"})
    assert a.status_code == b.status_code == 200
    assert a.json() != b.json()
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert (
        client.get("/session-probe", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_browser_cookie_origin_and_token_secrecy(client):
    assert client.post("/v1/sessions", json={"mode": "browser"}).status_code == 403
    result = client.post(
        "/v1/sessions", json={"mode": "browser"}, headers={"Origin": "http://localhost:5173"}
    )
    assert result.status_code == 201
    assert "token" not in result.json()
    cookie = result.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/session-probe").status_code == 200
    assert (
        client.post("/session-probe", headers={"Origin": "https://evil.example"}).status_code == 403
    )
    assert (
        client.post("/session-probe", headers={"Origin": "http://localhost:5173"}).status_code
        == 200
    )


def test_simulation_requires_session_and_is_repeatable(client):
    payload = {"run_id": "00000000-0000-0000-0000-000000000042", "count": 5}
    assert client.post("/v1/simulations/batch", json=payload).status_code == 401
    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/v1/simulations/batch", json=payload, headers=headers)
    repeated = client.post("/v1/simulations/batch", json=payload, headers=headers)
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    assert len(first.json()["transactions"]) == 5
    invalid = client.post("/v1/simulations/batch", json={**payload, "count": 100}, headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


class TestScorer(Scorer):
    __test__ = False

    def predict(self, transaction, features):
        return Prediction(probability=0.7, review_threshold=60, model_version="test-only")


def test_persisted_scoring_retries_conflicts_isolation_and_feedback(client, db):
    from uuid import uuid4

    app.dependency_overrides[get_scorer] = TestScorer
    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    other_token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    other = {"Authorization": f"Bearer {other_token}"}
    config = SimulationConfig(run_id=uuid4())
    transaction = generate_transaction(config, 0).model_dump(mode="json")
    first = client.post("/v1/transactions/score", json=transaction, headers=headers)
    assert first.status_code == 200
    result = first.json()
    assert result["recommendation"] == "review"
    assert result["model_probability"] == 0.7
    assert result["alert_id"]
    retry = client.post("/v1/transactions/score", json=transaction, headers=headers)
    assert retry.json() == result
    conflict = client.post(
        "/v1/transactions/score", json={**transaction, "amount": "12.34"}, headers=headers
    )
    assert conflict.status_code == 409
    assert len(client.get("/v1/alerts", headers=headers).json()["items"]) == 1
    assert client.get("/v1/alerts", headers=other).json()["items"] == []
    feedback_url = f"/v1/alerts/{result['alert_id']}/feedback"
    assert client.patch(feedback_url, json={"label": "fraud"}, headers=other).status_code == 404
    assert client.patch(feedback_url, json={"label": "fraud"}, headers=headers).status_code == 200
    assert (
        client.get("/v1/alerts?feedback=fraud", headers=headers).json()["items"][0]["feedback"]
        == "fraud"
    )
    assert (
        client.patch(feedback_url, json={"label": "legitimate"}, headers=headers).status_code == 200
    )
    assert client.get("/v1/alerts?feedback=fraud", headers=headers).json()["items"] == []
    assert client.post("/v1/transactions/score", json=transaction, headers=headers).json() == result
    # Out-of-order arrival must not leak future history.
    future = generate_transaction(config, 20).model_dump(mode="json")
    client.post("/v1/transactions/score", json=future, headers=headers)
    earlier = generate_transaction(config, 1).model_dump(mode="json")
    early_result = client.post("/v1/transactions/score", json=earlier, headers=headers).json()
    assert early_result["features"]["history_count"] == 1
    page = client.get("/v1/transactions?limit=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    next_page = client.get(
        f"/v1/transactions?limit=2&cursor={page['next_cursor']}", headers=headers
    ).json()
    assert len(next_page["items"]) == 1
    assert next_page["items"][0]["score"]["transaction_id"] == result["transaction_id"]
    assert client.get("/v1/transactions?cursor=garbage", headers=headers).status_code == 422


def test_missing_model_does_not_persist_a_fake_score(client, db):
    from uuid import uuid4

    from fraud_api.models import ScoredTransaction

    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    transaction = generate_transaction(SimulationConfig(run_id=uuid4()), 0).model_dump(mode="json")
    result = client.post("/v1/transactions/score", json=transaction, headers=headers)
    assert result.status_code == 503
    assert db.scalar(select(ScoredTransaction)) is None


def test_session_limit_still_allows_idempotent_retry(client, monkeypatch):
    from uuid import uuid4

    monkeypatch.setattr(get_settings(), "max_transactions_per_session", 1)
    app.dependency_overrides[get_scorer] = TestScorer
    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    config = SimulationConfig(run_id=uuid4())
    transaction = generate_transaction(config, 0).model_dump(mode="json")
    assert (
        client.post("/v1/transactions/score", json=transaction, headers=headers).status_code == 200
    )
    assert (
        client.post("/v1/transactions/score", json=transaction, headers=headers).status_code == 200
    )
    second = generate_transaction(config, 1).model_dump(mode="json")
    assert client.post("/v1/transactions/score", json=second, headers=headers).status_code == 429
