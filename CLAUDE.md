# CLAUDE.md — Master AI Coding Instructions & Project Blueprint

> **CRITICAL FOR AI CODING AGENTS (Cursor / Claude Code / Windsurf):**
> Before writing, refactoring, or planning any code, read this file completely and consult the linked specification files in `/docs/`. Never violate the Architectural Invariants in Section 3.

> **Current deployment structure:** `docs/04_SERVICE_BOUNDARIES.md` supersedes the
> former root-package layout. Deployable code lives only in `services/upstox/`
> and `services/stockgraph/`; the repository root is a non-package workspace.

---

## 1. Documentation Index (Read Before Coding)
When implementing specific modules, load the corresponding detailed specification from `/docs/`:
1. **[`docs/01_USE_CASE_AND_SOURCES.md`](docs/01_USE_CASE_AND_SOURCES.md)** — Complete business use case, problems solved, multi-cadence schedule (Daily, Bi-Monthly, Quarterly), and exact Indian market data sources (NSE/BSE/RBI/AMFI).
2. **[`docs/02_SYSTEM_DESIGN.md`](docs/02_SYSTEM_DESIGN.md)** — Dual-database architecture (`FalkorDB` + `PostgreSQL/TimescaleDB`), exact Graph Node/Edge topology, OpenCypher queries, SQL DDL, and REST/MCP API contracts.
3. **[`docs/03_CLASS_DIAGRAM.md`](docs/03_CLASS_DIAGRAM.md)** — Complete Mermaid OOP Class Diagram, Python Pydantic models, abstract interfaces, and repository method signatures.

---

## 2. Project Summary & Phase Split
We are building a **Temporal GraphRAG + Time-Series Stock Intelligence Platform** for Indian Equities (NSE/BSE).

* **Phase 1 (CURRENT FOCUS — Build Now):**
  - Build a scheduled **Multi-Cadence Ingestion Engine** (no realtime/websockets). A **30-minute cron runs news-only** (RSS feeds + NSE/BSE Reg-30 corporate announcements). Price/metric cadences record **two daily checkpoints per ticker**: Market Open (~9:30 AM IST) and Market Close (~7:00 PM IST with official NSE Bhavcopy delivery data). Monthly/Bi-Monthly macro & MF holdings use abstract base interfaces (`BasePeriodicMacroIngestor`) with pending implementation stubs; Quarterly/Annually earnings and filings run on corporate calendar.
  - Sourcing & Charting Separation: **Frontend UI renders interactive candlestick charts using TradingView (Lightweight Charts)** directly in the browser. Backend TimescaleDB does **not** store heavy tick or minute chart series; it stores only the 2 lightweight daily session checkpoints (`OPEN` and `CLOSE`). Official exchange Bhavcopy (`sec_bhavdata_full.csv` from NSE) is the **primary source of truth** for Delivery % and turnover. Third-party vendor adapter (`ChartProviderAdapter`, e.g. Upstox) provides opening/closing price checkpoints.
  - Store normalized numeric time-series in **PostgreSQL/TimescaleDB** (SQL-only, never in graph) and store ontology, news impact paths, balance-sheet snapshots, institutional deals, MF holdings, and vector-embedded text chunks in **FalkorDB**.
  - Expose a **Stock Context Service (FastAPI REST API + MCP Tool Server)** that returns a complete **Stock Dossier** for exactly one window: `window=LAST_6M | LAST_1Y`. No arbitrary `from_date/to_date`, no all-time mode.
* **Phase 2 (DEFERRED — Do Not Build Yet):**
  - The downstream **Trading Decision Engine** that consumes the Phase 1 Stock Context Service to output `BUY`, `SELL`, or `HOLD` signals.

---

## 3. Non-Negotiable Architectural Invariants (Guardrails)

