# API operations and guardrails

All transaction data is synthetic. These controls bound a public demonstration;
they do not make it suitable for real payment credentials or payment decisions.

## Request admission

Limits are per process and use fixed one-minute windows:

| Configuration | Default | Applies to |
|---|---:|---|
| `FRAUD_REQUESTS_PER_MINUTE_IP` | 240 | `/v1/` requests by client IP |
| `FRAUD_REQUESTS_PER_MINUTE_TOKEN` | 180 | `/v1/` requests carrying the same cookie/bearer token |
| `FRAUD_SESSIONS_PER_MINUTE_IP` | 10 | Session-creation route by client IP |
| `FRAUD_RATE_LIMIT_MAX_KEYS` | 10,000 | In-memory identities across all budgets |
| `FRAUD_MAX_REQUEST_BYTES` | 32,768 | Buffered API request body |

Identity keys are hashes and are never logged. Admission is atomic across the
applicable budgets. Expired windows are removed; live keys are not evicted to let
an attacker bypass limits. If storage fills, new identities are rejected until
capacity expires. `429 RATE_LIMITED` includes `Retry-After` in seconds. A fixed
window permits a boundary burst; these are demo controls, not distributed DDoS
protection. Invalid tokens and rotating tokens still share the IP budget.

`/health` and browser preflight are exempt from application rate limits. Health
remains useful during exhaustion. Oversized bodies return `413 REQUEST_TOO_LARGE`
before application parsing, including bodies without a trustworthy Content-Length.
Budgets are charged only when all applicable budgets permit admission. Admitted
requests can still fail validation, authentication or the body-size check.

Each session also has a durable transaction cap (default 500). It is enforced in
PostgreSQL under a session row lock. Idempotent retries still work at that cap.
Concurrent retries produce one transaction and at most one alert. The same lock
serializes historical-feature computation within a session.

Process restart resets burst counters; multiple workers would each have separate
budgets. Use one API process for this release. Distributed throttling is required
before horizontal scaling. PostgreSQL session caps survive restarts.

## Proxy and browser configuration

Run Uvicorn with `--no-proxy-headers`. Docker already does so. Otherwise Uvicorn
could rewrite the peer address before the application's trust checks run.
`FRAUD_TRUSTED_PROXY_CIDRS` defaults to `[]`; untrusted forwarding headers are
ignored. Configure only the actual immediate reverse-proxy networks after checking
the deployment topology. Broad all-Internet networks are rejected at startup.

For trusted peers, X-Forwarded-For is processed right to left, stopping at the
first untrusted hop. Invented addresses further left do not become the rate-limit
identity. Malformed chains fall back to the immediate peer. This requires a proxy
that reliably appends/replaces forwarding information; never trust arbitrary
client-provided chains. Provider-specific trust configuration remains part of
deployment verification, not an assumption about free hosting.

Frontend origin must be an HTTP(S) origin without credentials, path, query or
fragment. Production also requires HTTPS and Secure cookies. Credentialed CORS
allows that one configured origin and exposes request IDs and Retry-After.
Cookie mutations check Origin; API clients use bearer tokens. Browser deployment
still needs the same-site cookie topology documented in the design.

## Expiry and bounded maintenance

Sessions expire after 24 hours by default, regardless of whether physical cleanup
has happened. Expired tokens are rejected. Active database traffic opportunistically
cleans one batch at most every 60 seconds per process:

- `FRAUD_CLEANUP_BATCH_SIZE=100` (maximum 1,000).
- `FRAUD_CLEANUP_INTERVAL_SECONDS=60`.
- Only expired sessions are selected, ordered by expiry.
- Locked sessions are skipped so maintenance does not wait on scoring.
- Database foreign keys cascade to their transactions and alerts.
- A maintenance failure logs only a safe event code; normal request handling can
  continue or return a safe database-unavailable response.

There is no continuously running background stream or paid scheduler. Idle hosts
do no work; a backlog may require several active intervals. To clear expired data
manually in explicit bounded batches:

```sh
docker compose exec api python -m fraud_api.cleanup --batch-size 100 --batches 10
```

That command deletes at most 1,000 expired sessions plus their dependent rows.
Deletion is permanent without a database backup; active sessions are preserved.
To run on the host, use the same CLI via `PYTHONPATH=src uv run python -m
fraud_api.cleanup` from backend with the host database URL configured.

## Errors, logs and database limits

Errors use `{ "error": { "code": "...", "message": "..." } }`; validation adds
field/type details without echoing submitted values. OpenAPI documents this actual
envelope instead of the framework's default validation shape. Readiness failures
are the intentional exception: `/health` returns `{ "status": "unavailable" }`.

Common codes include `VALIDATION_ERROR`, `SESSION_REQUIRED`, `SESSION_EXPIRED`,
`IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `SESSION_LIMIT`, `REQUEST_TOO_LARGE`,
`NOT_FOUND`, `METHOD_NOT_ALLOWED`, `DATABASE_UNAVAILABLE`, and `INTERNAL_ERROR`.
Database failures return 503 with a short Retry-After. Never blindly retry a changed
transaction under an existing idempotency key. Keep its ID and payload unchanged.

Non-preflight responses carry a server-generated X-Request-ID, Cache-Control:
no-store, and X-Content-Type-Options: nosniff. Structured request logs contain only
request ID, method, route template, status and elapsed time. They omit actual path
parameter values, query strings, IPs, request/response bodies, cookies, authorization
headers and exception text. Default Uvicorn access logging is disabled because it
would include raw URLs. Use the provided logging.json for direct development too.

The API engine has bounded pooling, five-second connection/statement timeouts,
three-second lock timeouts, and SQL parameter hiding. Exhaustion returns a safe
503 response rather than leaking driver details. These are initial demo bounds;
they must be rechecked under the deployment environment's available connections.

## Try the API

Open `/docs` for the versioned contract. Create an API-mode session with:

```sh
curl --fail-with-body http://localhost:8000/v1/sessions \
  -H 'Content-Type: application/json' --data '{"mode":"api"}'
```

Use its ephemeral token through the Authorize control, request a simulation batch,
submit a returned transaction for scoring, inspect an alert and set its feedback.
For an executable version of that complete flow that keeps the token in memory:

```sh
cd backend
uv run python examples/demo.py
```

Automated evidence includes real PostgreSQL concurrency, cap, cascade/locking,
cleanup-scheduling tests; proxy spoofing; bounded and concurrent rate admission;
request-size/error/log redaction checks; and OpenAPI response-schema checks.
