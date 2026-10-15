# AGENTS.md — Temporal GraphRAG Stock Intelligence Service (Phase 1)

## 1. Project Overview & Core Mission
This project is a **Temporal GraphRAG + Time-Series Stock Intelligence Platform** built for the Indian Equity Market (NSE/BSE). 
When implementing features or debugging, consult the modular documentation files located in `/docs`:
- **System Design:** [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md)
- **Class Diagram:** [`docs/CLASS_DIAGRAM.md`](docs/CLASS_DIAGRAM.md)

In **Phase 1 (Current Scope)**, the system operates as an automated **Multi-Cadence Financial Data Ingestion Pipeline** and a **Context Retrieval Microservice (REST API + MCP Server)**. It continuously scrapes, normalizes, and links structured market data, institutional money flows, quarterly fundamentals, and unstructured news/geopolitical events into a dual-database architecture (**PostgreSQL/TimescaleDB** + **FalkorDB Unified Graph & Vector DB**).

Other downstream AI agents, trading bots (Phase 2), backtesting engines, and research dashboards query this service to retrieve a complete, time-bounded **360-Degree Stock Dossier** (`from_date` to `to_date`, or `all-time` if unfiltered).

---

## 2. What Problem Does This Solve?
Standard LLM RAG systems and traditional stock screeners fail at equity research for four structural reasons:

1. **Blindness to 2nd-Order Causal Contagion:**
   - *Problem:* If Brent Crude spikes 8% due to West Asia tensions or China announces steel stimulus, a news article will **never mention** `ASIANPAINT` or `TATASTEEL` by name. Standard keyword or vector search misses the connection completely.
   - *Our Solution:* **FalkorDB 2-Hop Causal Graph Traversal** links `(:NewsEvent)-[:SHOCKS]->(:Commodity | :Currency | :Sector | :MacroFactor)<-[:EXPOSED_TO]-(:Stock)`. Querying a stock automatically retrieves indirect macro, commodity, and geopolitical news affecting its margins or demand.
2. **Stale Fact Poisoning in Vector RAG:**
   - *Problem:* Standard Vector DBs retrieve Q1 guidance (*"Margins will be 18%"*) alongside Q2 guidance (*"Margins cut to 14%"*) because both have identical semantic embeddings, causing LLMs to hallucinate.
   - *Our Solution:* **Bi-Temporal Validity Intervals (`valid_from_ts`, `valid_to_ts`)** and `[:SUPERSEDES]` edges ensure the agent only retrieves the state that was active during the requested date window.
3. **LLM Inability to Process Raw Numeric Time-Series:**
   - *Problem:* Stuffing 365 days of daily Delivery %, P/E ratios, or OHLCV candles into a Graph DB or LLM prompt bloats memory and fails mathematically.
   - *Our Solution:* **Dual-Store Separation** keeps raw numeric time-series in **PostgreSQL/TimescaleDB**, runs deterministic Z-score anomaly detection at End-of-Day (EOD), and only pushes statistically significant **Anomaly/Signal Events** into **FalkorDB**.
4. **Lookahead Bias in Backtesting & Historical Analysis:**
   - *Problem:* Most AI stock tools only know "today's" state and cannot answer *"What did we know about TATASTEEL between Jan 1, 2026 and March 31, 2026?"*
   - *Our Solution:* Every node and edge carries strict Unix epoch timestamps (`event_ts` or `valid_from_ts`/`valid_to_ts`), allowing exact time-slice queries (`[from_date, to_date]`) or full historical retrieval (`from_date=None, to_date=None`).

---

## 3. Multi-Cadence Data Ingestion Scope
Scheduled cron workers automatically collect and normalize data across four frequencies:

### A. Continuous / Intraday (Every 15–30 Minutes)
- **News & Geopolitical Feeds:** Financial RSS feeds, global commodity/macro news, sector updates.
- **Corporate Filings:** NSE/BSE Regulation 30 announcements (Order wins, capacity expansions, litigation, board changes).

