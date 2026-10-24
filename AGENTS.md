# AGENTS.md — Master AI Coding Instructions & Project Blueprint

> **Current deployment architecture:** Read [docs/04_SERVICE_BOUNDARIES.md](docs/04_SERVICE_BOUNDARIES.md) first. It supersedes the legacy single-service layout, combined dossier, selective macro baseline, YAML runtime registry, and 30-minute news cadence below. Production services are `services/upstox/` (SQL/source ingestion) and `services/stockgraph/` (FalkorDB/LLM), with hourly news and API registration.

> **Phase 1 platform extension:** [docs/PHASE1_PLATFORM.md](docs/PHASE1_PLATFORM.md)
> adds `services/platform/` with its own ordinary PostgreSQL database on the same
> server. All implemented features are free, including professional evidence.
> RBAC and Pine Labs payment integration are Phase 2; keep authentication,
> ownership, independent review and operating budgets active. External agents
> consume REST/MCP APIs. The Data/Graph ownership and FalkorDB vector rules remain.

> **CRITICAL FOR AI CODING AGENTS (Cursor / Claude Code / Windsurf):**
> Before writing, refactoring, or planning any code, read this file completely and consult the linked specification files in `/docs/`. Never violate the Architectural Invariants in Section 3.

---

## 1. Documentation Index (Read Before Coding)
When implementing specific modules, load the corresponding detailed specification from `/docs/`:
1. **[`docs/01_USE_CASE_AND_SOURCES.md`](docs/01_USE_CASE_AND_SOURCES.md)** — Complete business use case, problems solved, dynamic LLM-driven ontology flow, multi-cadence schedule (Daily, Bi-Monthly, Quarterly), and exact Indian market data sources (NSE/BSE/RBI/AMFI).
2. **[`docs/02_SYSTEM_DESIGN.md`](docs/02_SYSTEM_DESIGN.md)** — Dual-database architecture (`FalkorDB` + `PostgreSQL/TimescaleDB`), exact Graph Node/Edge topology, dynamic exposure & news correlation OpenCypher queries, SQL DDL, and REST/MCP API contracts.
3. **[`docs/03_CLASS_DIAGRAM.md`](docs/03_CLASS_DIAGRAM.md)** — Complete Mermaid OOP Class Diagram, Python Pydantic models (`StockContextCard`, `InferredOntologyEdge`, `InferredNewsStockImpact`, `InferredNewsCorrelation`), abstract interfaces, and repository method signatures.

---

## 2. Project Summary & Phase Split
We are building a **Temporal GraphRAG + Time-Series Stock Intelligence Platform** for Indian Equities (NSE/BSE) powered by a **Context-Aware Dynamic Ontology**.

