import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from fraud_api.config import Settings, get_settings
from fraud_api.guardrails import GuardrailsMiddleware, WindowLimiter, client_ip, limiter
from fraud_api.main import app


def test_rate_window_is_atomic_bounded_and_expires():
    limits = WindowLimiter()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: limits.admit([("one", 7)], 2, 10), range(100)))
    assert results.count(0) == 7
    assert limits.admit([("two", 1)], 2, 10) == 0
    assert limits.admit([("three", 1)], 2, 10) == 50
    assert limits.admit([("one", 7)], 2, 10) == 50  # No eviction bypass.
    assert limits.admit([("three", 1)], 2, 60) == 0
    assert len(limits.entries) == 1


def test_forwarding_requires_trusted_immediate_peer():
    assert client_ip("198.51.100.4", "192.0.2.99", []) == "198.51.100.4"
    assert (
        client_ip("127.0.0.1", "192.0.2.99, 198.51.100.4, 10.1.2.3", ["127.0.0.1/32", "10.0.0.0/8"])
        == "198.51.100.4"
    )
    assert client_ip("127.0.0.1", "malformed", ["127.0.0.1/32"]) == "127.0.0.1"
    assert client_ip("::1", "2001:db8::123", ["::1/128"]) == "2001:db8::123"
    with pytest.raises(ValueError):
        Settings(trusted_proxy_cidrs=["0.0.0.0/0"])


def test_ip_token_creation_limits_and_health_exemption(monkeypatch):
    monkeypatch.setattr("fraud_api.guardrails.monotonic", lambda: 10.0)
    settings = get_settings()
    monkeypatch.setattr(settings, "requests_per_minute_ip", 5)
    monkeypatch.setattr(settings, "requests_per_minute_token", 1)
    monkeypatch.setattr(settings, "sessions_per_minute_ip", 1)
    limiter.clear()
    test_app = FastAPI()
    test_app.add_middleware(GuardrailsMiddleware)

    @test_app.get("/v1/read")
    def read():
        return {"ok": True}

    @test_app.post("/v1/sessions")
    def create():
        return {"ok": True}

    @test_app.get("/health")
    def health():
        return {"ok": True}

    with (
        TestClient(test_app, client=("198.51.100.1", 1)) as first,
        TestClient(test_app, client=("198.51.100.2", 1)) as second,
    ):
        headers = {"Authorization": "Bearer synthetic_token"}
        assert first.get("/v1/read", headers=headers).status_code == 200
        blocked = second.get("/v1/read", headers=headers)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert (
            second.get("/v1/read", headers={"Cookie": "fraud_session=synthetic_token"}).status_code
            == 429
        )
        assert first.post("/v1/sessions").status_code == 200
        assert first.post("/v1/sessions").status_code == 429
        for _ in range(3):
            assert first.get("/v1/read").status_code == 200
        assert first.get("/v1/read", headers={"X-Forwarded-For": "192.0.2.10"}).status_code == 429
        assert second.get("/v1/read").status_code == 200
        for _ in range(10):
            assert first.get("/health").status_code == 200
    limiter.clear()


def test_configuration_rejects_ambiguous_frontend_origins():
    for origin in ["https://example.com/path", "https://name:secret@example.com", "example.com"]:
        with pytest.raises(ValueError):
            Settings(frontend_origin=origin)


def test_openapi_matches_custom_error_and_health_contract():
    schema = app.openapi()
    errors = schema["paths"]["/v1/transactions/score"]["post"]["responses"]
    for status in ["401", "409", "413", "422", "429", "503"]:
        assert errors[status]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorEnvelope"
        )
    assert schema["paths"]["/health"]["get"]["responses"]["503"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/HealthResponse")


def test_errors_and_logs_do_not_expose_secret_values(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="fraud_api.requests")
    secret = "sensitive-value-never-log"

    def fail():
        raise ValueError(secret)

    def database_fail():
        raise OperationalError("secret sql", {}, Exception(secret))

    app.add_api_route("/v1/test-fault", fail)
    app.add_api_route("/v1/test-database-fault", database_fail)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/test-fault",
                params={"secret": secret},
                headers={"Authorization": f"Bearer {secret}", "Origin": "http://localhost:5173"},
            )
            assert response.status_code == 500
            assert response.json()["error"]["code"] == "INTERNAL_ERROR"
            assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
            assert len(response.headers["x-request-id"]) == 32
            assert response.headers["cache-control"] == "no-store"
            assert (
                client.get("/v1/test-database-fault").json()["error"]["code"]
                == "DATABASE_UNAVAILABLE"
            )
            assert client.get("/unknown").json()["error"]["code"] == "NOT_FOUND"
            assert client.delete("/v1/sessions").json()["error"]["code"] == "METHOD_NOT_ALLOWED"
            monkeypatch.setattr(get_settings(), "max_request_bytes", 1024)
            large = client.post(
                "/v1/sessions", content=secret * 100, headers={"Content-Type": "application/json"}
            )
            assert large.status_code == 413
        assert secret not in caplog.text
        assert "secret sql" not in caplog.text
        assert secret not in response.text
    finally:
        app.router.routes[:] = [
            route
            for route in app.router.routes
            if getattr(route, "path", "") not in {"/v1/test-fault", "/v1/test-database-fault"}
        ]
