# API reference

This document describes the REST APIs implemented by the two independently
deployable services. It is a companion to the generated OpenAPI documentation:

| Service | Base URL | Interactive documentation | OpenAPI JSON |
|---|---|---|---|
| StockGraph (graph context) | `http://localhost:8000` | `/docs` | `/openapi.json` |
| Upstox Data Service (registration and market data) | `http://localhost:8001` | `/docs` | `/openapi.json` |

All timestamps are ISO 8601 UTC unless a field is explicitly described as an
epoch timestamp. Tickers are normalized to uppercase. These are internal/development
APIs; add authentication and network controls before exposing either service.

## Typical registration flow

Register through the StockGraph endpoint (it forwards the request to the Data
Service), poll the job, then request graph context once graph processing is complete.

```http
POST http://localhost:8000/api/v1/stocks
Content-Type: application/json

{
  "query": "Reliance",
  "exchange": "NSE",
  "strengths": ["integrated energy value chain"],
  "business_exclusions": ["do not infer crypto exposure"]
}
```

```json
{
  "job_id": "018f8e3a-1b2c-7d4e-a5f6-123456789abc",
  "state": "pending"
}
```

The response status is `202 Accepted`. Valid job states are `pending`,
`data_collection`, `graph_processing`, `completed`, and `failed`.

```http
GET http://localhost:8000/api/v1/jobs/018f8e3a-1b2c-7d4e-a5f6-123456789abc
```

```json
{
  "job_id": "018f8e3a-1b2c-7d4e-a5f6-123456789abc",
  "state": "completed",
  "ticker": "RELIANCE",
  "attempts": 1,
  "error": null,
  "warnings": [],
  "data_state": "graph_processing",
  "graph_state": "completed"
}
```

`data_state` and `graph_state` are returned by StockGraph's job endpoint. The
Data Service's equivalent endpoint returns the source job fields and, while a
job is in graph processing, may also include `graph` status.

## StockGraph API (`:8000`)

### Health and readiness

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe; no dependency check. |
| `GET` | `/ready` | Readiness probe; checks Redis and FalkorDB. Returns `503` when either is unavailable. |

Example `GET /health` response:

```json
{"service":"stockgraph","status":"ok"}
```

### Register a stock

`POST /api/v1/stocks` accepts the registration body shown in the typical flow.
`query` is required (1-50 characters) and may be a company name, ticker, or
ISIN. `exchange` is `NSE` (default) or `BSE`; `strengths` and
`business_exclusions` are optional string arrays. The request is delegated to
the Data Service and returns `202` with `job_id` and `state`.

### Get a registration job

`GET /api/v1/jobs/{job_id}` returns the combined data-collection and graph
processing state. The path parameter must be a UUID. It returns `404` if no
source job or graph job can be found.

### Get graph context

`GET /api/v1/stocks/{ticker}/context`

| Query parameter | Default | Rules |
|---|---:|---|
| `window` | `LAST_6M` | `LAST_6M` or `LAST_1Y` only. |
| `offset` | `0` | Integer `>= 0`. |
| `limit` | `50` | Integer from `1` through `200`. |
| `as_of_ts` | — | Pagination snapshot epoch. Reuse the response value; it expires after the configured one-hour maximum. |

No arbitrary date query is supported. Unknown query parameters (including
`from_date` and `to_date`) return `422`.

```http
GET http://localhost:8000/api/v1/stocks/RELIANCE/context?window=LAST_1Y&limit=50&offset=0
```