### B. Daily End-of-Day (6:30 PM – 8:30 PM IST)
- **Delivery Percentage & Volume:** NSE/BSE Bhavcopy EOD delivery % and 20-day Z-score anomalies.
- **FII & DII Provisional Flows:** Daily net institutional cash and derivatives flow.
- **Bulk, Block & Insider Deals:** NSE/BSE bulk/block trade ledgers and SEBI SAST / Insider trading disclosures.
- **Valuation Ratios:** Daily P/E, P/B, EV/EBITDA, and 5-year historical valuation percentile.
- **Raw Material & Currency EOD Prices:** Brent Crude, HRC Steel, Coking Coal, Copper, Aluminium, USD/INR, DXY.

### C. Monthly & Bi-Monthly (1st–15th of Month / RBI Calendar)
- **Sectoral Business Updates:** Monthly auto sales, cement dispatches, power demand, telecom subscriber data.
- **Mutual Fund Portfolio Disclosures:** Monthly AMC scheme-wise stock holding additions/reductions (published by the 10th of each month).
- **Macro Data:** Monthly CPI/WPI Inflation data and Bi-Monthly RBI MPC Interest Rate (Repo Rate) decisions.

### D. Quarterly & Annual (Earnings Season)
- **Quarterly Financial Results:** Revenue, EBITDA, PAT, margins (parsed from NSE/BSE XBRL filings).
- **Management Guidance & Order Book:** Concall transcripts, investor presentations, order book size, and book-to-bill ratio (Vector-indexed in FalkorDB).
- **Shareholding Pattern & Promoter Pledging:** Promoter, FII, DII, Retail %, and Promoter Pledge % delta.
- **Balance Sheet & Cash Flow Statement:** Semi-annual/Annual Debt-to-Equity, Working Capital cycle, Operating & Free Cash Flow (OCF/FCF).

---

## 4. How Downstream Agents & Users Consume This Service
1. **Trading Bots (Phase 2):** Call `GET /api/v1/stocks/{ticker}/dossier?from_date=2026-10-01&to_date=2026-10-15` pre-market to get a clean JSON bundle of 14-day catalysts, delivery spikes, insider buying, and active quarterly guidance to decide `BUY`, `SELL`, or `HOLD`.
2. **AI Research Copilots (via MCP Tool Call):** Invoke `get_stock_intelligence(ticker, from_date, to_date, semantic_query)` to answer complex user prompts like *"How did steel price movements and management guidance evolve for TATASTEEL over the past 1 year?"*
3. **Strategy Backtesters:** Replay historical windows (`from_date=2025-01-01`, `to_date=2025-03-31`) with zero lookahead bias to test how an agent would have traded using only information known at that timestamp.

---

## 5. Strict Coding Rules for AI Agents (Vibe Coding Guardrails)
- **Database Rule #1:** You MUST use **FalkorDB** (`falkordb-py`) as the unified Knowledge Graph + Vector Database. Do NOT introduce Neo4j, Qdrant, Pinecone, or Milvus.
- **Database Rule #2:** Store raw daily numeric time-series (daily OHLCV, daily P/E, raw delivery % series) in **PostgreSQL / TimescaleDB**. Only write structured entities, relationships, anomalies, and vector-embedded text chunks to **FalkorDB**.
- **Temporal Rule:** Every node/edge inserted into FalkorDB MUST include either `event_ts: int` (for Point-in-Time events like News and Bulk Deals) or `valid_from_ts: int` and `valid_to_ts: int` (for Validity-Interval states like Quarterly Results, Guidance, and MF Holdings; use `9999999999` for currently active states).
- **Entity Resolution Rule:** Never allow free-text LLM node creation for companies or commodities. Always resolve entities against `CanonicalEntityResolver` (`ISIN` / `NSE Ticker` for stocks; locked enum IDs like `BRENT_CRUDE`, `HRC_STEEL`, `USD_INR`, `RBI_REPO_RATE` for macro/commodities).