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
from fraud_api.sessions import hash_token, require_session


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