### Rule 1: Mandatory FalkorDB for Unified Graph + Vector RAG
- Use **FalkorDB** (`falkordb` Python SDK) for ALL graph relationships and vector embeddings (`vecf32`). All vector searches (`CALL db.idx.vector.queryNodes(...)`) and vector insertions on nodes MUST wrap the vector parameter with `vecf32($embedding)`.
- **DO NOT** install or configure Neo4j, Qdrant, Pinecone, Milvus, Chroma, or Weaviate. FalkorDB handles both OpenCypher graph traversal and vector similarity search natively.

### Rule 2: Strict Dual-Store Data Separation (No Numbers in Graph)
- **PostgreSQL / TimescaleDB** stores ALL numeric series, fetched via `ChartProviderAdapter` + NSE Bhavcopy and staged in `vendor_quotes_raw (vendor_id, ticker, trade_date, series, payload jsonb, fetched_at)` before normalization into: `daily_stock_metrics` with composite primary key `(trade_date, session_type, ticker)` storing two rows per day (`OPEN` for opening sentiment/price; `CLOSE` for close price, Bhavcopy delivery %, P/E, P/B, EV/EBITDA + `vendor_id, vendor_as_of`), `daily_macro_and_flows` (Crude/Steel/USD-INR, FII/DII), `quarterly_financials` (full P&L/BS/CF), `institutional_deals_raw`, `monthly_mf_holdings_raw` (interface abstract/pending), plus ops table `ingest_runs`. Quant anomalies are **SQL-only computed columns/queries** on the `CLOSE` session (`WHERE session_type = 'CLOSE' AND abs(delivery_20d_zscore) >= 1.8`) — never graph nodes.
- **FalkorDB** stores:
  1. **Static Market Ontology:** `(:Stock)`, `(:Sector)`, `(:Commodity)`, `(:Currency)`, `(:MacroFactor)` and their structural exposure edges (`[:EXPOSED_TO]`, `[:BELONGS_TO]`, `[:SENSITIVE_TO_MACRO]`).
  2. **1-Hop & 2-Hop News Events:** `(:NewsEvent)` with vector embeddings (`vecf32`), sentiment, causal edges (`[:DIRECTLY_IMPACTS]`, `[:SHOCKS]`, `[:IMPACTS_SECTOR]`, `[:ALTERS_MACRO]`), plus dedup edge `[:DUPLICATE_OF]` (see Rule 5).
  3. **Institutional Footprint:** `(:InstitutionalActor)-[:EXECUTED_DEAL]->(:Stock)` (Bulk, Block, Insider deals) and `(:MutualFundHouse)-[:UPDATED_HOLDING]->(:Stock)`.
  4. **Quarterly Snapshots & Guidance RAG:** `(:QuarterlySnapshot)` (key BS ratios only: `debt_to_equity`, `promoter_pledge_pct`, `fcf_cr`, margins) and vector-indexed `(:GuidanceChunk)` nodes. Full statements live in SQL.
- Every dossier quant value MUST cite `vendor_id + vendor_as_of` for traceability.

### Rule 3: Fixed Window Temporal Filtering (`window=LAST_6M | LAST_1Y`)
The dossier API accepts exactly one window — no arbitrary `from_date/to_date`, no all-time mode:
- `LAST_6M` → `[now-180d, now]`, `LAST_1Y` → `[now-365d, now]`, resolved IST-aware (`Asia/Kolkata` start-of-day → UTC epoch `start_ts/end_ts`).
- **Point-in-Time Nodes/Edges** (`NewsEvent`, `EXECUTED_DEAL`):
  - Must have `event_ts: int` and `event_date: str` (`YYYY-MM-DD`).
  - Filtered via: `WHERE n.event_ts >= $start_ts AND n.event_ts <= $end_ts`, with per-section `LIMIT` so windows stay bounded.
- **Validity-Interval Nodes/Edges** (`QuarterlySnapshot`, `GuidanceChunk`, `UPDATED_HOLDING`):
  - Must have `valid_from_ts: int`, `valid_to_ts: int` (`9999999999` if currently active), and `is_latest: bool`.
  - When a new quarter/month arrives, close the previous node (`valid_to_ts = new_valid_from_ts - 1`, `is_latest = false`) and link `(new)-[:SUPERSEDES]->(old)`.
  - Filtered via interval overlap: `WHERE q.valid_from_ts <= $end_ts AND q.valid_to_ts >= $start_ts`.
