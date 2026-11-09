import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from fraud_api import cleanup
from fraud_api.cleanup import cleanup_batch
from fraud_api.config import get_settings
from fraud_api.database import get_db
from fraud_api.main import app
from fraud_api.models import Alert, Base, DemoSession, ScoredTransaction
from fraud_api.scoring import Prediction, Scorer, get_scorer
from fraud_api.simulation import SimulationConfig, generate_transaction


@pytest.fixture
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL operation tests")
    if url == "compose":
        url = make_url(get_settings().database_url.get_secret_value()).set(
            host="localhost", port=5433
        )
    base = create_engine(url, pool_size=10, max_overflow=0)
    schema = f"test_operations_{uuid4().hex}"
    with base.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = base.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(isolated)
    try:
        yield isolated
    finally:
        Base.metadata.drop_all(isolated)
        with base.begin() as connection:
            connection.execute(DropSchema(schema))
        base.dispose()


class ReviewScorer(Scorer):
    def predict(self, transaction, features):
        return Prediction(probability=0.9, review_threshold=50, model_version="operation-test")


@pytest.fixture
def client(engine):
    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_scorer] = ReviewScorer
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_concurrent_retries_create_one_transaction_and_one_alert(client, engine):
    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = generate_transaction(SimulationConfig(run_id=uuid4()), 0).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(
            executor.map(
                lambda _: client.post("/v1/transactions/score", json=payload, headers=headers),
                range(12),
            )
        )
    assert all(result.status_code == 200 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoredTransaction)) == 1
        assert db.scalar(select(func.count()).select_from(Alert)) == 1


def test_concurrent_session_cap_is_durable(client, engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_transactions_per_session", 1)
    token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    config = SimulationConfig(run_id=uuid4())

    def score(index):
        return client.post(
            "/v1/transactions/score",
            json=generate_transaction(config, index).model_dump(mode="json"),
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(score, range(8)))
    assert sum(result.status_code == 200 for result in results) == 1
    assert sum(result.status_code == 429 for result in results) == 7
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoredTransaction)) == 1


def test_expiry_cleanup_is_bounded_and_cascades(client, engine):
    config = SimulationConfig(run_id=uuid4())
    for _ in range(3):
        token = client.post("/v1/sessions", json={"mode": "api"}).json()["token"]
        response = client.post(
            "/v1/transactions/score",
            json=generate_transaction(config, 0).model_dump(mode="json"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
    now = datetime.now(UTC)
    with Session(engine) as db:
        sessions = db.scalars(select(DemoSession).order_by(DemoSession.created_at)).all()
        for session in sessions[:2]:
            session.expires_at = now - timedelta(seconds=1)
        db.commit()
        assert cleanup_batch(db, 1, now) == 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(DemoSession)) == 2
        assert db.scalar(select(func.count()).select_from(ScoredTransaction)) == 2
        assert db.scalar(select(func.count()).select_from(Alert)) == 2
        assert cleanup_batch(db, 100, now) == 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(DemoSession)) == 1
        assert db.scalar(select(func.count()).select_from(ScoredTransaction)) == 1
        assert db.scalar(select(func.count()).select_from(Alert)) == 1


def test_cleanup_skips_in_use_sessions(engine):
    now = datetime.now(UTC)
    identifier = uuid4()
    with Session(engine) as db, db.begin():
        db.add(
            DemoSession(
                id=identifier,
                token_hash=uuid4().hex,
                created_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
            )
        )
    with Session(engine) as writer, writer.begin():
        writer.scalar(select(DemoSession).where(DemoSession.id == identifier).with_for_update())
        with Session(engine) as cleaner, cleaner.begin():
            assert cleanup_batch(cleaner, 100, now) == 0
    with Session(engine) as cleaner, cleaner.begin():
        assert cleanup_batch(cleaner, 100, now) == 1


def test_opportunistic_cleanup_throttles_and_bounds_each_attempt(engine, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(cleanup, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cleanup, "_next_attempt", 0.0)
    monkeypatch.setattr(get_settings(), "cleanup_batch_size", 1)
    monkeypatch.setattr(get_settings(), "cleanup_interval_seconds", 60)
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        for _ in range(3):
            db.add(
                DemoSession(
                    token_hash=uuid4().hex,
                    created_at=now - timedelta(days=2),
                    expires_at=now - timedelta(days=1),
                )
            )
    cleanup.maybe_cleanup(engine)
    cleanup.maybe_cleanup(engine)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DemoSession)) == 2
    clock[0] += 60
    cleanup.maybe_cleanup(engine)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DemoSession)) == 1
