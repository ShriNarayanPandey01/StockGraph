# AGENTS.md — Master AI Coding Instructions & Project Blueprint

> **CRITICAL FOR AI CODING AGENTS (Cursor / Claude Code / Windsurf):**
> Before writing, refactoring, or planning any code, read this file completely and consult the linked specification files in `/docs/`. Never violate the Architectural Invariants in Section 3.

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
  - Build a scheduled **Multi-Cadence Ingestion Engine** (Cron jobs running every 30 mins, Daily EOD, Monthly/Bi-Monthly, and Quarterly/Annually) that scrapes/fetches stock, macro, institutional, and news data from the internet.
  - Store raw numeric time-series in **PostgreSQL/TimescaleDB** and store causal relationships, news impact paths, anomalies, and vector-embedded text chunks in **FalkorDB**.
  - Expose a **Stock Context Service (FastAPI REST API + MCP Tool Server)** that allows any downstream AI agent or user to fetch a complete **Stock Dossier** filtered by an optional date window (`from_date` to `to_date`), or all-time history if no filter is passed (`from_date=None, to_date=None`).
* **Phase 2 (DEFERRED — Do Not Build Yet):**
  - The downstream **Trading Decision Engine** that consumes the Phase 1 Stock Context Service to output `BUY`, `SELL`, or `HOLD` signals.

---

## 3. Non-Negotiable Architectural Invariants (Guardrails)

### Rule 1: Mandatory FalkorDB for Unified Graph + Vector RAG
- Use **FalkorDB** (`falkordb` Python SDK) for ALL graph relationships and vector embeddings (`vecf32`).
- **DO NOT** install or configure Neo4j, Qdrant, Pinecone, Milvus, Chroma, or Weaviate. FalkorDB handles both OpenCypher graph traversal and vector similarity search natively.

### Rule 2: Strict Dual-Store Data Separation (No Daily Numbers in Graph)
- **PostgreSQL / TimescaleDB** stores all continuous numeric time-series: daily OHLCV, daily Delivery %, daily P/E, P/B, EV/EBITDA, daily FII/DII provisional numbers, and daily Crude/Steel/USD-INR closing prices.
- **FalkorDB** stores:
  1. **Static Market Ontology:** `(:Stock)`, `(:Sector)`, `(:Commodity)`, `(:Currency)`, `(:MacroFactor)` and their structural exposure edges (`[:EXPOSED_TO]`, `[:BELONGS_TO]`, `[:SENSITIVE_TO_MACRO]`).
  2. **1-Hop & 2-Hop News Events:** `(:NewsEvent)` with vector embeddings, sentiment, and causal edges (`[:DIRECTLY_IMPACTS]`, `[:SHOCKS]`, `[:IMPACTS_SECTOR]`, `[:ALTERS_MACRO]`).
  3. **Daily Quant Anomalies Only:** Only create a `(:DailyAnomalyEvent)` node in FalkorDB when a daily metric in PostgreSQL crosses a statistical threshold (e.g., `Delivery_Pct_20D_ZScore >= 1.8`).
  4. **Institutional Footprint:** `(:InstitutionalActor)-[:EXECUTED_DEAL]->(:Stock)` (Bulk, Block, Insider deals) and `(:MutualFundHouse)-[:UPDATED_HOLDING]->(:Stock)`.
  5. **Quarterly Snapshots & Guidance RAG:** `(:QuarterlySnapshot)` and vector-indexed `(:GuidanceChunk)` nodes.

### Rule 3: Universal Temporal Filtering (`from_date` to `to_date` OR `None`)
Every piece of dynamic information MUST carry Unix epoch timestamps (in UTC seconds) and support two query modes:
- **Point-in-Time Nodes/Edges** (`NewsEvent`, `EXECUTED_DEAL`, `DailyAnomalyEvent`):
  - Must have `event_ts: int` and `event_date: str` (`YYYY-MM-DD`).
  - Filtered via: `WHERE n.event_ts >= $start_ts AND n.event_ts <= $end_ts`.
- **Validity-Interval Nodes/Edges** (`QuarterlySnapshot`, `GuidanceChunk`, `UPDATED_HOLDING`):
  - Must have `valid_from_ts: int`, `valid_to_ts: int` (`9999999999` if currently active), and `is_latest: bool`.
  - When a new quarter/month arrives, close the previous node (`valid_to_ts = new_valid_from_ts - 1`, `is_latest = false`) and link `(new)-[:SUPERSEDES]->(old)`.
  - Filtered via interval overlap: `WHERE q.valid_from_ts <= $end_ts AND q.valid_to_ts >= $start_ts`.
- **Unfiltered Mode (`from_date=None, to_date=None`):**
  - Default `$start_ts = 0` and `$end_ts = 9999999999`.
  - In FalkorDB: Returns the full historical graph chain for the stock.
  - In PostgreSQL: Returns raw daily rows for the last 90 days + monthly aggregated summaries (min, max, mean, anomaly count) for prior years so downstream LLM agents never hit context-window overflow.

### Rule 4: Canonical Entity Resolution (Zero Duplicate Nodes)
- Never allow an LLM or scraper to create free-text `:Stock`, `:Commodity`, or `:MacroFactor` nodes.
- All entity strings must pass through `CanonicalEntityResolver` first to resolve to an official NSE `ticker` / `ISIN` or a locked enum ID (`BRENT_CRUDE`, `HRC_STEEL`, `COKING_COAL`, `USD_INR`, `RBI_REPO_RATE`, `INDIA_CPI`).

