# Service architecture and operating guide

> **Current release policy:** Read [PHASE2_PLATFORM.md](PHASE2_PLATFORM.md) for
> public accounts, developer administration, Free/Pro enforcement and optional
> encrypted Upstox connections. The fourth workspace package, `services/agents/`,
> includes an opt-in, developer-pilot LangGraph worker. Payments and trading remain deferred.
>
> **Original platform extension:** Read [PHASE1_PLATFORM.md](PHASE1_PLATFORM.md)
> for the new Platform Backend, separate ordinary PostgreSQL application database,
> professional publishing, permitted document originals, external-agent jobs and
> stock-connection API. Phase 2 supersedes its original unrestricted access policy.
> The two core services below preserve their existing database ownership.

This specification supersedes the older single-service folder layout, combined
dossier API, YAML-as-runtime-registry, selective macro baseline, and 30-minute
cadence in documents 01–03. Phase 2 trading decisions and order execution remain
deferred. Backend services live under `services/`; the Vite browser frontend is
in `frontend/` and connects through the Platform API. Repository-root scripts and tests are cross-service
operational tooling, not backend deployment entrypoints.

For the whole-project system design and per-service system/OOP class diagrams,
see the [architecture index](architecture/README.md).
For per-route access rules and accepted/returned data types, see the
[API access and data contracts](API_ACCESS_AND_DATA_CONTRACTS.md). The
Swagger/OpenAPI reference is the place for operation-level schemas and examples.
For chat provider selection, credentials, spend estimates and restart behavior,
see [LLM provider configuration](LLM_PROVIDER_CONFIGURATION.md).
For the selected Meta model, the StockGraph workflows that use it, separate
embedding configuration and inference controls, see
[Meta model and AI usage](AI_AND_MODEL_USAGE.md).

## Ownership and layout

Data, Graph, Platform and the opt-in Agents worker are separate Python packages
in one uv workspace, with one root lockfile.
Each image installs only its own package and dependencies. No service imports
the sibling package or reads the sibling database.

| Responsibility | Upstox / Data Service | StockGraph |
|---|---|---|
| Database | PostgreSQL/TimescaleDB | FalkorDB |
| Source integrations | Upstox, existing news providers, exchange adapters | None |
| Registry | Canonical SQL catalog and revision history | Committed catalog projection |
| Financial information | Immutable raw payloads, statements, two daily checkpoints, daily OHLCV candles, quarterly shareholding, NSE/BSE equity universe | Narrative context and source references only |
| Processing | Fetching, normalization, durable jobs/outbox | Embeddings, LLM relationships, deduplication, correlation |
| Read API | Financial data | Graph nodes, edges and related news |

Both services use Redis for transport/coordination. Provider quotas and LLM spend
ledgers are preserved across project resets. Compose enables AOF with
`appendfsync=always` so a stream write is persisted before its SQL outbox row
can be marked published.

```text
services/upstox/src/upstox_service/
  domain/                         # provider-independent contracts/resolver
  application/ingestion/          # news fetching and checkpoint orchestration
  application/stock_registration.py
  adapters/providers/upstox/      # authenticated HTTP, instruments, fundamentals
  adapters/providers/news/        # existing news providers
  adapters/repositories/timescale/
  adapters/api/                   # registration, catalog, financial reads
  runtime/                        # API, worker, scheduler, bootstrap
  resources/ontology_seed.yaml    # packaged empty-registry bootstrap
services/stockgraph/src/stockgraph/
  domain/                         # graph/API/event contracts
  application/ingestion/          # committed-event processing
  application/processors/         # ontology, news routing/dedup/correlation
  application/graph_queries/
  adapters/repositories/falkor/
  adapters/llm/
  adapters/messaging/             # Redis Streams consumption/recovery
  adapters/api/                   # source-service client and MCP
  runtime/                        # graph API and separate graph worker
```

## Flow, APIs and failure states

1. `POST http://localhost:8000/api/v1/stocks` with
   `{"query":"RELIANCE","strengths":[],"business_exclusions":[]}` delegates
   registration to the Data Service at port 8001. It responds **202**, with a
   durable job ID; it does not wait for an LLM call.
2. The Data worker resolves an official instrument identity, fetches profile and
   supported statements/price data, and commits raw SQL data, catalog revision,
   and projection event in the **same SQL transaction**. Optional unavailable
   datasets are reported as warnings, never fabricated.
3. The SQL outbox publisher writes `stockgraph:events:v1`, field `event` containing
   JSON conforming to `contracts/events-v1.schema.json`. Delivery is at least once;
   event IDs, entity revisions and graph MERGEs make replay safe.
4. StockGraph projects canonical identities, connects all stock/macro pairs,
   embeds profiles, runs context-aware inference, and checks existing canonical
   news from the past 365 days. The graph worker acknowledges only after success.
5. `GET /api/v1/jobs/{job_id}` distinguishes `pending`, `data_collection`,
   `graph_processing`, `completed`, and `failed`. Disabled/budget-exhausted/broken
   inference is not reported as completed. Pending stream messages are retried
   after worker recovery; upstream news is not fetched again for graph replay.

