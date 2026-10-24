# StockGraph

Three independently deployable services for Indian equity intelligence:

- **Upstox / Data Service** — stock registration, provider ingestion, PostgreSQL/TimescaleDB, hourly news scheduling, durable jobs and event publication.
- **StockGraph** — FalkorDB, embeddings, LLM-inferred relationships, historical news backfill, and paginated graph-context queries.
- **MarketGraph Platform** — authenticated free access, independent professional review, versioned evidence, external-agent jobs, watchlists, alerts and the stock-connections page. It owns a separate ordinary PostgreSQL database on the existing server.

Read [Phase 1 setup, API integration and recovery](docs/PHASE1_PLATFORM.md) before
recreating an existing Timescale container: the corrected volume mount requires
a verified migration of any data written outside the old mount.

Start with [the service architecture and operating guide](docs/04_SERVICE_BOUNDARIES.md)
for the folder structure, API examples, Upstox OOP design, deployment commands,
failure recovery and safe backup/reset procedure. Deployable code lives only
under `services/`; the repository root contains shared contracts, operations
scripts, documentation, and cross-service tests.

```powershell
uv sync --all-packages --group dev --inexact
docker compose up -d --build
uv run --all-packages pytest -q
```

Graph API: `http://localhost:8000/docs`; data API: `http://localhost:8001/docs`;
Platform API: `http://localhost:8002/docs` and connections page:
`http://localhost:8002/connections`.
Configure credentials in the git-ignored `.env`. Enable `LLM_ENABLED=true` for
semantic processing; offline/failed inference is visibly incomplete, not success.
All implemented features are free. RBAC and Pine Labs integration are Phase 2.
External research/discovery agents run separately and connect through leased APIs;
there is no live trading execution.

To verify the configured Upstox token without persisting data or publishing a
graph event, run the provider smoke test from the repository root:

```powershell
$env:PYTHONPATH = "services/upstox/src"
.venv/Scripts/python.exe scripts/verify_upstox_live.py
```

The Data Service also provides NSE/BSE equity search, company profiles,
shareholding history and daily candles, plus on-demand option chains,
smartlists, FII/DII flows, exchange holidays/status and derivatives analytics.
Unregistered stock reads do not create graph nodes. See its `/docs` for inputs.
