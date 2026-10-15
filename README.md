# StockGraph — Temporal GraphRAG & Stock Intelligence Platform

> **Branch Focus (`stock_to_stock`):**
> This branch specifically introduces first-class **Stock-to-Stock (`:Stock -> :Stock`) relationship topology**, allowing the knowledge graph to model multi-tier supply chain dependencies, competitor peer groups, equity stake holdings, and conglomerate business group structures. It also introduces dedicated **Graph Visualization APIs** (`/api/v1/graph/...`) formatted for zero-transformation rendering in interactive frontend graph engines (**React Force Graph 2D/3D**, **Three.js**, **Cytoscape.js**, and **Sigma.js**).

---

## 1. What is StockGraph?

**StockGraph** is a **Temporal GraphRAG + Time-Series Stock Intelligence Platform** tailored for Indian Equities (NSE/BSE). It synthesizes continuous quantitative market data with qualitative news, corporate filings, supply-chain contagion, and institutional money footprints into a unified dual-database architecture:

- **FalkorDB (Unified Graph + Vector DB):** High-speed OpenCypher knowledge graph and native `vecf32` vector search storing causal relationships, news impact paths, quarterly guidance chunks, governance risks, and inter-company links.
- **PostgreSQL 16 + TimescaleDB:** Continuous numeric time-series storage for daily OHLCV candles, delivery percentages, valuation ratios (P/E, P/B, EV/EBITDA), FII/DII net cash flows, and macro rates.

Downstream consumers (Phase 2 algorithmic trading engines, AI research copilots via MCP, and web visualizers) query this service to retrieve complete, time-bounded intelligence dossiers or traversable graph networks with zero lookahead bias.

---

## 2. Highlight: Stock-to-Stock Topology (`stock_to_stock` Branch)

In traditional financial tools, stocks exist in isolation. Real markets, however, operate on direct operational, competitive, and conglomerate links. This branch unlocks **inter-company graph traversal**:

```text
       (:Stock {ticker: "NMDC"})                  (:BusinessGroup {id: "TATA_GROUP"})
                   |                                       ^               ^
                   | [:SUPPLIES_TO {item: "Iron Ore"}]     |               | [:BELONGS_TO_GROUP]
                   v                                       |               |
       (:Stock {ticker: "TATASTEEL"}) ---------------------+               |
           |                |     |                                        |
           |                |     +----------------------------------------+
           |                |     | [:SUPPLIES_TO {item: "Auto Grade Steel"}]
           |                |     v
           |                |   (:Stock {ticker: "TATAMOTORS"}) <--[:SUPPLIES_TO]-- (:Stock {ticker: "SONACOMS"})
           |                |
           |                +--> [:OWNS_STAKE_IN {stake_pct: 34.1}] --> (:Stock {ticker: "TRF"})
           |
           +--> [:COMPETES_WITH {segment: "Flat Steel"}] <--> (:Stock {ticker: "JSWSTEEL"})
```

### Supported Inter-Company Edge Types
1. **Supply Chain (`:Stock -[:SUPPLIES_TO]-> :Stock`)**:
   - Captures component dependency, critical raw materials, and revenue dependency levels (`HIGH`, `MEDIUM`, `LOW`).
   - *Example:* `NMDC` supplies Iron Ore to `TATASTEEL`, which supplies flat steel to `TATAMOTORS`.
2. **Peer Competition (`:Stock -[:COMPETES_WITH]-> :Stock`)**:
   - Segment-level rivalries (e.g., `TATASTEEL` competes with `JSWSTEEL` in Flat Steel).
3. **Cross-Holdings & Subsidiaries (`:Stock -[:OWNS_STAKE_IN]-> :Stock`)**:
   - Direct parent-subsidiary, joint venture, and associate stakes with ownership percentages.
4. **Conglomerate Membership (`:Stock -[:BELONGS_TO_GROUP]-> :BusinessGroup`)**:
   - Maps conglomerate ties (e.g., `TATA_GROUP`, `ADANI_GROUP`, `RELIANCE_GROUP`, `ADITYA_BIRLA_GROUP`) to track cross-entity reputational and governance contagion.