- **Phase 1 (CURRENT FOCUS — Build Now):**
  - Build a scheduled **Multi-Cadence Ingestion Engine** (no realtime/websockets). A **30-minute cron runs news-only** (paid news APIs via NewsProviderAdapter + NSE/BSE Reg-30 corporate announcements). Price/metric cadences record **two daily checkpoints per ticker**: Market Open (~9:30 AM IST) and Market Close (~7:00 PM IST with official NSE Bhavcopy delivery data). Monthly/Bi-Monthly macro & MF holdings use abstract base interfaces (`BasePeriodicMacroIngestor`) with pending implementation stubs; Quarterly/Annually earnings and filings run on corporate calendar.
  - **Curated Static Baseline + Dynamic LLM-Driven Ontology:** `ontology_seed.yaml` defines the **canonical node registry** (Stocks, Commodities, MacroFactors, Sectors — no `:Currency` nodes; USD/INR forex is a `:MacroFactor`), **rich Stock Profile descriptions** (business model, revenue segments, raw material inputs, geography), **MacroFactor explainers** (`description`, `why_it_moves`, `equity_transmission`), **Commodity inter-links** (`related_ids`, e.g. `COKING_COAL <-> HRC_STEEL`), and — by explicit operator design — a **small curated set of static edges** for macro sensitivities and stock exposures (see Rule 4 for the exact permitted categories). Everything else is LLM-inferred: the LLM receives `StockContextCard`s (stock profile + latest quarterly snapshot + concall guidance + existing exposures) to dynamically decide:
    1. Which `:Stock` relates to which `:Commodity`, `:MacroFactor`, `:Sector`, or peer `:Stock` — and which `:Commodity` relates to which `:Commodity` (`RELATED_TO`) — (`DynamicOntologyBuilder`).
    2. Which `:NewsEvent` relates to which `:Stock` (directly or indirectly) and which `:Commodity`/`:MacroFactor` it shocks (`NewsGraphExtractor`).
    3. Which `:NewsEvent`s are causally or thematically correlated with prior `:NewsEvent`s (`NewsCorrelator`).
  - **Sourcing & Charting Separation:** **Frontend UI renders interactive candlestick charts using TradingView (Lightweight Charts)** directly in the browser. Backend TimescaleDB does **not** store heavy tick or minute chart series; it stores only the 2 lightweight daily session checkpoints (`OPEN` and `CLOSE`). Official exchange Bhavcopy (`sec_bhavdata_full.csv` from NSE) is the **primary source of truth** for Delivery % and turnover. Third-party vendor adapter (`ChartProviderAdapter`, e.g. Upstox) provides opening/closing price checkpoints.
  - Store normalized numeric time-series in **PostgreSQL/TimescaleDB** (SQL-only, never in graph) and store canonical entities, curated static + dynamic LLM-inferred ontology edges, news impact paths, cross-news correlation edges, balance-sheet snapshots, institutional deals, MF holdings, and vector-embedded text chunks in **FalkorDB**.
  - Expose a **Stock Context Service (FastAPI REST API + MCP Tool Server)** that returns a complete **Stock Dossier** for exactly one window: `window=LAST_6M | LAST_1Y`. No arbitrary `from_date/to_date`, no all-time mode.
- **Phase 2 (DEFERRED — Do Not Build Yet):**
  - The downstream **Trading Decision Engine** that consumes the Phase 1 Stock Context Service to output `BUY`, `SELL`, or `HOLD` signals.

---

## 3. Non-Negotiable Architectural Invariants (Guardrails)

### Rule 1: Mandatory FalkorDB for Unified Graph + Vector RAG
- Use **FalkorDB** (`falkordb` Python SDK) for ALL graph relationships and vector embeddings (`vecf32`). All vector searches (`CALL db.idx.vector.queryNodes(...)`) and vector insertions on nodes MUST wrap the vector parameter with `vecf32($embedding)`.
- **DO NOT** install or configure Neo4j, Qdrant, Pinecone, Milvus, Chroma, or Weaviate. FalkorDB handles both OpenCypher graph traversal and vector similarity search natively (including vector indexing on `:Stock.profile_embedding`, `:NewsEvent.embedding`, and `:GuidanceChunk.embedding`).

