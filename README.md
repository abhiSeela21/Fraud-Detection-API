# Fraud Detection API

A portfolio API for scoring **synthetic** payment transactions, with an interactive
demo planned as an independent React client. Detection results will combine explicit
rules and a lightweight classifier. This project never processes real payments.

## Status

Foundation in progress. Product decisions are recorded in [docs/design.md](docs/design.md).
Anonymous browser/API sessions, the initial PostgreSQL migration, deterministic
simulation batches, validated transaction contracts, historical features and rule
signals are implemented.
The current `/health` endpoint deliberately returns 503 until database and model
readiness are implemented. Persisted scoring, the classifier, alerts and the frontend
are still in progress.

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

The database binds to localhost port 5433 by default (`POSTGRES_PORT` overrides it).
Apply migrations with `docker compose exec api alembic upgrade head`.
For API clients, POST `{"mode":"api"}` to `/v1/sessions` to receive a temporary
bearer token. Browser mode sets an HttpOnly cookie and requires an `Origin` header
matching `FRAUD_FRONTEND_ORIGIN`. Responses carrying sessions are not cacheable.
When developing directly on the host, use localhost:5433 in the backend database
URL; Compose uses db:5432. For database integration tests against the local Compose
database, run `TEST_DATABASE_URL=compose uv run pytest` from `backend/` (the helper
uses the env file's credentials and localhost:5433). CI uses a separate test database.

From `backend/`, verify with `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run mypy src`.

## Synthetic simulations

With a session token, POST to `/v1/simulations/batch` using a JSON body such as:

```json
{
  "run_id": "00000000-0000-0000-0000-000000000042",
  "seed": 42,
  "profile": "commuter",
  "scenario": "mixed",
  "offset": 0,
  "count": 20
}
```

Pass the token in `Authorization: Bearer <token>`. Profiles are `commuter`,
`traveler`, and `business`; scenarios are `normal`, `burst`, `travel`, `amount`,
`category_channel`, and `mixed`. Requests return at most 50 events within a bounded
500-event run. Supply `start_time` to change the fixed event-time origin. No
background feed runs on the server. New runs use new UUIDs; the same seed/config
recreates the event contents with new IDs.

All profiles and behaviors are invented. The current generator is an initial
baseline, not yet a finished training dataset. Historical features exclude
same-time/future events and different accounts/runs. Physical travel uses earlier
in-person activity only. Rule signals cover limited history, relative amount
spikes, velocity, impossible travel and new categories/channels. Rule adjustments
are provisional until model/threshold evaluation; they do not explain a classifier.

Hosting must cost $0 with no payment method. Free-plan verification and deployment
will follow the local release gates. No hosted resources have been provisioned.
