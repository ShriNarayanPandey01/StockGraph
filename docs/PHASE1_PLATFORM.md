# Original platform implementation and operations

> Current account, permission and broker behavior is defined by
> [Phase 2 operations](PHASE2_PLATFORM.md). The original unrestricted-access
> policy below has been replaced; database ownership/recovery guidance remains.

This document extends `04_SERVICE_BOUNDARIES.md`. The Data and Graph services
keep their existing ownership. `services/platform` is a third independently
deployable package; its database is ordinary PostgreSQL on the same server.

## Current release policy

The platform now enforces Free/Pro permissions and selected-stock/alert limits.
The environment-managed developer account has all supported application access,
including self-approval. Other publication requires authorized independent review.
Payments are disabled; the future provider is undecided. Historical replay and
order execution remain deferred. `services/agents/` provides an opt-in LangGraph
worker for a developer-only research, discovery, and monitoring pilot.
See [Phase 2](PHASE2_PLATFORM.md) for authentication, migration and quota details.

## Ownership and deployments

| Unit | Ownership | Default local port |
|---|---|---|
| Data API / worker / scheduler | Sources, SQL catalog, numerical history, immutable original documents | 8001 |
| Graph API / worker | FalkorDB, vectors, ontology, projected professional evidence, citations | 8000 |
| Platform API / worker | Users/tokens, versions/reviews, agent jobs, watchlists, alerts, usage | 8002 |

The `platform-db-init` one-shot creates `marketgraph_platform` and its dedicated
non-superuser owner. The API/worker never receive the administrator DSN. Existing
database ownership must match; bootstrap never takes over another database or
silently changes an existing role's password. Runtime database ownership is
separate from the Data Service, even though CPU, RAM and disk are shared. There
are no sibling-package imports or cross-database SQL queries.

Platform migrations are numbered, checksummed and applied transactionally under
an advisory lock. Data schemas adopt idempotent baselines through a checksummed
migration journal. Never edit an already-applied migration; append a new one.

## Start safely

**Existing Timescale installations:** the previous Compose mount targeted
`/var/lib/postgresql/data`, while the HA image uses `/home/postgres/pgdata/data`.
Compose now mounts the latter. Do not recreate an existing container until its
current data is backed up and its actual PGDATA/mounts checked. A new mount does
not migrate an old container's writable-layer data.

1. Stop application writers (including both new platform processes) for a
   coordinated backup. If the old container runs, take a native `pg_dumpall`
   backup outside the container before replacing it; verify the archive and
   restore into a separate PostgreSQL instance before cutover. Keep the old
   container stopped, available and unremoved until restore verification passes.
2. For a fresh database or after verified migration, run:

```powershell
uv sync --all-packages --group dev --inexact
docker compose up -d --build
docker compose run --rm platform-api marketgraph-platform provision-user --name "Researcher"
docker compose run --rm platform-api marketgraph-platform provision-user --name "Analyst" --professional-verified
```

The provisioning CLI prints an opaque token once. Only its SHA-256 digest is
stored. Use `Authorization: Bearer <token>`, keep tokens out of URLs/logs, and
use the operator CLI for rotation or professional verification/revocation.
There is no default token, anonymous user impersonation or self-verification API.
The developer assigns reviewer permissions. Non-developer self-review is rejected;
the developer can override publication and ownership restrictions with an audit
record. Current signup behavior is described in Phase 2. TLS and
private infrastructure networking remain deployment concerns.

Local processes use `.env.example` as a reference. Local developer setup may
initialize missing secrets in ignored `.env` without displaying them.
Set `PLATFORM_DATABASE_DSN`, `PLATFORM_REDIS_URL` (6380 locally), and service URLs.
Run `uv run --package marketgraph-platform marketgraph-platform migrate`, then:

```powershell
uv run --package marketgraph-platform uvicorn marketgraph_platform.api:create_app --factory --port 8002
uv run --package marketgraph-platform marketgraph-platform-worker
```

The Compose platform API binds to loopback. Existing Data/Graph APIs remain
internal/development interfaces and must be protected by network controls.

## Professional publication and research

Create a draft with canonical ticker, title/body, direction, horizon, event time,
future expiry, disclosures and one or more citations. Submit a frozen version,
then have an assigned independent reviewer approve it (the developer can self-approve). The author must have active
professional verification. Mutations use expected revisions; draft creation uses
an idempotency key. Publication and its outbox event commit together.

The Graph worker consumes `stockgraph:platform-events:v1` independently of the
existing source stream. Event IDs and aggregate revisions prevent duplicate or
out-of-order publication from reviving retracted evidence. SQL publication and
graph projection are separate states; a newly published version can be waiting
for graph processing. Corrections preserve previous published evidence until a
replacement is approved. Draft revisions are not public. Author verification
changes also emit events so revoked credentials lose the expert boost.

