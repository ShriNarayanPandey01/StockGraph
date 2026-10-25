# StockGraph

Three production services and one future-agent scaffold for Indian equity intelligence:

- **Upstox / Data Service** — stock registration, provider ingestion, PostgreSQL/TimescaleDB, hourly news scheduling, durable jobs and event publication.
- **StockGraph** — FalkorDB, embeddings, LLM-inferred relationships, historical news backfill, and paginated graph-context queries.
- **MarketGraph Platform** — public accounts, developer administration, Free/Pro permissions, versioned evidence, external-agent jobs, watchlists, alerts and stock-connection APIs. It owns a separate ordinary PostgreSQL database on the existing server.

- **MarketGraph Agents template**: health-only scaffold in `services/agents/`; execution disabled, no handlers or job loop. Its optional Compose profile uses localhost:8005.

Read [Phase 2 accounts, access and broker setup](docs/PHASE2_PLATFORM.md) for the current release policy.

Read [Phase 1 setup, API integration and recovery](docs/PHASE1_PLATFORM.md) before
recreating an existing Timescale container: the corrected volume mount requires
a verified migration of any data written outside the old mount.

Start with [the service architecture and operating guide](docs/04_SERVICE_BOUNDARIES.md)
for the backend boundaries, API examples, deployment commands, failure recovery
and safe backup/reset procedure. This repository currently contains backend
services and APIs only; no browser frontend is included.

See [the architecture diagrams](docs/architecture/README.md) for the whole-project
system design and per-service system and OOP class diagrams.

```powershell
uv sync --all-packages --group dev --inexact
docker compose up -d --build
uv run --all-packages pytest -q
```

Graph API: `http://localhost:8000/docs`; data API: `http://localhost:8001/docs`;
Platform API: `http://localhost:8002/docs`. Authenticated stock connections are
available through `GET /api/v1/stocks/{ticker}/connections`.
Configure credentials in the git-ignored `.env`. Enable `LLM_ENABLED=true` for
semantic processing; offline/failed inference is visibly incomplete, not success.
The `.env` developer account has every application permission, including self-approval.
The developer assigns users Free or Pro manually; billing is disabled. A future payment provider has not been selected.
Data/Graph domain routes require `MARKETGRAPH_INTERNAL_SERVICE_KEY`; end users authenticate to Platform.
External research/discovery agents run separately and connect through leased APIs;
there is no live trading execution.

The Data Service also provides NSE/BSE equity search, company profiles,
shareholding history and daily candles, plus on-demand option chains,
smartlists, FII/DII flows, exchange holidays/status and derivatives analytics.
Unregistered stock reads do not create graph nodes. See its `/docs` for inputs.

For the disabled agent scaffold only: `docker compose --profile agents-template up -d --build agents-template`.
See [the template guide](services/agents/README.md). Personal Upstox connections are optional; shared ingestion
continues using the existing environment credential. No order execution is implemented.