### Rule 2: Strict Dual-Store Data Separation (No Numbers in Graph)
- **PostgreSQL / TimescaleDB** stores ALL numeric series, fetched via `ChartProviderAdapter` + NSE Bhavcopy and staged in `vendor_quotes_raw (vendor_id, ticker, trade_date, series, payload jsonb, fetched_at)` before normalization into: `daily_stock_metrics` with composite primary key `(trade_date, session_type, ticker)` storing two rows per day (`OPEN` for opening sentiment/price; `CLOSE` for close price, Bhavcopy delivery %, P/E, P/B, EV/EBITDA + `vendor_id, vendor_as_of`), `daily_macro_and_flows` (Crude/Steel/USD-INR, FII/DII), `quarterly_financials` (full P&L/BS/CF), `institutional_deals_raw`, `monthly_mf_holdings_raw` (interface abstract/pending), plus ops table `ingest_runs`. Quant anomalies are **SQL-only computed columns/queries** on the `CLOSE` session (`WHERE session_type = 'CLOSE' AND abs(delivery_20d_zscore) >= 1.8`) — never graph nodes.
- **FalkorDB** stores:
  1. **Canonical Node Catalog & Market Ontology:** Canonical nodes (`(:Stock)` with `profile_embedding`, `(:Sector)`, `(:Commodity)` with inter-links, `(:MacroFactor)` with explainers) and **ontology exposure edges** (`[:EXPOSED_TO]`, `[:BELONGS_TO]`, `[:SENSITIVE_TO_MACRO]`, `[:SUPPLIES_TO]`, `[:COMPETES_WITH]`, `[:RELATED_TO]` for commodity-to-commodity) — a curated static baseline seeded from `ontology_seed.yaml` (macro + stock exposure categories, per Rule 4) extended by **LLM-discovered dynamic edges** — carrying `exposure_nature`, `margin_impact`, `sensitivity`, `confidence`, `rationale`, `inferred_by`, and validity intervals (`valid_from_ts`, `valid_to_ts`, `is_latest`).
  2. **Context-Routed News & Cross-News Correlations:** `(:NewsEvent)` with vector embeddings (`vecf32`), sentiment, LLM-inferred causal edges (`[:DIRECTLY_IMPACTS]`, `[:INDIRECTLY_IMPACTS]`, `[:SHOCKS]`, `[:IMPACTS_SECTOR]`, `[:ALTERS_MACRO]` with `causal_rationale` and `confidence`), deduplication edge `[:DUPLICATE_OF]`, and cross-news correlation edge `[:CORRELATED_WITH {correlation_type, confidence, rationale, event_ts}]` (see Rule 5).
  3. **Institutional Footprint:** `(:InstitutionalActor)-[:EXECUTED_DEAL]->(:Stock)` (Bulk, Block, Insider deals) and `(:MutualFundHouse)-[:UPDATED_HOLDING]->(:Stock)`.
  4. **Quarterly Snapshots & Guidance RAG:** `(:QuarterlySnapshot)` (key BS ratios only: `debt_to_equity`, `promoter_pledge_pct`, `fcf_cr`, margins) and vector-indexed `(:GuidanceChunk)` nodes. Full statements live in SQL.
- Every dossier quant value MUST cite `vendor_id + vendor_as_of` for traceability.

### Rule 3: Fixed Window Temporal Filtering (`window=LAST_6M | LAST_1Y`)
The dossier API accepts exactly one window — no arbitrary `from_date/to_date`, no all-time mode:
- `LAST_6M` → `[now-180d, now]`, `LAST_1Y` → `[now-365d, now]`, resolved IST-aware (`Asia/Kolkata` start-of-day → UTC epoch `start_ts/end_ts`).
- **Point-in-Time Nodes/Edges** (`NewsEvent`, `EXECUTED_DEAL`, `CORRELATED_WITH`):
  - Must have `event_ts: int` and `event_date: str` (`YYYY-MM-DD`).
  - Filtered via: `WHERE n.event_ts >= $start_ts AND n.event_ts <= $end_ts`, with per-section `LIMIT` so windows stay bounded.
- **Validity-Interval Nodes/Edges** (`QuarterlySnapshot`, `GuidanceChunk`, `UPDATED_HOLDING`, and dynamic ontology edges `EXPOSED_TO`, `SENSITIVE_TO_MACRO`, `BELONGS_TO`, `SUPPLIES_TO`, `COMPETES_WITH`):
  - Must have `valid_from_ts: int`, `valid_to_ts: int` (`9999999999` if currently active), and `is_latest: bool`.
  - When a new quarter/month arrives or `DynamicOntologyBuilder` revises a stock's exposure, close the previous state (`valid_to_ts = new_valid_from_ts - 1`, `is_latest = false`) and link `(new)-[:SUPERSEDES]->(old)` for nodes.
  - Filtered via interval overlap: `WHERE q.valid_from_ts <= $end_ts AND q.valid_to_ts >= $start_ts`.
- **Retention:** graph keeps 1Y + 30d grace; SQL keeps full history with compression. Both window queries are always bounded and cacheable (2 keys per ticker).

