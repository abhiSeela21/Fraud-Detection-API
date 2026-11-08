# Fraud Detection API

A portfolio API for scoring **synthetic** payment transactions, with an interactive
demo planned as an independent React client. Detection results will combine explicit
rules and a lightweight classifier. This project never processes real payments.

## Status

Foundation in progress. Product decisions are recorded in [docs/design.md](docs/design.md).
Anonymous browser/API sessions, the initial PostgreSQL migration, deterministic
simulation batches, validated transaction contracts, historical features and rule
signals are implemented.
Transaction/alert storage, idempotency, pagination and feedback are implemented.
A trained scikit-learn logistic classifier serves model-backed scoring. Startup
verifies its bundled JSON artifact; `/health` reports readiness only when the
verified model and migrated database are available. The frontend and remaining
operational safeguards are still in progress; this is not ready for public release.

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

All profiles and behaviors are invented. Historical features exclude
same-time/future events and different accounts/runs. Physical travel uses earlier
in-person activity only. Rule signals cover limited history, relative amount
spikes, velocity, impossible travel and new categories/channels. Rule adjustments
are versioned and evaluated separately; they do not explain the classifier.

## Transaction and alert contract

- `POST /v1/transactions/score`: accepts the transaction shape returned by simulation.
  Identical session-scoped client IDs and payloads return the original immutable
  result; changed payloads return 409. Each session is limited to 500 transactions
  by default. Retries remain available after the cap is reached.
- `GET /v1/transactions` and `GET /v1/alerts`: newest-ingested first, with `limit`
  (1–100) and opaque `cursor`. Filters: `recommendation`, `min_score`, `max_score`,
  `account_id`, `run_id`, `feedback` (`fraud`, `legitimate`, `unlabeled`),
  `start_time`, and `end_time`. Time filters use transaction event time.
- `PATCH /v1/alerts/{alert_id}/feedback`: accepts `{"label":"fraud"}` or
  `{"label":"legitimate"}`. Feedback can change; the original score never changes.

All routes require the session cookie or bearer token. Alert IDs belonging to
another session return 404. Scoring serializes writes per session so concurrent
requests cannot create duplicate alerts or race the durable transaction cap.
Historical events are strictly earlier by event time; inserting an old event does
not rewrite previously stored score snapshots.

Scores retain feature/rule/model/formula versions, features, model probability,
rule signals, rule baseline, applied adjustment and threshold. The initial formula
is `min(100, round(100 × model_probability) + min(40, rule_score))`. The current
threshold-cohort-selected review threshold is 45 in the v2 development artifact.
The risk index is not a fraud probability. The model probability now receives
sigmoid calibration fitted on a separate chronological cohort.

## Train and evaluate

From `backend/`:

```sh
uv sync --group training
uv run --group training python training/train.py
```

The v2 pipeline compares logistic and bounded forest models, calibrates on a
separate cohort, selects candidates and thresholds on two later cohorts, and
reserves a fresh 2028 final cohort. Configuration is in
`backend/training/improved_config.json`; the committed
[improvement protocol](docs/evaluation/improvement-plan.md) records the boundaries.
Use `--development-only` to stop before final evaluation and `--evaluate-frozen`
to evaluate an existing frozen artifact. No bulk dataset is committed.

The preserved v1 combined test result was **22.8% precision, 66.4% recall**, with 1,561 false
alerts among 2,022 reviews on 6,000 synthetic events. It missed the validation
recall objective of 80%. Original evidence is in [baseline-v1](docs/evaluation/baseline-v1/report.md)
and its code is preserved at commit `c27b589`. The v2 development candidate is
frozen; the fresh final evaluation is pending. All results remain synthetic.

Artifacts contain data-only standardized coefficients or bounded trees rather than executable pickle.
The API needs no scikit-learn/NumPy runtime dependency. Tests and training verify
exported inference against scikit-learn and online/offline feature parity.
Use `uv run --group training pytest` to include training-specific tests. Restart the
API after retraining (`docker compose up -d --build api` for Compose).

With the API running, `uv run python training/benchmark.py` records a small local
HTTP load with database persistence at concurrency 1 and 4. See
[latency evidence](docs/evaluation/latency.md); hosted cold starts are not measured.

To try scoring, create an API session using `/docs`, authorize with its bearer
token, request a simulation batch, then submit a returned transaction to
`/v1/transactions/score`. Inspect `/v1/alerts` and apply a feedback label.

Hosting must cost $0 with no payment method. Free-plan verification and deployment
will follow the local release gates. No hosted resources have been provisioned.