```json
{
  "ticker": "RELIANCE",
  "window": "LAST_1Y",
  "start_ts": 1729728000,
  "end_ts": 1761234567,
  "processing_status": "completed",
  "nodes": [
    {"id": "Stock:RELIANCE", "kind": "Stock", "properties": {"name": "Reliance Industries Ltd"}},
    {"id": "Commodity:BRENT_CRUDE", "kind": "Commodity", "properties": {"name": "Brent Crude"}}
  ],
  "edges": [
    {
      "id": "RELIANCE:EXPOSED_TO:BRENT_CRUDE",
      "source": "Stock:RELIANCE",
      "target": "Commodity:BRENT_CRUDE",
      "relation": "EXPOSED_TO",
      "confidence": 0.88,
      "rationale": "Refining and petrochemicals use crude as a key input.",
      "provenance": {"inferred_by": "LLM"},
      "properties": {"margin_impact": "MIXED"}
    }
  ],
  "direct_news": [
    {
      "id": "news-sha1-id",
      "headline": "Example company announcement",
      "source_url": "https://exchange.example/filings/example-announcement",
      "citation": {
        "url": "https://exchange.example/filings/example-announcement",
        "title": "Example company announcement",
        "publisher": "NSE",
        "event_date": "2026-10-22"
      },
      "impact_type": "DIRECTLY_IMPACTS",
      "confidence": 0.91,
      "rationale": "The announcement names the company."
    }
  ],
  "indirect_news": [
    {
      "id": "macro-news-sha1-id",
      "headline": "Example crude-market event",
      "via_node": "Commodity:BRENT_CRUDE",
      "exposure_confidence": 0.88
    }
  ],
  "pagination": {
    "offset": 0,
    "limit": 50,
    "has_more": {"nodes": false, "edges": false, "direct_news": false, "indirect_news": false},
    "next_offset": null,
    "as_of_ts": 1761234567
  }
}
```

`nodes` always use `{id, kind, properties}`. `edges` provide `{id, source,
target, relation}`, optional confidence/rationale, provenance, and relation
properties. Every `direct_news` and `indirect_news` card has a `citation`
object when its provider supplied an article URL: `{url, title, publisher,
event_date}`. `citation.url` is the canonical main-source article link; it is
present only when the upstream source supplied a URL. Otherwise, `citation`
is `null`. The original `source_url` is retained for compatibility.

To fetch another page, send the returned `next_offset` and preserve
`as_of_ts`:

```http
GET /api/v1/stocks/RELIANCE/context?window=LAST_1Y&limit=50&offset=50&as_of_ts=1761234567
```

A stock that has not been projected returns `404`. An expired or future
`as_of_ts` returns `422`.

### Public market-graph preview

`GET /api/v1/public/market-graph` returns one small, frontend-ready market
graph with no query parameters. It is not a graph browser or stock dossier.
The service selects up to 15 recently active, connected stocks from a rolling
30-day window, up to 10 linked Commodity/MacroFactor/Sector nodes, up to 15
canonical news nodes, and no more than 60 user-facing edges. Permanent broad
macro-baseline, duplicate, lifecycle/version, and developer-only links are
excluded. The response is cached for five minutes by default.

```http
GET http://localhost:8000/api/v1/public/market-graph
```

```json
{
  "generated_at": 1761234567,
  "start_ts": 1758642567,
  "end_ts": 1761234567,
  "selection": {
    "stock_target": 15,
    "stock_count": 12,
    "market_driver_count": 8,
    "news_count": 11,
    "edge_count": 37,
    "is_partial": true
  },
  "nodes": [
    {"id": "Stock:RELIANCE", "kind": "Stock", "properties": {"name": "Reliance Industries Ltd"}},
    {"id": "Commodity:BRENT_CRUDE", "kind": "Commodity", "properties": {"name": "Brent Crude"}},
    {"id": "NewsEvent:news-sha1-id", "kind": "NewsEvent", "properties": {"headline": "Oil supply update"}}
  ],
  "edges": [
    {"id": "...", "source": "Stock:RELIANCE", "target": "Commodity:BRENT_CRUDE", "relation": "EXPOSED_TO", "confidence": 0.88}
  ]
}
```

`selection.is_partial` is true whenever the eligible graph does not contain
enough stocks, market-driver nodes, or recent news to fill the compact target.
Unknown query parameters return `422`.

### Manual graph ingestion

The graph service offers manual-ingestion endpoints, but they deliberately do
not write arbitrary nodes or caller-supplied edges into FalkorDB. Each request
is forwarded to the Data Service, committed to the canonical SQL catalog or
raw-news store, emitted through the durable outbox, and processed by the
normal StockGraph worker. Consequently, manual submissions receive the same
LLM edge inference, confidence thresholding, news deduplication, and retries
as provider-ingested records.

| Method | Path | Use |
|---|---|---|
| `POST` | `/api/v1/manual/stocks` | Explicit alias for stock registration. It resolves an official NSE/BSE identity; it never creates a free-text stock node. |
| `POST` | `/api/v1/manual/entities/{kind}` | Add or revise a canonical `Commodity`, `MacroFactor`, or `Sector`. |
| `POST` | `/api/v1/manual/news` | Stage a human-supplied news article and enqueue normal LLM-backed graph processing. |

