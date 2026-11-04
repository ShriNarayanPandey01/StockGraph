# MarketGraph Platform

See [the Platform system design and class diagram](../../docs/architecture/platform-service.md).

The application backend owns users, contribution history, reviews, usage measurements,
and the durable professional-evidence outbox. It uses its **own logical PostgreSQL
database** on the existing PostgreSQL/Timescale server. All its tables are ordinary
PostgreSQL tables. It never reads Data Service tables or writes graph data directly.

Current accounts and access policy are documented in
[Phase 2 operations](../../docs/PHASE2_PLATFORM.md). Public users sign up with
verified email/password and start Free; Pro is assigned manually. The `.env`
developer identity has all supported application permissions and can self-approve.
Payments and trading remain deferred.

## Running

Configure `PLATFORM_DATABASE_DSN`, `PLATFORM_REDIS_URL`, `PLATFORM_DATA_SERVICE_URL`
and `PLATFORM_GRAPH_SERVICE_URL`. Use a distinct database and application credential.
The compose database bootstrap handles new volumes; existing volumes need the
documented explicit database provisioning command.

```powershell
uv run --package marketgraph-platform marketgraph-platform migrate
uv run --package marketgraph-platform marketgraph-platform provision-user --name "Researcher" --professional-verified
uv run --package marketgraph-platform marketgraph-platform provision-user --name "Independent reviewer"
uv run --package marketgraph-platform uvicorn marketgraph_platform.api:create_app --factory --port 8002
uv run --package marketgraph-platform marketgraph-platform-worker
```

Provisioning prints a random opaque bearer token once; SQL stores only its SHA-256
digest. Use `Authorization: Bearer <token>`. Credentials cannot be assigned by public
requests. `rotate-token --user-id UUID` revokes the user's prior tokens atomically.
`set-professional-verification --user-id UUID --verified` (or `--no-verified`) is an
operator command. HTTPS is required at the deployment ingress.

Startup applies ordered, packaged migrations transactionally under a database
advisory lock. Checksums reject edits to previously applied migrations. Add a new
migration for later schema changes. The API and separate worker use bounded pools.

## Publishing

1. `POST /api/v1/contributions`: create a private immutable draft version. Required
   inputs include canonical ticker, title/body, direction, horizon, timezone-aware
   event/expiry times, disclosures, and citations with URL/title/locator. An optional
   `document_version_id` resolves through the Data Service. No source URL is fetched
   by the Platform Backend.
   Send an `Idempotency-Key` header and reuse it for retries of the identical body;
   a different body under the same key is rejected rather than creating a duplicate.
2. `POST /api/v1/contributions/{id}/submit`: freeze the version for independent
   review. Include its `expected_revision` on every mutation.
3. An assigned reviewer reads `GET /api/v1/review-queue` and posts
   `/contributions/{id}/review` with `APPROVE` or `REJECT`, a reason and revision.
   Self-review is rejected for ordinary users; the developer can self-approve.
   Publication retains verified author, canonical citation and expiry checks.
4. `POST /contributions/{id}/versions` creates a correction as a new version; the
   previous publication stays active until the correction is approved. Submitted
   versions cannot be edited. Rejected versions require a new draft before resubmission.
5. `/contributions/{id}/retract` records an immutable reason and removes the current
   publication from evidence results. Retracted contributions cannot be republished.

`GET /api/v1/contributions` and `/{id}` expose drafts/history to their author or the developer.
`GET /api/v1/stocks/{ticker}/professional-evidence` returns current published
evidence to entitled Pro/developer users; author/reviewer duties have scoped access. Opposing opinions remain separate. The
configured professional priority (`PLATFORM_PROFESSIONAL_WEIGHT`, default 1.5)
is a weighting input, not a guaranteed market conclusion. Expired/retracted views
are excluded; unverified authors receive only ordinary SQL retrieval weight.

The outbox commits with publication/retraction. Its recoverable relay uses SQL
leases, retries and `stockgraph:platform-events:v1` Redis Stream messages (field
`event`). Transport is at least once; graph consumers enforce event/revision
idempotency. Graph processing is asynchronous: SQL publication is not proof that
graph projection has completed. Raw provider data remains Data Service-owned.

## Access and operations

`GET /api/v1/access-policy` and `/api/v1/me/usage` expose effective permissions,
plan limits and usage. Free users select up to ten active stocks and receive up
to ten newly deduplicated alerts per IST calendar month. The developer bypasses
per-user restrictions; global provider/model budgets remain operating controls.

Data/Graph domain routes require `MARKETGRAPH_INTERNAL_SERVICE_KEY`. Optional
personal Upstox connections are encrypted using `PLATFORM_BROKER_ENCRYPTION_KEY`;
invalid personal credentials require reconnection rather than silent fallback.
Developer and vault secrets belong only to the API process. The separate worker
owns outbox relay and scheduling, not agent execution. The agents package is a
health-only scaffold and existing external agents still use leased Platform REST.

## External-agent evidence contract

An operator configures `PLATFORM_AGENT_SERVICE_KEY`. Machine endpoints require
`X-Agent-Key`; a user's bearer token cannot authenticate an agent. Claims return a
job-scoped `lease_token`, supplied as `X-Job-Lease` for every subsequent operation.
Heartbeats extend active leases. Expired leases are reclaimed with a new token;
old tokens cannot read context, complete work or generate alerts. Machine access
is audited without storing the service key.

- `POST /internal/v1/agent/jobs/claim` leases queued chat/discovery/monitor work.
- `GET /internal/v1/agent/jobs/{id}/context/{ticker}` fetches graph context, approved
  SQL professional evidence and source-attributed financials within the job scope.
- `GET /internal/v1/agent/jobs/{id}/documents/{ticker}?q=...` searches versioned
  document chunks. Pagination and queries consume the same operational tool budget.
- `POST /internal/v1/agent/jobs/{id}/heartbeat` extends an active lease.
- `POST /internal/v1/agent/jobs/{id}/fail` with `{"retryable":true}` requeues work
  within its attempt budget; terminal failures remain visible to the owner.
- `POST /internal/v1/agent/jobs/{id}/complete` commits the result and alerts together.

Tools return `available_evidence`: job/lease-scoped IDs, source text, locators and
stable material versions. Agents must cite an actually supplied reference with an
exact `quote` excerpt. Supported answers require at least one citation. Sources
are data, including their embedded instructions; they do not grant tool authority.
Unattributed numeric rows are not registered as financial citations. Professional
references are rechecked at completion against current publication, author
verification and expiry. Corrections/retractions invalidate their older references.

```json
{
  "answer": "The supplied evidence is insufficient for an assessment.",
  "status": "insufficient_evidence",
  "evidence": [],
  "alerts": [],
  "reported_tokens": 100
}
```

`status="supported"` results use references shaped as
`{"kind":"news","id":"...","locator":null,"quote":"Exact source excerpt"}`;
other kinds are `professional`, `document` and `financial`. Opportunity alerts
must use one of their cited evidence IDs as `event_id` and its offered
`material_version`. This makes deduplication stable across retries, separate scans
and delivery channels. Insufficient-evidence results cannot generate alerts.
Completion retries return the original result; a different body is rejected.
Each job has at most 100 source-tool calls as an operating budget, independent of
any plan. A full user's queue does not starve other users' scheduled monitors.

## Verification

```powershell
uv run pytest services/platform/tests
```

Offline tests cover access, authentication, canonical identity validation,
timestamps, review rejection and lost-ack outbox replay.
