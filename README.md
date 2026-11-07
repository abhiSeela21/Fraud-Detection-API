# Fraud Detection API

A portfolio API for scoring **synthetic** payment transactions, with an interactive
demo planned as an independent React client. Detection results will combine explicit
rules and a lightweight classifier. This project never processes real payments.

## Status

Foundation in progress. Product decisions are recorded in [docs/design.md](docs/design.md).
The current `/health` endpoint deliberately returns 503 until database and model
readiness are implemented. Scoring and the demo are not implemented yet.

## Local backend development

Install Python 3.12+ and uv. From `backend/`, run `uv sync` to create `.venv` with
locked dependencies, then `uv run uvicorn fraud_api.main:app --app-dir src --reload`.
Interactive documentation is at http://localhost:8000/docs.

Copy `.env.example` to `.env` at the repository root and in `backend/`, replacing
placeholder credentials locally. Never commit real env files. For Compose, set
the backend database host to `db` and match its password to the root env file.
Use URL-encoded credentials in database URLs. Start with `docker compose up --build`.
Docker is required for the PostgreSQL workflow; the frontend service will be added
when its implementation is ready.

From `backend/`, verify with `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run mypy src`.

Hosting must cost $0 with no payment method. Free-plan verification and deployment
will follow the local release gates. No hosted resources have been provisioned.