Data-service endpoints also include `GET /api/v1/entities`,
`POST /api/v1/entities/Commodity`, `/MacroFactor`, `/Sector`, and
`GET /api/v1/stocks/{ticker}/financials?window=LAST_6M` (or `LAST_1Y`).
Register stocks through the stock-registration endpoint, not free-text entity IDs.
Inspect each service's `/docs` or `/openapi.json` for request/response schemas.

The Data Service additionally exposes `GET /api/v1/stocks` (search with cursor
pagination), `GET /api/v1/stocks/{ticker}` (company profile),
`GET /api/v1/stocks/{ticker}/shareholding` (quarterly ownership revisions), and
`GET /api/v1/stocks/{ticker}/candles` (stored daily OHLCV). Reading an
unregistered equity may populate these SQL tables but does not register it or
publish a graph event. A separate daily 06:00 IST job refreshes the NSE/BSE
equity universe from Upstox's published instrument files.

The stock directory includes company shares only: NSE `EQ` and BSE company
trading groups, excluding fund/ETF ISINs (`INF...`). Cash segments also contain
bonds, government securities and investment trusts; those are not company
stocks. Migration `005_company_equity` marks previously imported non-stock
directory entries inactive while preserving their source payloads. Restart or
redeploy Data API, worker and scheduler together so every instrument writer uses
the same classification on future refreshes.

For local development, `uv run --package upstox-service python
scripts/populate_sample_stocks.py` manually refreshes that SQL equity directory,
then registers `LT` and `AXISBANK` through the normal Data Service job and graph
outbox flow. Pass `--symbols TCS INFY` to choose other official symbols, or
`--skip-universe-refresh` to use the current directory. The script skips stocks
already projected in FalkorDB and waits for each registration job to finish.

### Render one-off stock population

Run `scripts/populate_sample_stocks.py` as a **one-off job based on the
`data-api` service**, after deploying the updated Data Service image. The
Upstox Dockerfile includes this script at `/app/scripts/populate_sample_stocks.py`.
Do not use it as the Data API's start command or pre-deploy command: it exits
after each run and writes stock-directory and registration data.

Set `DATA_API_INTERNAL_URL` and `GRAPH_API_INTERNAL_URL` on the `data-api`
service to the internal URLs shown in each service's Render Connect panel, with
the host and port that Render reports. Keep these services and their databases
in the same Render region. The one-off job inherits the base service's
environment, so it also needs `MARKETGRAPH_INTERNAL_SERVICE_KEY` and `TIMESCALE_DSN`, `REDIS_URL`, and a valid
`UPSTOX_ANALYTICS_TOKEN` (or `UPSTOX_AUTHTOKEN`). Ensure `data-api`,
`graph-api`, `data-worker`, and `graph-worker` are running before starting it.

Set the one-off job's start command to:

```sh
sh -lc 'python /app/scripts/populate_sample_stocks.py \
  --data-url "$DATA_API_INTERNAL_URL" \
  --graph-url "$GRAPH_API_INTERNAL_URL" \
  --symbols LT AXISBANK'
```

The default run refreshes the full NSE/BSE equity directory in TimescaleDB,
then registers only the requested tickers through the normal data and graph
workers. It does not fetch complete financial history for every directory
entry. `data-scheduler` already refreshes the directory daily at 06:00 IST; if
that refresh has completed, pass `--skip-universe-refresh` to avoid repeating
it. Re-running with the same symbols is safe and skips completed graph
projections. MCP, Platform, and database services are not where this script
runs; the script reaches the Data and Graph APIs over Render's private network.

On-demand endpoints are `GET /api/v1/option-chains/expiries`,
`GET /api/v1/option-chains`, `GET /api/v1/market/smartlists/{kind}` for MTF,
options and futures, `GET /api/v1/market/institutional-flows` for FII/DII,
`GET /api/v1/market/holidays`, `GET /api/v1/market/status/{exchange}`, and
`GET /api/v1/market/{pcr|oi|change-oi|max-pain}`. Responses include source and
fetch time (plus provider time when supplied). Redis caches live data briefly
and dated results longer. These reads do not populate `daily_macro_and_flows`,
FalkorDB or the graph outbox. See the Data Service `/docs` for validated query
parameters, product/segment combinations and error schemas.

The graph endpoint is:

```text
GET /api/v1/stocks/RELIANCE/context?window=LAST_1Y&limit=50&offset=0
```

It returns `nodes`, `edges`, `direct_news`, `indirect_news`, and processing status.
Each relationship includes confidence, rationale and available provenance. An
indirect path includes both stock→commodity/macro exposure and news→shock edges,
even when the article does not name the stock. Follow `pagination.next_offset`
and preserve `pagination.as_of_ts` until every section's `has_more` is false.
Pagination snapshots expire after one hour by default; restart pagination if
the API rejects an expired snapshot.
Only `LAST_6M` and `LAST_1Y` windows are supported; no arbitrary date-range or
all-time API is added. Pagination is not a guarantee against concurrent graph
updates; callers should retry after registration completes for a consistent view.
This is graph-ready JSON, not a rendered visualization.

