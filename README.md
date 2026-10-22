# StockGraph

Two independently deployable services for Indian equity intelligence:

- **Upstox / Data Service** — stock registration, provider ingestion, PostgreSQL/TimescaleDB, hourly news scheduling, durable jobs and event publication.
- **StockGraph** — FalkorDB, embeddings, LLM-inferred relationships, historical news backfill, and paginated graph-context queries.

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

Graph API: `http://localhost:8000/docs`; data API: `http://localhost:8001/docs`.
Configure credentials in the git-ignored `.env`. Enable `LLM_ENABLED=true` for
semantic processing; offline/failed inference is visibly incomplete, not success.
No trading execution or frontend graph UI is included.