`kind` accepts only `Commodity`, `MacroFactor`, or `Sector`. Other node labels
and direct edge writes are rejected by design, preserving canonical identity
and preventing fabricated graph relationships.

```http
POST /api/v1/manual/entities/Commodity
Content-Type: application/json

{
  "id": "LITHIUM_CARBONATE",
  "name": "Lithium Carbonate",
  "description": "Battery-grade lithium carbonate benchmark.",
  "aliases": ["lithium"],
  "unit": "USD/tonne"
}
```

```json
{
  "entity_id": "LITHIUM_CARBONATE",
  "revision": 1,
  "changed": true,
  "state": "graph_processing"
}
```

The background graph worker projects the entity and invokes the LLM
`DynamicOntologyBuilder` against affected stock-context cards. It persists
only canonical, allowed relationships that meet the configured confidence
floor; the request cannot choose those edges.

```http
POST /api/v1/manual/news
Content-Type: application/json

{
  "headline": "Lithium carbonate prices rise on constrained supply",
  "summary": "Tighter supply lifted battery-material prices this week.",
  "source_url": "https://research.example/lithium-supply",
  "source": "Analyst research",
  "published_at": "2026-10-23T09:00:00+00:00",
  "category": "COMMODITY",
  "tickers": ["TATAMOTORS"],
  "ticker_sentiment": {"TATAMOTORS": -0.3}
}
```

```json
{
  "external_id": "manual-8ca243...",
  "state": "queued",
  "eligibility": {"source": "RULES", "reason": "CLEAR_COMMODITY"}
}
```

`tickers` must already be registered canonical tickers. `ticker_sentiment`
keys must also appear in `tickers`, and each score must be in `[-1.0, 1.0]`.
`published_at` is required and must include a timezone. When `external_id` is
omitted, the Data Service deterministically derives one from `source_url`;
submitting unchanged content again returns `state`:
`unchanged`. An eligible manual article still waits for the graph worker and
LLM to finish before its inferred edges appear in graph-context responses.

### Developer graph-edge overrides (FalkorDB)

StockGraph uses FalkorDB, not Neo4j. The developer edge API is disabled by
default and must be explicitly enabled with
`DEVELOPER_GRAPH_MUTATIONS_ENABLED=true` in a protected development/admin
environment. It writes only to FalkorDB and takes the same renewable graph
writer lease as the worker.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/developer/edges` | Create an auditable `DEVELOPER_LINK` between any two existing labeled graph nodes. |
| `DELETE` | `/api/v1/developer/edges/{edge_id}` | Delete a developer-created link. |

The submitted `relation` is stored as edge metadata; it is not interpolated
into Cypher. This permits a developer-defined semantic name without allowing
Cypher injection or arbitrary relationship labels. Direct deletion of LLM,
provider, curated, and macro-baseline edges is not exposed by this API.

```http
POST /api/v1/developer/edges
Content-Type: application/json