## Scheduling and graph rules

- A separate durable scheduler fetches news at **minute zero every hour**, IST.
  Redis locks, lease renewal, single-flight defaults, ingest-run logs and existing
  daily provider quotas are retained. Raw news is committed before graph work.
- Two daily price checkpoints remain: OPEN around 09:30 IST and CLOSE around
  19:00 IST. Official NSE Bhavcopy remains the primary delivery/turnover source;
  Upstox is not assumed to provide every requested financial/macro/delivery field.
  Daily chart candles are stored separately; no tick/minute storage,
  option-chain snapshots, order execution, or trading engine is added.
- Bootstrap creates exactly five stocks, five commodities, seven macro factors,
  and twelve sectors only when the SQL registry is empty. Startup thereafter
  does not overwrite API-maintained data. Keep the packaged seed in sync with
  the root compatibility seed when intentionally changing bootstrap defaults.
- Every stock links to every macro by policy; five seed stocks produce 35
  baseline stock/macro pairs. Macro explainer changes create interval-versioned
  history and `SUPERSEDES` links; unchanged mentions do not rotate versions.
- Typed LLM edges must resolve to committed canonical IDs and meet the configured
  confidence threshold (default 0.65). Prompts include business profiles, strengths,
  exclusions, available quarterly/guidance context and active exposures. Routing
  covers all registered stocks using token-aware batches, not a fixed eight-stock
  cap. Curated commodity exposures/inter-links remain an initial baseline.
- Graph reads exclude duplicate news and use bounded event/validity windows.
  Numeric financial series stay SQL-only. Direct database edits bypass this
  application/event contract and are not automatically inferred.

## OOP design of the Upstox integration

```mermaid
classDiagram
    class UpstoxClient {
        -SecretStr token
        -AsyncClient transport
        +get(path, params)
        +close()
    }
    class UpstoxCompanyProvider {
        -UpstoxClient client
        +resolve(query, exchange)
        +fetch_company(request) CompanyBundle
    }
    class RegistrationWorker {
        -Repository repository
        -CompanyProvider provider
        +run_once()
    }
    class DataRepository {
        +create_job(request)
        +commit_registration(job, bundle)
        +publish_outbox(publisher)
    }
    class CompanyBundle {
        <<immutable value object>>
        +entity
        +raw
        +statements
        +checkpoint
        +warnings
    }
    UpstoxCompanyProvider --> UpstoxClient : composes
    RegistrationWorker --> UpstoxCompanyProvider : injected provider
    RegistrationWorker --> DataRepository : injected repository
    UpstoxCompanyProvider --> CompanyBundle : produces
```

Credentials and transport policy stay inside the client; domain/application
objects do not expose tokens or import a vendor SDK. Future option/order-history
modules can compose the same client without coupling StockGraph to Upstox.

## Running, testing and safe reset

The standalone browser frontend is started from `frontend/` with `npm install`
and `npm run dev`; see [its README](../frontend/README.md) for its Platform API
proxy and deployment configuration. It is not currently a Compose service.

```powershell
uv sync --all-packages --group dev --inexact
docker compose up -d --build
uv run --all-packages pytest -q
```

For local Python processes, start the database containers only and run these in
separate terminals from the repository root (so the git-ignored `.env` is loaded):

```powershell
docker compose up -d falkordb timescale redis
uv run --package upstox-service upstox-api
uv run --package upstox-service upstox-worker
uv run --package upstox-service upstox-scheduler
uv run --package stockgraph-service uvicorn stockgraph.runtime.api:create_app --factory --port 8000
uv run --package stockgraph-service stockgraph-worker
```

Enable `LLM_ENABLED=true` and configure the chosen provider key for semantic
processing. Keep it false for offline tests. APIs are development/internal APIs;
domain routes require the shared internal service key; end users use Platform
accounts. Protect deployment ingress with TLS and network controls.

The graph MCP entrypoint is `uv run --package stockgraph-service --inexact stockgraph-mcp`
(local stdio transport). Set `MARKETGRAPH_PLATFORM_URL` and
`MARKETGRAPH_PLATFORM_TOKEN`; tools call authenticated Platform equivalents and
inherit account permissions. Compose has no remote HTTP MCP gateway.

Stop project API/workers/scheduler before a reset. `python -m scripts.project_data`
creates an integrity-checked local ZIP with SQL binary COPY data, graph DUMP and
project processing keys. `--reset --writers-stopped --confirm stockgraph/stock_graph`
backs up first, then clears only allowlisted local application data. No volume
deletion, database drop, Redis FLUSH, or unrelated graph removal occurs.
`--restore backups/<file>.zip --writers-stopped --confirm stockgraph/stock_graph`
backs up the current state before restoring an archive to the same local targets.
Backups are git-ignored and may contain licensed data; protect them accordingly.