---

## 3. Dual Output Modes

The platform serves two primary output formats:

### Mode A: Downstream Agent Dossier (`/api/v1/stocks/{ticker}/dossier`)
- Structured hierarchical JSON built for LLM reasoning, research copilots, and strategy backtesters.
- Merges 1-hop direct news, 2-hop commodity/macro shocks, institutional transactions, quarterly snapshots, and quantitative valuation percentiles.
- Supports arbitrary time-slice filtering (`from_date` to `to_date`) or all-time history (`from_date=None, to_date=None`).

### Mode B: Interactive Graph UI Topology (`/api/v1/graph/...`)
- Returns a flat `{ "nodes": [...], "links": [...] }` schema (`GraphTopologyResponse`) with visual attributes (`visual_size`, `polarity`, `hop_distance`, `event_ts`, `node_type`).
- Ready for zero-overhead rendering in **React Force Graph (2D/3D)**, **Three.js**, **Cytoscape.js**, or **Sigma.js**.

#### Key Visualization Endpoints:
- `GET /api/v1/graph/ego/{ticker}?depth=2&include_peers=true`: Dynamic ego-network centered around a stock.
- `GET /api/v1/graph/path?source_ticker=ONGC&target_ticker=ASIANPAINT`: Shortest path causal discovery between any two companies.
- `GET /api/v1/graph/sector-cluster/{sector_id}`: Inter-connected sector cluster graph.

---

## 4. Multi-Cadence Ingestion Schedule

| Frequency | Interval / Schedule | Focus | Target DB |
| :--- | :--- | :--- | :--- |
| **Continuous** | Every 30 mins (`*/30 * * * *`) | RSS news, geopolitical catalysts, NSE/BSE Reg-30 filings | FalkorDB (Vector + Graph) |
| **Daily EOD** | 7:00 PM – 9:00 PM IST | Bhavcopy delivery %, bulk/block/insider trades, P/E ratios, FX & crude | TimescaleDB + FalkorDB (Anomalies) |
| **Monthly / Bi-Monthly** | 1st–12th of month & RBI MPC | AMFI Mutual Fund holdings, CPI inflation, RBI repo rate, auto sales | TimescaleDB + FalkorDB |
| **Quarterly / Annual** | Earnings Season | XBRL financials (P&L, BS, CF), concall guidance RAG, shareholding | FalkorDB (Bi-temporal) + TimescaleDB |

---

## 5. Architectural Invariants (Guardrails)

1. **Mandatory FalkorDB for Graph & Vector:** All graph traversals and vector searches are handled exclusively by FalkorDB (`falkordb` SDK).
2. **Strict Dual-Store Separation:** Numeric time-series live in TimescaleDB; only structural nodes, causal edges, statistical anomalies (Z-Score $\ge 1.8$), and vector chunks live in FalkorDB.
3. **Bi-Temporal Validity (`valid_from_ts`, `valid_to_ts`, `[:SUPERSEDES]`):** Prevents lookahead bias and stale fact poisoning across historical earnings guidance and fund holdings.
4. **Canonical Entity Resolution:** All entity strings pass through `CanonicalEntityResolver` to ensure zero duplicate nodes (mapping to official NSE tickers, ISINs, or locked commodity/macro IDs).

---

## 6. Project Documentation Index

For in-depth specifications, refer to the documentation in `/docs`:
- **[01_USE_CASE_AND_SOURCES.md](docs/01_USE_CASE_AND_SOURCES.md)** — Detailed business use cases, Indian market data sources, and scraping playbook.
- **[02_SYSTEM_DESIGN.md](docs/02_SYSTEM_DESIGN.md)** — Dual-database architecture, OpenCypher queries, TimescaleDB DDL, and Graph UI schemas.
- **[03_CLASS_DIAGRAM.md](docs/03_CLASS_DIAGRAM.md)** — Mermaid class diagrams, Pydantic DTOs, and abstract service contracts.
- **[AGENTS.md](AGENTS.md)** — Master instructions and blueprint for AI coding agents.