{
  "source": {"kind": "Stock", "id": "RELIANCE"},
  "target": {"kind": "Commodity", "id": "BRENT_CRUDE"},
  "relation": "MANUALLY_REVIEWED",
  "rationale": "Developer confirmed refinery-margin sensitivity from the latest annual report.",
  "actor": "jane@example.com",
  "confidence": 0.9,
  "metadata": {"review_ticket": "SG-123"}
}
```

```json
{
  "edge_id": "developer:9d5be0d3-3c21-4c1f-a6f2-37c09342a91c",
  "source": {"kind": "Stock", "id": "RELIANCE"},
  "target": {"kind": "Commodity", "id": "BRENT_CRUDE"},
  "relation": "MANUALLY_REVIEWED",
  "rationale": "Developer confirmed refinery-margin sensitivity from the latest annual report.",
  "actor": "jane@example.com",
  "confidence": 0.9,
  "event_ts": 1761206400,
  "metadata": {"review_ticket": "SG-123"}
}
```

```http
DELETE /api/v1/developer/edges/developer:9d5be0d3-3c21-4c1f-a6f2-37c09342a91c
```

```json
{"edge_id":"developer:9d5be0d3-3c21-4c1f-a6f2-37c09342a91c","deleted":true}
```

### Internal news eligibility endpoint

`POST /internal/v1/news/eligibility` is for the Data Service only; do not
expose it publicly.

```json
{
  "headline": "RBI keeps policy rate unchanged",
  "summary": "The MPC retained the policy rate in its latest decision.",
  "candidate_tickers": ["HDFCBANK", "RELIANCE"],
  "preliminary_category": "MACRO"
}
```

```json
{
  "eligible": true,
  "category": "MACRO",
  "reason": "Market-material macroeconomic event"
}
```

## Upstox Data Service API (`:8001`)

### Registration, jobs, catalog, and financials

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness response `{"status":"ok","service":"upstox-data"}`. |
| `POST` | `/api/v1/stocks` | Create a durable stock-registration job. Same request body and `202` response as the StockGraph registration endpoint. |
| `GET` | `/api/v1/jobs/{job_id}` | Return the source registration job. |
| `GET` | `/api/v1/entities?kind={kind}` | List canonical catalog entities; `kind` is optional: `Stock`, `Commodity`, `MacroFactor`, or `Sector`. |
| `POST` | `/api/v1/entities/{kind}` | Create/update `Commodity`, `MacroFactor`, or `Sector`; `Stock` is rejected with `422`. |
| `GET` | `/api/v1/stocks/{ticker}/financials?window={window}` | Return SQL-only daily metrics and latest raw provider statements for a registered stock. |

`POST /api/v1/entities/Commodity` example:

```json
{
  "id": "LITHIUM_CARBONATE",
  "name": "Lithium Carbonate",
  "description": "Battery-grade lithium carbonate benchmark.",
  "aliases": ["lithium"],
  "unit": "USD/tonne",
  "related_ids": [],
  "related_rationale": ""
}
```

The canonical ID must match `^[A-Z][A-Z0-9_]{0,79}$`. Entity writes are
accepted asynchronously (`202`).

`GET /api/v1/stocks/RELIANCE/financials?window=LAST_6M` example response:

```json
{
  "ticker": "RELIANCE",
  "window": "LAST_6M",
  "start_date": "2026-04-27",
  "end_date": "2026-10-23",
  "daily_metrics": [
    {
      "trade_date": "2026-10-22",
      "session_type": "CLOSE",
      "open_price": 1420.0,
      "high_price": 1435.0,
      "low_price": 1414.2,
      "close_price": 1428.6,
      "volume": 1234567,
      "delivery_pct": 48.2,
      "vendor_id": "UPSTOX",
      "vendor_as_of": "2026-10-22T13:30:00+00:00"
    }
  ],
  "statements": [
    {
      "series": "income_statement",
      "vendor_id": "UPSTOX",
      "vendor_as_of": "2026-10-22T13:30:00+00:00",
      "payload": {"reporting_period": "FY2026"}
    }
  ]
}
```

`window` is required and accepts only `LAST_6M` or `LAST_1Y`. The `payload`
field is an unmodified provider statement, so its contents vary by statement
series. Missing/unregistered stocks return `404`.

### Stock discovery and company data

| Method | Path | Query parameters |
|---|---|---|
| `GET` | `/api/v1/stocks` | `query` (default empty), `exchange` (`NSE`/`BSE`), `cursor`, `limit` (1-100; default 50) |
| `GET` | `/api/v1/stocks/{ticker}` | `exchange` (`NSE` default or `BSE`) |
| `GET` | `/api/v1/stocks/{ticker}/shareholding` | `exchange` (`NSE` default or `BSE`) |
| `GET` | `/api/v1/stocks/{ticker}/candles` | `exchange`; `from` and `to` as `YYYY-MM-DD` |

Search example:

```http
GET /api/v1/stocks?query=reliance&exchange=NSE&limit=1
```

```json
{
  "items": [
    {
      "exchange": "NSE",
      "instrument_key": "NSE_EQ|INE002A01018",
      "trading_symbol": "RELIANCE",
      "isin": "INE002A01018",
      "name": "Reliance Industries Limited",
      "short_name": "Reliance",
      "source_as_of": "2026-10-23T00:00:00+00:00",
      "registered": true
    }
  ],
  "next_cursor": null
}
```

Daily candle response shape:

```json
{
  "exchange": "NSE",
  "ticker": "RELIANCE",
  "isin": "INE002A01018",
  "from_date": "2026-10-01",
  "to_date": "2026-10-23",
  "vendor_id": "UPSTOX",
  "candles": [
    {"trade_date":"2026-10-22","open":1420.0,"high":1435.0,"low":1414.2,"close":1428.6,"volume":1234567,"vendor_id":"UPSTOX","vendor_as_of":"2026-10-22T13:30:00+00:00"}
  ]
}
```

Shareholding responses return `exchange`, `ticker`, `isin`, `vendor_id`,
`vendor_as_of`, and `periods`. Each period contains `period`, optional
`promoters`, `fii`, `dii`, `public`, and a `breakdown` object.

Company-profile responses (`GET /api/v1/stocks/{ticker}`) include
`profile.prospectus_links`, an array of `{document_type, url}` objects. The
Data Service obtains these only from a matching Upstox IPO detail record:
`document_type` is `DRHP` (Draft Red Herring Prospectus) or `RHP` (Red Herring
Prospectus). The array is empty when Upstox has no matching IPO document; the
service never manufactures a filing URL.

```json
{
  "exchange": "NSE",
  "trading_symbol": "EXAMPLEIPO",
  "isin": "INE123A01010",
  "profile": {
    "business_summary": "Example company profile.",
    "sector": "Industrials",
    "prospectus_links": [
      {"document_type": "DRHP", "url": "https://issuer.example/drhp.pdf"},
      {"document_type": "RHP", "url": "https://issuer.example/rhp.pdf"}
    ]
  },
  "vendor_id": "UPSTOX",
  "vendor_as_of": "2026-10-23T09:00:00+00:00"
}
```

### On-demand market data

All endpoints in this section return the envelope below. `data` is typed for
the documented endpoint; fields deliberately passed through from Upstox may be
extended by the provider.

```json
{
  "source": "UPSTOX",
  "fetched_at": "2026-10-23T09:00:00+00:00",
  "provider_as_of": "2026-10-23T08:59:00+00:00",
  "data": {}
}
```

| Method | Path | Required query parameters |
|---|---|---|
| `GET` | `/api/v1/option-chains/expiries` | `underlying`; optional `exchange=NSE\|BSE` |
| `GET` | `/api/v1/option-chains` | `underlying`, `expiry` (`YYYY-MM-DD` or supported relative expiry); optional `exchange` |
| `GET` | `/api/v1/market/smartlists/{kind}` | `kind`: `mtf`, `options`, or `futures`; `options`/`futures` also require `asset_type` and `category` |
| `GET` | `/api/v1/market/institutional-flows` | `investor=FII\|DII`, `segment`; optional `interval=1D\|1M`, `from` |
| `GET` | `/api/v1/market/holidays` | optional `date=YYYY-MM-DD` |
| `GET` | `/api/v1/market/status/{exchange}` | exchange such as `NSE`, `BSE`, `NFO`, or `MCX` |
| `GET` | `/api/v1/market/{pcr\|oi\|change-oi\|max-pain}` | `underlying`, `expiry`, `date`; see interactive docs for metric-specific interval parameters |

Option-chain example:

```http
GET /api/v1/option-chains?underlying=NIFTY&exchange=NSE&expiry=current_week
```

```json
{
  "source": "UPSTOX",
  "fetched_at": "2026-10-23T09:00:00+00:00",
  "provider_as_of": null,
  "data": {
    "underlying": "NIFTY",
    "exchange": "NSE",
    "instrument_key": "NSE_INDEX|Nifty 50",
    "expiry": "current_week",
    "strikes": []
  }
}
```

For smartlists, `mtf` accepts pagination only. `options` and `futures` require
`asset_type` (`INDEX`, `STOCK`, or `COMMODITY`) plus a supported category. For
analytics, `change-oi` accepts `interval`; `pcr` and `max-pain` accept
`bucket_interval`; `oi` accepts neither.

## Errors

FastAPI validation errors use status `422`. Application errors use a simple
detail payload:

```json
{"detail":"Stock is not yet projected; check its registration job"}
```

Common statuses: `404` for unknown/unavailable resources, `422` for invalid
parameters or unsupported combinations, `502` for invalid upstream responses,
and `503` for unavailable dependencies, authorization/entitlement problems, or
temporary provider failures.