### Rule 4: Canonical Node Registry + Context-Aware Dynamic Edge Synthesis
- **Strict Node Identity, Curated + Dynamic Edges:** Never allow an LLM or scraper to create free-text `:Stock`, `:Commodity`, `:MacroFactor`, or `:Sector` node IDs. There is NO `:Currency` node type — forex (USD/INR) is a `:MacroFactor` (`USD_INR_FX`). All target entity IDs produced by the LLM must pass through `CanonicalEntityResolver` to resolve to an official NSE `ticker` / `ISIN` or a registry ID from `services/upstox/src/upstox_service/resources/ontology_seed.yaml` (seed IDs: `BRENT_CRUDE`, `HRC_STEEL`, `COKING_COAL`, `USD_INR_FX`, `RBI_REPO_RATE`, `INDIA_CPI`, `INDIA_GDP_GROWTH`, `INDIA_10Y_YIELD`, `US_FED_RATE`, `GOVT_CAPEX_SPEND`, etc.).
- **Curated Static Baseline + Dynamic Extension:** `services/upstox/src/upstox_service/resources/ontology_seed.yaml` defines the **bootstrap canonical entity catalog, rich Stock Profile descriptions** (`business_summary`, `revenue_segments`, `raw_material_inputs`, `geographic_exposure`), **MacroFactor explainers** (`description`, `why_it_moves`, `equity_transmission`, `default_scope`), and **Commodity inter-links** (`related_ids` + `related_rationale`). It may declare **static edges in exactly three curated categories, and no others**: (1) `SENSITIVE_TO_MACRO` — per-stock `macro_exposures` plus the `BROAD` baseline (next bullet); (2) `EXPOSED_TO` — per-stock `exposures` operator-curated commodity lists; (3) `RELATED_TO` — commodity `related_ids` inter-links. Every other ontology edge (`SUPPLIES_TO`, `COMPETES_WITH`, peer `Stock <-> Stock` links) must be LLM-inferred via `DynamicOntologyBuilder` — never hand-added to YAML.
- **Broad Macro Baseline + Selective Refinement:** `BROAD`-scoped macro factors (`RBI_REPO_RATE`, `INDIA_CPI`, `INDIA_GDP_GROWTH`, `INDIA_10Y_YIELD`, `US_FED_RATE`, `GOVT_CAPEX_SPEND`) are seeded as permanent `(:Stock)-[:SENSITIVE_TO_MACRO]->(:MacroFactor)` edges to every stock, since macro moves hit almost all equities. `SELECTIVE` macros (`USD_INR_FX`) link only where listed. The LLM may later refine sensitivity/confidence, but the baseline is never empty.
- **Commodity Inter-Links:** `(:Commodity)-[:RELATED_TO]->(:Commodity)` edges (input/substitute linkage, e.g. `COKING_COAL -[:RELATED_TO]-> HRC_STEEL`) are seeded from `related_ids` and LLM-extensible via `InferredOntologyEdge{relation: RELATED_TO}`.
- **Mandatory Stock Context Injection (`StockProfileProvider`):** Whenever the LLM infers `Stock <-> Commodity/Currency/Macro/Sector/Stock` edges (`DynamicOntologyBuilder`) or decides which `NewsEvent` relates to which `Stock` (`NewsGraphExtractor`), the LLM prompt MUST be injected with `StockContextCard`s containing the stock's business summary, raw materials, revenue segments, latest `QuarterlySnapshot`, latest `GuidanceChunk` highlights, and current active graph exposures.
- **Confidence Thresholding:** Dynamic ontology edges and news impact edges must carry `confidence: float` (`0.0–1.0`) and `rationale: str`. Only edges with `confidence >= ontology_min_confidence` (from settings, default `0.65`) are persisted or traversed.

