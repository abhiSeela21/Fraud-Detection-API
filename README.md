# Fraud Detection API

A portfolio API for scoring **synthetic** payment transactions, with an interactive
React demo as an independent client. Detection combines explicit
rules and a lightweight classifier. This project never processes real payments.

## Status

Local API and interactive demo implemented. Product decisions are recorded in [docs/design.md](docs/design.md).
Anonymous browser/API sessions, the initial PostgreSQL migration, deterministic
simulation batches, validated transaction contracts, historical features and rule
signals are implemented.
Transaction/alert storage, idempotency, pagination and feedback are implemented.
A trained scikit-learn logistic classifier serves model-backed scoring. Startup
verifies its bundled JSON artifact; `/health` reports readiness only when the
verified model and migrated database are available. Request limits, expiry cleanup,
safe request logging and consistent API errors are implemented and tested against
PostgreSQL, including concurrent retry/cap checks. The React demo includes a guided
review, configurable simulations, manual scoring, alert investigation and feedback.
Public deployment verification remains outstanding; nothing is publicly hosted yet.

## Try the local demo

After configuring the env files below:

```sh
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Open **http://localhost:5173** and choose **Start guided demo**. Inspect a review
alert, then label it fraud or legitimate. You can then change the profile,
scenario, seed, event count and playback speed for your own simulations.
See [frontend setup and design](docs/frontend.md) for Vite development, browser
tests, the generated API contract and implementation boundaries.

## Local backend development

Install Python 3.12+ and uv. From `backend/`, run `uv sync` to create `.venv` with
locked dependencies, then run:

```sh
uv run uvicorn fraud_api.main:app --app-dir src --reload --no-proxy-headers --no-access-log --log-config logging.json
```

Interactive documentation is at http://localhost:8000/docs.

Copy `.env.example` to `.env` at the repository root and in `backend/`, replacing
placeholder credentials locally. Never commit real env files. For Compose, set
the backend database host to `db` and match its password to the root env file.
Use URL-encoded credentials in database URLs. Start with `docker compose up --build`.
Docker provides PostgreSQL, the API, and the frontend's static build/API proxy.

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

For a complete API example against the running local containers, run
`uv run python examples/demo.py` from `backend/`. It creates a temporary session,
scores 20 synthetic events, verifies a retry, inspects alerts and saves simulated
feedback without printing or saving its token. See [API operations](docs/api-operations.md)
for limits, cleanup, logging, proxy settings and error handling.

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
development-selected review threshold is now 38 after a separate recall-policy audit.
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
and its code is preserved at commit `c27b589`.

The [fresh v2 final evaluation](docs/evaluation/report.md) compares both versions
on the same 18,000 held-out events: v1 scored 23.4% precision / 81.0% recall, while
v2 scores **79.6% precision / 76.7% recall**. False alerts fall from 4,827 to 357,
at the cost of more missed fraud (345 to 424). V2 still misses the 80% recall
objective. Its run-cluster bootstrap recall interval is approximately 73.1%–80.4%;
these are synthetic-cohort uncertainty estimates, not real-world guarantees.

Calibration reduces final Brier loss from 0.0541 to 0.0383 on the same new model
(lower is better). See the report for scenario/profile failures, all threshold
tradeoffs and model-only comparisons. Stronger category/channel results reflect
simple generator assumptions; background fraud with no observable signal remains
largely undetectable. All results remain synthetic.

The subsequent [recall-policy audit](docs/evaluation/recall-policy/report.md) keeps
the weights and calibration fixed. Development selected threshold **38** using an
expanded 2027 cohort and a bootstrap recall safety margin before opening a new
2029 cohort. On that fresh **30,000-event** audit, recall increases from **79.8% to
81.8%** while precision decreases from **79.8% to 79.4%**: 74 extra fraud labels
found and 37 extra false alerts. Threshold 38 passed the predefined promotion gate.
Its approximate 95% run-cluster recall interval is **78.8%–84.4%**; this is a point
target achieved on synthetic data, not a guarantee of future or real-world recall.

Reproduce the promoted policy after training with:

```sh
uv run --group training python training/tune_recall.py --select-only
uv run --group training python training/tune_recall.py
```

The failed initial stricter policy and the successful development decision are
preserved with source/model hashes. The 2028 threshold table did not select the
new default. Retraining with `training/train.py` alone restores threshold 45; run
the policy commands above afterward. Rebuild/restart the API to load the new policy.

Artifacts contain data-only standardized coefficients or bounded trees rather than executable pickle.
The API needs no scikit-learn/NumPy runtime dependency. Tests and training verify
exported inference against scikit-learn and online/offline feature parity.
Stored v1 score snapshots remain readable and idempotent after feature upgrades.
Use `uv run --group training pytest` to include training-specific tests. Restart the
API after retraining (`docker compose up -d --build api` for Compose).

With the API running, `uv run python training/benchmark.py` records a small local
HTTP load with database persistence at concurrency 1 and 4. See
[latency evidence](docs/evaluation/latency.md); hosted cold starts are not measured.

To try scoring, create an API session using `/docs`, authorize with its bearer
token, request a simulation batch, then submit a returned transaction to
`/v1/transactions/score`. Inspect `/v1/alerts` and apply a feedback label.

Hosting must cost $0 with no payment method. Free-plan verification and deployment
instructions are in [the deployment guide](docs/deployment.md). A root Dockerfile
and `render.yaml` package the demo and API under one origin for Render Free with
Neon Free PostgreSQL. Public provisioning/verification follows a pushed, green
commit; no hosted resources have been provisioned yet.
