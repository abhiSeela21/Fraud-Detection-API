# Free deployment: Render + Neon

Status: deployment packaging is locally tested. No public service or database has
been provisioned by this change. Push this commit, let GitHub Actions pass, then
complete the account-specific steps below. A working local image is not evidence
of a successful public deployment.

## Cost boundary · checked November 9, 2026

- Use a Render **Hobby** workspace and exactly one **Free** web service. The
  Blueprint pins `plan: free`, disables preview environments and automatic deploys,
  and requests no paid disk, worker, cron job or Render database.
- Use a Neon **Free** organization/project, with no trial or paid upgrade. Neon’s
  current pricing page lists $0, no credit card, 100 CU-hours/project/month,
  1 GB/project storage and 5 GB/project public network transfer.
- Add **no payment method** to either provider. If signup or verification requires
  a card, stop rather than completing it. Do not accept a paid fallback.
- Render documents 750 shared free instance-hours/workspace/month. Without a
  payment method, exhausted bandwidth suspends free services; exhausted build
  minutes disables builds. Other free apps share the workspace allowances.
- Quotas, abuse prevention and provider policy can make the demo unavailable.
  They are not permission to upgrade. Recheck provider terms before provisioning;
  this is a dated verification, not a promise that policies never change.

Sources: [Render Free](https://render.com/docs/free),
[first deploy](https://render.com/docs/your-first-deploy),
[Neon pricing](https://neon.com/pricing),
[Render Blueprint specification](https://render.com/docs/blueprint-spec).

## Topology

One free Render Docker web service serves the built React client at `/` and the
FastAPI application at `/api`. PostgreSQL lives on Neon Free. Browser requests and
cookies stay on the same origin; no custom domain purchase or cross-site cookie
exception is needed. The API and demo remain independent source modules and retain
their standalone local Compose services.

- Demo: `https://<assigned-service>.onrender.com/`
- API documentation: `/api/docs`
- API schema: `/api/openapi.json`
- Readiness: `/api/health` (model plus migrated database)
- API scoring: `/api/v1/transactions/score`

Render terminates TLS. Cookies are `HttpOnly; Secure; SameSite=Lax`, host-only,
with path `/`. The Blueprint copies `RENDER_EXTERNAL_URL` into
`FRAUD_FRONTEND_ORIGIN` via Render’s supported self-reference. A custom domain
would require explicitly updating that origin.

The root Dockerfile builds React with Node 24 and packages it with the Python 3.12
API. It runs as a non-root user. No frontend secrets or local env files enter the
image. The entrypoint validates production settings and database TLS, runs Alembic,
then starts one worker on Render’s `PORT`. Migration failure prevents listening
and emits a generic error rather than credentials. Free services lack Render’s
paid pre-deploy command, so migrations run at startup. Use backward-compatible
migrations while an older deployment might still serve requests.

## Launch after pushing

1. Confirm the pushed **Quality** workflow is green. Do not deploy a failed build.
2. In the Neon console, confirm **Free** and no payment method. Create a dedicated
   project for this synthetic demo, preferably AWS Ohio to match Render Ohio.
   Use only PostgreSQL; no AI gateway or other paid add-ons. Leave scale-to-zero
   enabled and choose the smallest suitable compute configuration.
3. Copy the project’s direct PostgreSQL connection string privately. Change its
   scheme from `postgresql://` to `postgresql+psycopg://`, retaining the credentials,
   host, database and TLS query parameters (at least `sslmode=require`). Do not
   decode/re-encode individual pieces by hand or paste this string into chat.
4. In Render, confirm a Hobby workspace with no card. Create a **Blueprint** from
   this GitHub repository and its root `render.yaml`. Keep automatic Blueprint
   syncing off as well as the service’s manual deploy setting. Review the resource
   preview: one Free web service, no paid resources. If its defaults differ, stop.
5. Supply `FRAUD_DATABASE_URL` through Render’s private environment-variable input
   when prompted (`sync: false`). Do not put the value in `render.yaml`, GitHub
   source, build arguments, screenshots, terminal arguments or `VITE_` variables.
   If retaining a local copy, use an ignored `.env` file only.
6. Start the initial deploy. Verify its logs show successful migration and startup;
   use `/api/health` to confirm readiness. Verify the actual assigned HTTPS origin
   equals `FRAUD_FRONTEND_ORIGIN` and secure cookies remain enabled.
7. Complete the public verification below before presenting the link as released.

Creating accounts, accepting terms, repository authorization and entering secrets
may require the account owner. No hosted credentials are needed in CI: its
PostgreSQL credentials are disposable test values only.

## Public release verification

- Confirm both dashboards still show Free/$0 and no payment method, after launch.
- Open the assigned HTTPS URL in a clean browser session. Run the guided demo,
  inspect an alert, save/change a label, reload and confirm restoration.
- Run a custom seeded scenario, pause/resume/stop it, and submit a manual event.
- Test on mobile; verify Escape/focus and error states. Two separate browser
  sessions must not share transaction history.
- Check the cookie flags in browser developer tools without copying its value.
  Confirm cookie writes from an unrelated Origin are rejected.
- Open `/api/docs` and use a separate API-mode bearer session to score/retry a
  synthetic event. Never put bearer tokens in URLs or screenshots.
- Test readiness and one real idle wake-up. Record observed times and the tested
  commit in this document; do not invent hosted latency from local measurements.
- Check request-limit responses (429 plus Retry-After) and logs without flooding
  the free instance. Preserve the default conservative proxy behavior below.

Optional automated smoke journey, from `frontend/` with Chromium installed:

```sh
DEMO_BASE_URL=https://<assigned-service>.onrender.com npm run test:e2e
```

This creates temporary synthetic sessions and feedback on the specified demo. It
starts no local servers. Run it once against an awake service; respect 429 retries.
It checks functional flows, not billing settings or a real idle cold start.

## Limits and operations

Render sleeps after about 15 idle minutes and may take around a minute to wake.
Because this deployment serves both client and API together, Render’s loading page
may appear before React loads. Neon can also suspend when idle. Do not add uptime
pings to defeat free-plan sleeping. Health checks and traffic consume database
compute; monitor both providers’ quotas.

Forwarded IPs remain untrusted by default. Requests behind Render’s proxy can share
an IP budget, which may cause early 429 responses across visitors. This is a
conservative demo limitation; do not trust `0.0.0.0/0` or arbitrary forwarded
headers. Only configure specific immediate proxy networks after verifying the
provider’s current chain. Throttling is per process; keep one instance/worker.

Session expiry cleanup runs opportunistically in bounded batches. Session limits
are not a global storage quota. Monitor Neon storage/transfer; stop the service if
it approaches its free allowance. There are no paid backups or availability SLA.
Treat all stored data as disposable synthetic demo data.

Deploy future pushed, green commits manually. Render Free retains only limited
rollback history; a code rollback does not reverse a database migration. Never
run destructive downgrades to fix a deployment. Disable Blueprint auto-sync before
deleting services, or a later sync can recreate them. Delete the dedicated Neon
project only when its synthetic data is no longer needed.

## Local release evidence · November 9, 2026

- 77 backend tests pass, including mounted API body/session throttling, missing
  build handling, startup configuration and migration-failure behavior.
- All four Chromium journeys pass against the combined deployment image with a
  real database (local HTTP test settings); populated desktop/mobile axe checks
  pass as part of those journeys.
- The unmodified production entrypoint was separately exercised against a fresh,
  disposable TLS-enabled PostgreSQL database: migrations completed, readiness
  passed, and browser-session responses used Secure/HttpOnly/SameSite=Lax cookies
  without returning a JSON token. This does not simulate Render’s public TLS edge.
- The pushed demo commit’s backend CI job passed; its frontend schema gate failed
  on Python-dependent default HTTP reason phrases. Explicit response descriptions
  now reproduce the committed schema byte-for-byte on Python 3.12 and 3.14. The
  next pushed workflow must confirm this fix and all remaining CI steps remotely.
- Root Docker build and local lint/type/schema checks pass. The Blueprint also
  validates against Render’s official JSON schema. Hosted billing,
  account eligibility, public cold starts and public release verification remain
  unverified until provisioning after the push.