### Rule 5: Multi-Layered News Deduplication & Cross-News Correlation
Four layers run at different stages; thresholds come from settings (`dedup_cosine_threshold=0.92`, `dedup_window_hours=48`, `correlation_min_cosine=0.68`, `correlation_window_days=14`), never hardcoded:
- **L1 — Exact Match at ingestion:** canonicalize `source_url` (strip tracking params) and check Redis `SETNX seen:<url_hash>` before any write. Exact URL hits are dropped without further work.
- **L2 — Near-Duplicate Detection before chunking:** normalize the headline (lowercase, strip punctuation/source suffixes) and compare against items within the dedup window. Text matches link `(dup)-[:DUPLICATE_OF]->(canonical)` — no chunking or embedding is spent on the dup.
- **L3 — Semantic Deduplication during vector storage:** after embedding, run the 48h vector search; cosine >= `dedup_cosine_threshold` links `(dup)-[:DUPLICATE_OF]->(canonical)` instead of creating new impact edges. Keep the earliest item canonical.
- **L4 — Cross-News Correlation (`NewsCorrelator`):** for every newly persisted canonical `(:NewsEvent)`, query non-duplicate canonical news in the trailing `correlation_window_days` where cosine is in `[correlation_min_cosine, dedup_cosine_threshold)` or that share an impacted `:Stock`/`:Commodity`/`:MacroFactor`. The LLM evaluates candidate pairs with context and links correlated stories via `(n_new)-[:CORRELATED_WITH {correlation_type, confidence, rationale, event_ts}]->(n_prior)` where `correlation_type` $\in$ `CAUSAL_CHAIN | MACRO_CONTAGION | SECTOR_RIPPLE | FOLLOW_UP`.
- News node id is deterministic: `sha1(normalized_headline + primary_entity + event_date)`; always `MERGE (n:NewsEvent {id})`, never bare `CREATE`.
- The dedup bucket `primary_entity` is derived from the article TEXT, never from a provider's entity tags: the same story arriving from two providers must land on the same bucket, or L2/L3 cannot see them as duplicates and the graph gains two `(:NewsEvent)` nodes for one story. Provider tags drive ROUTING only.
- Source priority on conflict: Reg-30 filing > BSE > NSE > media (RSS and news-API providers share the media tier). Lower-priority sources never overwrite the canonical summary.
- News reaches the graph only through `NewsProviderAdapter` (the anti-corruption layer: provider symbols such as `SBIN.NS` become canonical tickers, and anything that does not resolve through `CanonicalEntityResolver` is dropped, never invented). Raw provider payloads are staged immutably in `news_raw` BEFORE any graph write, so LLM routing and embeddings can be replayed without re-spending metered API quota. The provider's per-entity sentiment is written to the impact edge OUTSIDE the LLM schema, so the model can never fabricate it. Provider credentials travel as query parameters and are masked by `redact_url()` before any URL reaches a log line.
- A news API is a **media** source (same tier as RSS): it never overwrites an exchange filing, and it never overwrites another media source.

### Rule 6: Hardened APScheduler (Persistence + Single-Flight)
- APScheduler runs as a **separate worker process** (`stockgraph-scheduler` entrypoint), never inside the API process.
- Durable `SQLAlchemyJobStore` (Postgres) or `RedisJobStore`; `coalesce=True`, `max_instances=1`, `misfire_grace_time=300`.
- Every job body takes a Redis distributed lock (`SET <job-name> NX EX <lease>`) and logs to `ingest_runs(status, started_at, finished_at, error)`. Overlapping runs must be impossible.

### Rule 7: Generic Vendor Adapter, Bhavcopy Primary & TradingView Charting
- **Frontend Charting:** Visual interactive candlestick charts are rendered directly on the client using **TradingView Lightweight Charts**. The backend does not store heavy intraday tick or minute data.
- **Bhavcopy as Primary Delivery Source:** Official exchange Bhavcopy (`sec_bhavdata_full.csv` from NSE) is the **primary source of truth** for Delivery % and official turnover at market close (~7:00 PM IST).
- **Vendor Adapter for Price Series:** All other numeric reads/writes go through `ChartProviderAdapter` (e.g. Upstox: `get_eod_series()`, `get_macro_series()`). No vendor SDK imports outside the adapter.
- Raw payloads land immutably in `vendor_quotes_raw` with vintage key `(vendor_id, ticker, trade_date, series, fetched_at)` — a revision inserts a new vintage, never overwrites; normalization reads the latest vintage per key (`DISTINCT ON ... ORDER BY fetched_at DESC`) and inserts two checkpoint records per day (`OPEN` and `CLOSE` session entries) into `daily_stock_metrics`.
- **Backfill watermark:** `vendor_sync_state (vendor_id, ticker, series, last_trade_date, last_fetched_at)` tracks the last data pushed per series. Each sync compares against the watermark, inserts new records, then advances the watermark. Revisions arrive as new vintages (never overwrite); a revision sweep re-fetches the trailing `vendor_revision_lookback_days` window (the watermark only moves forward) and stages changed payloads as new vintages; gaps are logged to `ingest_runs` for replay.

---

