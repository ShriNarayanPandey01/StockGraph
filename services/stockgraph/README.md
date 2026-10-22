# StockGraph service

Owns FalkorDB and graph processing state in Redis. It has no SQL driver,
data-service Python dependency, provider credentials, or numeric-history API.

Run from the repository root after `uv sync --package stockgraph-service`:

```powershell
uv run --package stockgraph-service uvicorn stockgraph.runtime.api:create_app --factory --port 8000
uv run --package stockgraph-service stockgraph-worker
uv run --package stockgraph-service stockgraph-mcp
```

The worker is a separate process. It consumes committed version-1 events from
`stockgraph:events:v1` using group `graph-v1`. Failed messages remain pending
and are recovered using `XAUTOCLAIM`; successful graph work is idempotent and
acknowledged only after completion. A renewable graph-writer lock serializes
validity rotation. Each mutation verifies lease ownership. `LLM_ENABLED=false`,
an exhausted budget, malformed output, or a provider failure leaves processing
incomplete and retryable rather than reporting empty inference as success.

Configuration: `FALKOR_HOST`, `FALKOR_PORT`, `FALKOR_GRAPH_NAME`, `REDIS_URL`,
`DATA_SERVICE_URL`, and LLM/embedding settings in the root environment example.
No relational database URL belongs in this service's container environment.

## API

`POST /api/v1/stocks` forwards a validated registration request to the data
service and returns `202`. `GET /api/v1/jobs/{job_id}` merges source collection
and graph processing state. Example registration:

```json
{"query":"Reliance","exchange":"NSE","strengths":[],"business_exclusions":[]}
```

`GET /api/v1/stocks/RELIANCE/context?window=LAST_1Y&limit=50` returns graph-ready
nodes and edges, direct/indirect news, explanations, provenance, processing
status, and pagination. Only `LAST_6M` and `LAST_1Y` are accepted. Follow
`pagination.next_offset`, retaining the returned `pagination.as_of_ts`, until
it is null. Each section has an explicit `has_more` flag. Snapshots expire in
one hour by default. This API returns data, not an interactive graph frontend.

The MCP stdio tool `get_stock_graph_context` calls the same API; set
`STOCKGRAPH_API_URL` if it is not at `http://localhost:8000`.

## Inference

Canonical identity comes from committed registry projections, never YAML at
runtime. Stock profiles include strengths and business exclusions. Every
registered stock receives every macro baseline. News routing evaluates all
registered stocks in token-sized batches; aliases do not exclude unnamed
stocks. Newly registered entities replay the past year of canonical news
without refetching providers or creating duplicate news nodes. LLM outputs
must pass canonical-ID, relationship-kind, rationale, and confidence checks.

Macro identity stays stable. Actual descriptive state changes create
`MacroFactorVersion` history and `SUPERSEDES` links; ordinary news mentions do
not create macro versions. Same-second state changes use monotonically
increasing validity seconds to avoid overlapping intervals. Original source
event time is retained separately. Numeric macro observations stay upstream.