Professional evidence defaults to weight **1.5**, ordinary evidence to **1.0**.
Configure Graph `PROFESSIONAL_EVIDENCE_WEIGHT` and Platform
`PLATFORM_PROFESSIONAL_WEIGHT` identically; Compose maps one setting to both.
Expired/retracted/superseded evidence is excluded from current priority. The
policy compares the same stock/horizon, retains contradictions, and permits
strong opposing evidence to outweigh a professional view. External agents must
honor the returned policy and provide inspectable citations. It is not a win
probability or an order instruction.

## Source documents and financial context

The Data API accepts explicitly permitted PDF or UTF-8 text originals as base64
JSON through operator-authenticated `POST /api/v1/documents`. Configure
`DOCUMENT_INTERNAL_API_KEY`; an empty key disables intake. The server does not
fetch caller-provided URLs. Source URLs are citations. Declare
`redistribution_permitted: true` only for content that can be stored/displayed.

Originals are content-addressed, fsynced and immutable under
`DOCUMENT_STORAGE_ROOT` (a shared Compose volume). SQL holds versions, pages,
chunks, page/character locators and an outbox event. Empty, oversized, encrypted
or textless/scanned PDFs are rejected; OCR is not implemented. The Graph worker
projects document chunks and guidance, with FalkorDB `vecf32` embeddings when
enabled. When `LLM_ENABLED=false`, citation reads work and semantic state remains
explicitly pending. Stored document versions are referenceable by professional
citations. These are public, permitted reference documents, not private drafts.

Provider financial statements remain raw SQL vintages and are normalized where
supported. Available statement/guidance narratives populate stock context;
missing values remain absent. This does not create unsupported vendor datasets
or a new scheduled AMFI/macro source. Existing hourly news, daily checkpoints and
source quotas remain; checkpoint catch-up and revision sweeps are bounded.

## External-agent integration

Users create conversations, messages, discovery scans, watchlists and monitor
rules through Platform REST. Jobs are SQL-owned, associated with the authenticated
user, and idempotent. The worker coalesces due monitor evaluations. No plan limit
is applied; pending-job ceilings and minimum intervals are operational controls.

Configure a separate `PLATFORM_AGENT_SERVICE_KEY`. External agents authenticate
with `X-Agent-Key`, claim work, and use the returned `X-Job-Lease` on context,
document, heartbeat, completion and failure requests. User identity is inherited
from the job, never supplied by the agent as an arbitrary user ID. Leases expire,
heartbeat extensions require a live lease, and attempts are bounded. Empty
service-key configuration disables machine intake.

Tools expose bounded context and available evidence. Results must cite the
returned evidence identifiers and exact source quotes; professional citations
are checked against current publication/verification/expiry. Unsupported answers
use `status: insufficient_evidence` without opportunity alerts. Sources are
untrusted data; source text cannot grant permissions. A job has a bounded tool
budget and machine actions are audited. Reported token counts are telemetry,
not independently verified provider charges.

Completing a job atomically stores the answer, usage and canonical in-app alerts.
Retries and the same canonical event/material version do not duplicate alerts.
Telegram/WhatsApp delivery and their consent flows remain follow-on integrations;
the current delivery channel is the durable in-app feed.

## Client applications

The Vite browser frontend is in `frontend/`; it is run separately from Docker Compose.
The backend capabilities remain available through the authenticated Platform,
Data and Graph REST APIs and the original local stdio MCP tool. No remote HTTP
MCP gateway is deployed by Compose. Stock relationship data
is available through `GET /api/v1/stocks/{ticker}/connections`; callers should
preserve `pagination.as_of_ts` across pages. The opt-in worker and separately
hosted external agents claim jobs through the Platform agent API. Market
relationships provide context and do not establish causation or issue orders.

## Backup, restore and validation

Stop all writers for a coordinated Data/Graph/Platform backup. `scripts.project_data`
includes Data SQL, original document objects, FalkorDB and processing Redis keys;
`python -m scripts.platform_data` separately backs up Platform SQL. Keep matching
archives together. Platform restore accepts only an empty initialized local
target with matching migrations and requires explicit stopped-writer confirmation.
It never deletes existing records. Do not run a standalone graph reset against
live Platform publication records.

```powershell
uv run --all-packages pytest -q -p no:cacheprovider --basetemp=.cache/pytest-check
uv run --all-packages ruff check services scripts tests
```

The remaining tests run offline and do not validate live provider access or
production persistence.
