# Interactive demo

React/TypeScript/Vite is an independently deployable client of the documented API.
Its first release includes guided investigation, custom seeded simulations,
start/pause/resume/stop, manual scoring, session restoration, local session filters,
score/rule/model detail, and editable reviewer feedback. All data is synthetic.

## Local setup

The full Compose workflow builds PostgreSQL, FastAPI and a static React app served
through Nginx. Configure root/backend env files as in the README, then:

```sh
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Open `http://localhost:5173` (use **localhost**, matching the configured frontend
origin). API docs work through `/api/docs`, with its schema proxied at
`/openapi.json`. The API is also available on localhost:8000.

For frontend development, stop the frontend container to free port 5173 and start
Vite while the API and database remain running:

```sh
docker compose stop frontend
cd frontend
npm ci
npm run dev
```

The Vite development proxy and Nginx both route `/api` to the real API; browser
sessions use HttpOnly cookies. No token is returned to application state or stored
in local/session storage. The only localStorage value is a tutorial-dismissal
preference. Reloading restores server-side session transactions; an interrupted
run's configuration is not reconstructed after a full reload, so start a new run.

Frontend `.env.example` contains only the public API base URL. `VITE_` values are
bundled into browser code and must never contain credentials. To run Vite against
a different local API, set server-only `API_PROXY_TARGET`; for a separately hosted
browser API, set public `VITE_API_BASE_URL` and verify same-site cookies/origins
before deployment. No hosting resources are provisioned by this change.

## Behavioral guarantees and limits

- Generated batches use run ID, profile, scenario, seed and fixed event-time origin.
  Playback speed only changes delivery timing. Each score goes through the API.
- Pausing/hidden-tab/unmount aborts current browser requests and playback timers.
  An aborted request may already have committed on the server; resuming retains
  the same transaction ID and payload so server idempotency recovers safely.
- Each deliberate rerun gets new IDs and its own historical context. Earlier run
  results remain visible. Current-run filtering is optional.
- New events do not steal focus or announce each row to screen readers. Inspecting
  a transaction pauses the feed. Mobile investigation uses a native modal with
  Escape support and restores focus to the invoking row.
- Feedback only changes after a successful API response. Failure remains visible;
  previous labels and score snapshots remain intact.
- 401 responses require explicit fresh-session action. 429 responses respect the
  Retry-After countdown. Other scoring errors pause the run without skipping the
  unconfirmed transaction. Health wake-up retries are bounded to about a minute;
  unavailable services never produce fabricated local scores.
- Default custom playback is 1 event/second; fastest is 2/second. Runs are bounded
  to 200 events and the default session to 500. Browser code enforces a helpful
  soft limit; the server remains authoritative. Local filters cover recommendation,
  unlabeled alerts, run and text. Session restoration fetches at most 500 events.

## Contract and checks

`frontend/openapi.json` is exported from the backend; `src/api/schema.d.ts` is
generated from that schema. UI request/response types use those definitions.

```sh
cd backend
uv run python scripts/export_openapi.py
cd ../frontend
npm run api:generate
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests need a migrated, ready API and localhost:5173 available. The config
reuses existing local servers, or starts them when configured with a host-accessible
`FRAUD_DATABASE_URL`. CI creates its own PostgreSQL service and starts both servers.
It checks schema/type drift, unit/component tests, real-API browser flows and a
Docker build. The main flows use real scores, storage, cookies and feedback.
The wake-up test deliberately stubs a 503 to exercise that error state.

Accessibility checks run axe WCAG A/AA rules on populated desktop and mobile views;
keyboard/focus behavior is checked separately. Automated checks do not replace
manual accessibility review. The suite also tests safe retries after response loss,
in-flight pause, deliberate reruns, expiry, feedback failure and effect cleanup.

## UI structure

- `src/api/client.ts`: cookie-only HTTP transport and bounded wake-up retries.
- `src/demo.ts`: playback lifecycle, cancellation, idempotent retries and state.
- `src/App.tsx`: workspace composition, guide, controls, filters and responsive details.
- `src/components/`: investigation and manual-entry views.
- `src/styles.css`: layout, colors, type, responsive rules and reduced motion.

Presentation changes can stay in components/styles without rewriting the API
transport or simulation lifecycle. Model probability, risk index and rule signals
remain visibly distinct; the tutorial never claims to decline a real payment.

## Local verification · November 9, 2026

The first demo release passed 13 frontend unit/component tests and all 72 backend
tests. Four Chromium browser tests passed against the production React build served
by Nginx in Docker, using the existing FastAPI/PostgreSQL services. The same browser
suite also passed against Vite. Populated desktop (1440px) and mobile (390px) axe
checks reported no WCAG A/AA violations; mobile Escape and focus restoration passed.
Saved reviewer feedback was also checked interactively in the browser.

ESLint, TypeScript/production build, backend Ruff/mypy and exported schema checks
passed locally. The Node 24/Nginx Docker build passed. CI is configured for the
same release gates but has not run remotely for this commit. Public deployment,
hosted cold starts and broader browser/device testing remain future work.
