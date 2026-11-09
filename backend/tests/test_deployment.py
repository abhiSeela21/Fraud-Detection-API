import pytest
from fastapi.testclient import TestClient

from fraud_api.config import get_settings
from fraud_api.deployment import create_app
from fraud_api.guardrails import limiter
from fraud_api.hosted_start import main, validate_hosted_environment


def test_packaged_app_preserves_api_guards_docs_and_static_boundary(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Demo build</h1>")
    monkeypatch.setenv("FRAUD_DEMO_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(get_settings(), "sessions_per_minute_ip", 1)
    monkeypatch.setattr(get_settings(), "max_request_bytes", 1024)
    monkeypatch.setattr("fraud_api.guardrails.monotonic", lambda: 10.0)
    with TestClient(create_app()) as client:
        assert "Demo build" in client.get("/").text
        assert client.get("/.env").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
        docs = client.get("/api/docs")
        assert docs.status_code == 200
        assert "/api/openapi.json" in docs.text
        assert client.get("/api/openapi.json").status_code == 200
        protected = client.get("/api/v1/transactions")
        assert protected.status_code == 401
        assert protected.headers["cache-control"] == "no-store"
        assert client.post("/api/v1/transactions/score", content="x" * 1025).status_code == 413
        # Even rejected browser-session attempts consume the session-creation budget.
        assert client.post("/api/v1/sessions", json={"mode": "browser"}).status_code == 403
        limited = client.post("/api/v1/sessions", json={"mode": "browser"})
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0
        assert client.get("/").status_code == 200
    limiter.clear()


def test_packaged_app_fails_if_build_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAUD_DEMO_DIRECTORY", str(tmp_path))
    with pytest.raises(RuntimeError, match="Built demo is missing"):
        create_app()


def test_hosted_start_requires_production_tls_and_valid_port(monkeypatch):
    settings = get_settings()
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(
        settings,
        "database_url",
        SecretStr("postgresql+psycopg://user:secret@db/demo?sslmode=require"),
    )
    monkeypatch.setenv("PORT", "12345")
    assert validate_hosted_environment() == 12345
    monkeypatch.setenv("PORT", "0")
    with pytest.raises(ValueError, match="port"):
        validate_hosted_environment()
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setattr(settings, "database_url", SecretStr("postgresql+psycopg://db/demo"))
    with pytest.raises(ValueError, match="TLS"):
        validate_hosted_environment()
    monkeypatch.setattr(settings, "environment", "test")
    with pytest.raises(ValueError, match="production"):
        validate_hosted_environment()


def test_migration_failure_prevents_listening_and_redacts_errors(monkeypatch, capsys):
    monkeypatch.setattr("fraud_api.hosted_start.validate_hosted_environment", lambda: 10000)

    def fail(*args):
        raise RuntimeError("postgresql://secret-password@private-host")

    monkeypatch.setattr("fraud_api.hosted_start.command.upgrade", fail)
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert "secret-password" not in capsys.readouterr().err


def test_migrations_precede_single_worker_start(monkeypatch):
    calls = []
    monkeypatch.setattr("fraud_api.hosted_start.validate_hosted_environment", lambda: 10000)
    monkeypatch.setattr(
        "fraud_api.hosted_start.command.upgrade", lambda config, target: calls.append(target)
    )
    monkeypatch.setattr("fraud_api.hosted_start.os.execvp", lambda name, args: calls.append(args))
    main()
    assert calls[0] == "head"
    assert "--factory" in calls[1]
    assert "--no-proxy-headers" in calls[1]
    assert calls[1][calls[1].index("--workers") + 1] == "1"
