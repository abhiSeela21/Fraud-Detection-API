# Product and architecture decisions

The core product is a public, documented fraud scoring API. A React/TypeScript
demo consumes that same HTTP API through a guided tutorial and custom simulations.
All inputs and evaluation data are synthetic. Recommendations are `clear` or
`review`; this application does not process or decline real payments.

## Delivery boundaries

- One repository; independently deployable `backend/` and `frontend/` applications.
- Python/FastAPI/Pydantic, synchronous SQLAlchemy 2 + psycopg, Alembic, PostgreSQL.
- React/TypeScript/Vite; Docker Compose for local development; Python `.venv`
  and locked dependencies for direct development.
- No cost, payment methods, AWS dependency, or automatic paid upgrades.
- Render API/static hosting and Neon are candidates only: verify current free
  terms before provisioning. Local functionality must remain independent of hosts.
- Future phases: accounts, durable history, measured scalability improvements,
  and separately governed real-world integrations.

## Sessions and API

Anonymous sessions expire after 24 hours. Opaque random tokens are hashed in the
database. Browser mode sets an HttpOnly, Secure, SameSite=Lax cookie; API mode
returns a bearer token. Production browser deployment needs a same-site topology
(or same-origin proxy); unrelated provider domains cannot be assumed to support
SameSite=Lax API cookies. Cookie mutations validate the frontend origin. Local
HTTP development may explicitly disable Secure. Tokens never enter browser JS.

Versioned endpoints: POST `/v1/sessions`, POST `/v1/transactions/score`, GET
`/v1/transactions`, GET `/v1/alerts`, PATCH `/v1/alerts/{id}/feedback` plus
simulation endpoints. `/docs` publishes OpenAPI; `/health` checks database and
verified model readiness. Missing/incompatible model artifacts fail readiness.

Session-scoped transaction IDs are idempotency keys: identical retries return the
stored result; changed payloads return 409. Runs get unique IDs and transaction
IDs. Account histories are session scoped. Inputs and scoring results are
immutable; feedback labels are editable. At most one review alert per transaction.

USD only initially; fixed precision positive amounts, timezone-aware timestamps
normalized to UTC, separate receipt time, structured country/coordinates, enum
merchant categories/channels, synthetic account IDs. No payment credential fields.
Clients supply current events; server computes history strictly preceding event
time. Cursor pagination and bounded server filters cover account, run, time,
recommendation, scores and feedback. Errors share stable codes/messages/details.

## Detection and simulation

Deterministic generator configuration includes profile, scenario, seed, index and
fixed event-time origin. Commuter, traveler and business profiles have distinct
normal behavior. Scenarios cover bursts, impossible travel, relative amount
spikes, unusual merchants/channels, and mixed signals. Include legitimate anomalies
and overlapping patterns; never make synthetic labels trivially separable.

Browser fetches bounded batches only while running, submits each through scoring,
and supports pause/resume/stop/rerun. Reruns isolate account history to reproduce
scores. Tutorial has a known seed with an alert. Visitors can configure profile,
scenario, seed, speed and count. Labels from reviewers never replace generator
truth or retrain the model automatically.

Rules cover amount relative to history, velocity, geography, category and channel.
A lightweight classifier probability plus explicit capped rule adjustments produces
a versioned 0–100 score. Rule signals are distinct from model explanation. Limited
history is explicit. Store rule/model/feature/formula versions and score components.

Generate training/validation/later test periods. Compare lightweight candidates,
select threshold on validation against a documented recall target, and evaluate
rules-only/model-only/combined on untouched test data. Preserve documented test
prevalence; training-only weighting/resampling. Reproduction command creates data,
model/checksum and report. Startup validates artifact integrity/schema. Report
precision, recall, false alerts, alert volume, threshold tradeoffs and documented
warm/cold percentile latency. Synthetic metrics establish no real-world efficacy.

## Operations and quality

500 transactions/session initially, configurable request throttles per IP/token,
standard 429 responses, durable database session caps. Single-instance in-memory
burst limiting initially; distributed throttling is future work. Trust forwarded
IPs only behind configured proxies. Bounded opportunistic expiry cleanup and a
manual cleanup command avoid paid scheduling.

Typed environment configuration, ignored real env files, safe `.env.example`,
hosting secret stores, no secrets in Vite variables or structured logs. CI checks
secret leakage, lint/type checks, unit tests, PostgreSQL integration/migrations,
OpenAPI/frontend drift, Docker build, and Playwright guided journey. Tests cover
validation, deterministic scoring, isolation, retries/conflicts, alerts, feedback,
expiry and future-data invariance.

UI: restrained dashboard, replayable ~one minute tutorial, live table/mobile cards,
alert details, saved/error feedback states, keyboard operation and WCAG AA
fundamentals. Numeric scores plus text; restrained live announcements. Explicit
waking/unavailable states and persistent synthetic disclosure. Link API docs,
source, architecture and evaluation.

Release only after local gates pass. Verify hosted tutorial/custom run/feedback,
docs request/mobile/wake-up/free configuration manually. Handoff includes setup,
example requests, architecture, evaluation, recording and hosting limitations.