## 4. Target Repository Structure
```text
stock-graphrag-engine/
├── services/
│   ├── upstox/
│   │   ├── pyproject.toml
│   │   └── src/upstox_service/          # Providers, TimescaleDB, jobs, outbox, scheduler
│   └── stockgraph/
│       ├── pyproject.toml
│       └── src/stockgraph/              # FalkorDB, LLM processing, graph API/MCP
├── contracts/events-v1.schema.json      # Versioned cross-service wire contract
├── scripts/                             # Cross-service operations and verification
├── tests/integration/                   # Cross-service integration tests
├── docs/04_SERVICE_BOUNDARIES.md        # Authoritative deployment architecture
├── docker-compose.yml
├── pyproject.toml                       # Non-package uv workspace root
└── .env.example
```

> **Phase 1 Implementation Note:** The two service packages implement the interfaces specified in `docs/03` and the architectural invariants in Section 3. There is no deployable root package.

---

## 5. Step-by-Step Vibe Coding Implementation Order
When asked to build the project, execute in these exact milestones:
- **Milestone 1 (Infra & Schemas):** Maintain `docker-compose.yml`, the uv workspace manifests, service-local domain models, and database initialization in the owning service repositories.
- **Milestone 2 (Static Ontology & Entity Resolver):** `ontology_seed.yaml` (done), `processors/entity_resolver.py` (`CanonicalEntityResolver`, Rule 4 gatekeeper), `repositories/ontology_seeder.py` (idempotent MERGE seeder: BELONGS_TO + EXPOSED_TO + SENSITIVE_TO_MACRO with BROAD baseline + RELATED_TO commodity inter-links), and `processors/stock_profile_provider.py` (`StockContextCard` builder for LLM prompts).
- **Milestone 3 (The Stock Context Service & API/MCP):** Build `stock_context_service.py`, `routes_stock.py`, and `mcp_server.py` with full support for `window=LAST_6M | LAST_1Y`, verified with mock seed data.
- **Milestone 4 (News & Vendor Chart Ingestion):** Implement `news_dedup.py`, `news_graph_extractor.py`, `news_candidate_resolver.py`, `news_provider_adapter.py`, `news_fetch_service.py`, `stream_news_ingestor.py` (30m news-only), `chart_vendor_adapter.py` + vendor sync/normalization, and SQL-only `anomaly_detector.py`.
- **Milestone 5 (Bi-Monthly & Quarterly Ingestion):** Implement `periodic_macro_ingestor.py` and `quarterly_ingestor.py` with bi-temporal node rotation (`[:SUPERSEDES]`).

---

## 6. Multi-Agent Delegation & Cost-Optimized Parallel Execution (`spawn-opencode` Skill)
To accelerate development, avoid context bloat, and minimize token costs, agents should proactively leverage the `spawn-opencode` skill ([`SKILL.md`](.agents/skills/spawn-opencode/SKILL.md)) to distribute subtasks across parallel agent sessions:

* **Task Offloading & Parallel Work:** When tackling large, repetitive, or parallelizable subtasks (such as boilerplate generation, schema expansion, test suite generation, data fixture creation, or vendor adapter implementations), spawn parallel OpenCode CLI sessions in separate terminal windows instead of running all tasks sequentially within the primary agent session.
* **Cost Minimization with Free/Lightweight Models:**
  - Offload coding, test authoring, and mechanical refactors to free reasoning/coding models such as `opencode/deepseek-v4.1-flash-free` or `opencode/glm-5.3-flash-free`.
  - Use high-tier models primarily for overall architecture orchestration, cross-cutting schema decisions, and critical reviews.
* **Invocation Pattern:**
  - **Windows (PowerShell):**
    ```powershell
    powershell -ExecutionPolicy Bypass -File ".agents/skills/spawn-opencode/scripts/launch_opencode.ps1" -Model "opencode/deepseek-v4.1-flash-free" -Prompt "<task_prompt>"
    ```
  - **macOS / Linux / WSL:**
    ```bash
    ./.agents/skills/spawn-opencode/scripts/launch_opencode.sh "opencode/deepseek-v4.1-flash-free" "<task_prompt>"
    ```
  - Inspect `git status` and modified files upon session completion to review and integrate changes into the master branch.