- **Retention:** graph keeps 1Y + 30d grace; SQL keeps full history with compression. Both window queries are always bounded and cacheable (2 keys per ticker).

### Rule 4: Canonical Entity Resolution (Zero Duplicate Nodes)
- Never allow an LLM or scraper to create free-text `:Stock`, `:Commodity`, or `:MacroFactor` nodes.
- All entity strings must pass through `CanonicalEntityResolver` first to resolve to an official NSE `ticker` / `ISIN` or a registry ID from `services/upstox/src/upstox_service/resources/ontology_seed.yaml`.
- The YAML registry is the source of truth. Adding a commodity/currency/macro/sector = 1 YAML entry + reseed. Never hardcode new IDs in code.

### Rule 5: Multi-Layered News Deduplication (Zero Duplicate Impact Paths)
Three layers run at different stages; thresholds come from settings (`dedup_cosine_threshold=0.92`, `dedup_window_hours=48`), never hardcoded:
- **L1 — Exact Match at ingestion:** canonicalize `source_url` (strip tracking params) and check Redis `SETNX seen:<url_hash>` before any write. Exact URL hits are dropped without further work.
- **L2 — Near-Duplicate Detection before chunking:** normalize the headline (lowercase, strip punctuation/source suffixes) and compare against the same ticker's items within the dedup window. Text matches link `(dup)-[:DUPLICATE_OF]->(canonical)` — no chunking or embedding is spent on the dup.
- **L3 — Semantic Deduplication during vector storage:** after embedding, run the 48h vector search; cosine > threshold links `(dup)-[:DUPLICATE_OF]->(canonical)` instead of creating new impact edges. Keep the earliest item canonical.
- News node id is deterministic: `sha1(normalized_headline + ticker + event_date)`; always `MERGE (n:NewsEvent {id})`, never bare `CREATE`.
- Source priority on conflict: Reg-30 filing > BSE > NSE > media RSS. Lower-priority sources never overwrite the canonical summary.

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
├── services/upstox/src/upstox_service/      # Providers, TimescaleDB, jobs, outbox
├── services/stockgraph/src/stockgraph/      # FalkorDB, LLM, graph API/MCP
├── contracts/events-v1.schema.json          # Cross-service wire contract
├── scripts/                                 # Project operations and verification
├── tests/integration/                       # Cross-service integration tests
├── docs/04_SERVICE_BOUNDARIES.md            # Authoritative architecture
├── docker-compose.yml
├── pyproject.toml                           # Non-package uv workspace root
└── .env.example
```

> **Fix-only scope note:** `processors/`, `ingestion/`, `services/`, and `api/` modules are **deferred — interfaces specified in `docs/03`, not yet implemented**. This pass only fixes markdown + existing files (`docker-compose.yml`, `pyproject.toml`, `config/`, `domain/`, `repositories/`, `tests/`).

---

## 5. Step-by-Step Vibe Coding Implementation Order
When asked to build the project, execute in these exact milestones:
- **Milestone 1 (Infra & Schemas):** Maintain `docker-compose.yml`, the uv workspace manifests, service-local domain models, and database initialization in the owning service repositories.
- **Milestone 2 (Static Ontology & Entity Resolver):** Build `ontology_seed.yaml`, `entity_resolver.py`, and seed the baseline Stocks, Sectors, Commodities, Currencies, and Macro factors into FalkorDB.
- **Milestone 3 (The Stock Context Service & API/MCP):** Build `stock_context_service.py`, `routes_stock.py`, and `mcp_server.py` with full support for `window=LAST_6M | LAST_1Y`, verified with mock seed data.
- **Milestone 4 (News & Vendor Chart Ingestion):** Implement `news_dedup.py`, `news_graph_extractor.py`, `stream_news_ingestor.py` (30m news-only), `chart_vendor_adapter.py` + vendor sync/normalization, and SQL-only `anomaly_detector.py`.
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