### Rule 5: Stock-to-Stock Relationships (`:Stock -> :Stock`)
FalkorDB must explicitly model inter-company relationships so users and agents can trace supply-chain contagion, peer competition, and conglomerate links:
- `(:Stock)-[:SUPPLIES_TO {component: str, revenue_dependency: "HIGH"|"MED"|"LOW"}]->(:Stock)`
- `(:Stock)-[:COMPETES_WITH {segment: str}]->(:Stock)`
- `(:Stock)-[:OWNS_STAKE_IN {stake_pct: float, relation_type: "SUBSIDIARY"|"ASSOCIATE"|"JV"}]->(:Stock)`
- `(:Stock)-[:BELONGS_TO_GROUP]->(:BusinessGroup {id: str, name: str})` (e.g., `TATA_GROUP`, `ADANI_GROUP`, `RELIANCE_GROUP`, `ADITYA_BIRLA_GROUP`)

### Rule 6: Dual API Output Modes (Agent Dossier Mode vs. Frontend Graph UI Mode)
Every temporal query in `FalkorGraphRAGRepository` must support two output serializers:
1. **Agent Dossier Mode (`/api/v1/stocks/{ticker}/dossier`):** Hierarchical JSON optimized for LLM reasoning and Phase 2 trading bots.
2. **Graph Visualization UI Mode (`/api/v1/graph/...`):** Flat `{ "nodes": [...], "links": [...] }` JSON topology compatible with **React Force Graph / Three.js / Cytoscape.js / Sigma.js**, complete with visual properties (`group`, `color_category`, `val/size`, `polarity`, `hop_distance`, `event_ts`).

---

## 4. Target Repository Structure
```text
stock-graphrag-engine/
├── AGENTS.md
├── docs/
│   ├── 01_USE_CASE_AND_SOURCES.md
│   ├── 02_SYSTEM_DESIGN.md
│   └── 03_CLASS_DIAGRAM.md
├── docker-compose.yml               # FalkorDB + TimescaleDB (PostgreSQL 16) + Redis
├── pyproject.toml                   # Python 3.12+, FastAPI, falkordb, asyncpg, pydantic, apscheduler
├── .env.example
├── src/
│   ├── config/
│   │   ├── settings.py              # Pydantic BaseSettings
│   │   └── ontology_seed.yaml       # Static Stock -> Sector/Commodity/Currency/Macro mappings
│   ├── domain/
│   │   ├── enums.py                 # Cadence, CommodityID, MacroID, DealType, NewsCategory
│   │   ├── entities.py              # Internal domain objects
│   │   └── schemas.py               # API Request/Response Pydantic models (StockDossierResponse)
│   ├── repositories/
│   │   ├── falkor_repo.py           # FalkorDB connection, index init, OpenCypher & Vector queries
│   │   └── timescale_repo.py        # PostgreSQL/TimescaleDB async queries & aggregations
│   ├── processors/
│   │   ├── entity_resolver.py       # Maps aliases ("Reliance", "RIL") -> "RELIANCE" / ISIN
│   │   ├── anomaly_detector.py      # Z-Score calculation for Delivery % & Valuation
│   │   └── news_graph_extractor.py  # LLM Structured Output: News -> 1-Hop Stock or 2-Hop Macro
│   ├── ingestion/
│   │   ├── base.py                  # Abstract BaseIngestor
│   │   ├── stream_news_ingestor.py  # 30m cron: RSS feeds + NSE/BSE Reg-30 corporate announcements
│   │   ├── daily_eod_ingestor.py    # 7PM IST cron: Bhavcopy, FII/DII, Bulk/Insider, P/E, FX/Crude
│   │   ├── periodic_macro_ingestor.py # Monthly/Bi-M cron: MF holdings, CPI, RBI Repo, Sector sales
│   │   ├── quarterly_ingestor.py    # Quarterly cron: XBRL P&L/BS/CF, Concall PDF RAG, Shareholding
│   │   └── scheduler.py             # APScheduler / CLI entrypoint for cron jobs
│   ├── services/
│   │   └── stock_context_service.py # Core orchestrator merging FalkorDB + TimescaleDB by date range
│   └── api/
│       ├── main.py                  # FastAPI application factory
│       ├── routes_stock.py          # REST endpoints (/api/v1/stocks/{ticker}/dossier)
│       └── mcp_server.py            # FastMCP tool server for AI agent consumption
└── tests/
    ├── test_temporal_bounds.py
    ├── test_falkor_queries.py
    └── test_news_routing.py
```

---

## 5. Step-by-Step Vibe Coding Implementation Order
When asked to build the project, execute in these exact milestones:
- **Milestone 1 (Infra & Schemas):** Create `docker-compose.yml`, `pyproject.toml`, `src/domain/enums.py`, `src/domain/schemas.py`, and database initialization scripts in `falkor_repo.py` and `timescale_repo.py`.
- **Milestone 2 (Static Ontology & Entity Resolver):** Build `ontology_seed.yaml`, `entity_resolver.py`, and seed the baseline Stocks, Sectors, Commodities, Currencies, and Macro factors into FalkorDB.
- **Milestone 3 (The Stock Context Service & API/MCP):** Build `stock_context_service.py`, `routes_stock.py`, and `mcp_server.py` with full support for `[from_date, to_date]` and `None` (all-time) queries, verified with mock seed data.
- **Milestone 4 (News & Daily EOD Ingestion):** Implement `news_graph_extractor.py`, `stream_news_ingestor.py`, `anomaly_detector.py`, and `daily_eod_ingestor.py`.
- **Milestone 5 (Bi-Monthly & Quarterly Ingestion):** Implement `periodic_macro_ingestor.py` and `quarterly_ingestor.py` with bi-temporal node rotation (`[:SUPERSEDES]`).