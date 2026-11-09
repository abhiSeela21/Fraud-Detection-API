"""Migrate before listening: Free Render services have no pre-deploy command."""

import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from fraud_api.config import get_settings


def validate_hosted_environment() -> int:
    settings = get_settings()
    url = make_url(settings.database_url.get_secret_value())
    if settings.environment != "production":
        raise ValueError("Hosted startup requires production settings")
    if url.drivername != "postgresql+psycopg" or url.query.get("sslmode") not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError("Hosted database requires PostgreSQL/psycopg and TLS")
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid listening port")
    return port


def main() -> None:
    try:
        port = validate_hosted_environment()
        command.upgrade(Config("alembic.ini"), "head")
    except Exception:
        # Driver/config exceptions can contain connection details. Never print them.
        print(
            "Hosted startup failed. Check production settings, TLS and migrations.", file=sys.stderr
        )
        raise SystemExit(1) from None
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "fraud_api.deployment:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-proxy-headers",
            "--no-access-log",
            "--log-config",
            "logging.json",
        ],
    )


if __name__ == "__main__":
    main()
