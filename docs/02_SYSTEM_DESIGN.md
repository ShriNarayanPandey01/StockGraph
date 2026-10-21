# 02 — System Design, Database Schemas & Query Specifications

## 1. End-to-End Architecture Diagram

```text
+-----------------------------------------------------------------------------------+
|                        1. CRON SCHEDULER & INGESTION LAYER                        |
|  [APScheduler / CLI Workers — separate `stockgraph-scheduler` process, durable jobstore] |
|   ├── StreamNewsIngestor    (Every 30m, news-only): RSS Feeds + NSE/BSE Reg-30     |
|   ├── VendorChartSync       (Daily EOD) : OHLCV/Delivery/Valuations/FII-DII/FX via |
|   |                            generic ChartProviderAdapter → vendor_quotes_raw      |
|   ├── PeriodicMacroIngestor (Monthly/BM): AMFI MF Holdings, CPI, RBI Repo, Sector |
|   └── QuarterlyIngestor     (Quarterly) : XBRL P&L/BS/CF, Concall PDFs, SHP/Pledge|
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                      2. PROCESSING & GRAPH EXTRACTION LAYER                       |
|   ├── CanonicalEntityResolver : Maps raw strings -> NSE Ticker / ISIN / registry  |
|   ├── NewsDeduper             : URL canonicalize + deterministic id + DUPLICATE_OF|
|   ├── ChartVendorAdapter      : Generic vendor fetch → stage raw → normalize      |
|   ├── QuantAnomalyDetector    : SQL-only 20D Delivery Z-Score & 5Y PE Percentile  |
|   └── NewsGraphExtractor (LLM): Extracts 1-Hop Stock vs 2-Hop Macro/Commodity Edge|
+--------------------+-----------------------------------------+--------------------+
                     |                                         |
                     v (Normalized Vendor Series)            v (Causal Graph + Vector RAG)
+----------------------------------------+ +----------------------------------------+
|     3A. PERSISTENT RELATIONAL DB       | |     3B. UNIFIED GRAPH + VECTOR DB      |
|     [PostgreSQL 16 + TimescaleDB]      | |              [FalkorDB]                |
|  • vendor_quotes_raw (jsonb staging)   | |  • Static: Stock, Sector, Commodity,   |
|  • daily_stock_metrics (+vendor_id)    | |    MacroFactor (no :Currency)          |
|  • daily_macro_and_flows               | |  • Point-in-Time: NewsEvent (vecf32),  |
|  • institutional_deals_raw             | |    EXECUTED_DEAL (+DUPLICATE_OF edge)  |
|  • monthly_mf_holdings_raw             | |  • Validity-Interval: QuarterlySnapshot|
|  • quarterly_financials                | |    GuidanceChunk (vecf32), MF Holding  |
|  • ingest_runs (ops log)               | |  • Anomalies: SQL-only, never in graph |
+--------------------+-------------------+ +-------------------+--------------------+
                     |                                         |
                     +--------------------+--------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                 4. STOCK CONTEXT SERVICE (FastAPI + FastMCP Server)               |
|   • Resolves window=LAST_6M|LAST_1Y (IST-aware) -> [start_ts, end_ts]             |
|   • Merges 1-Hop + 2-Hop FalkorDB Subgraph + Vector Chunks + SQL Quant Summary    |
|   • Every quant value cites vendor_id + vendor_as_of                              |
|   • Returns StockDossierResponse JSON to Upstream AI Agents / Phase 2 Bot         |
+-----------------------------------------------------------------------------------+
```

---

## 2. FalkorDB Graph Topology & How Everything Connects

```text
                    +------------------------------------------+
                    |              :NewsEvent                  |
                    |  id (sha1), headline, summary, category  |
                    |  sentiment (-1 to +1), event_ts: int     |
                    |  embedding: vecf32(1536)                 |
                    |  self-edge: [:DUPLICATE_OF] -> canonical |
                    +----+----------------+---------------+----+
                         |                |               |
   [:DIRECTLY_IMPACTS]   |                | [:SHOCKS]     | [:IMPACTS_SECTOR /
   (1-Hop Stock News)    |                v               v  :ALTERS_MACRO]
                         |        +---------------+  +---------------+
                         |        |  :Commodity   |  |    :Sector    |
                         |        |  (RELATED_TO  |  |  :MacroFactor |
                         |        |  inter-links)|  |  (explainers) |
                         |        |               |  |               |
                         |        |               |  |               |
                         |        +-------+-------+  +-------+-------+
                         |                ^                  ^
                          |                | [:EXPOSED_TO]    | [:BELONGS_TO /
                          v                | (Seed + LLM)     |  :SENSITIVE_TO_MACRO]
+----------------------+  +-----------------+------------------+  +--------------------+
| Anomalies: SQL-only  |<-+               :Stock               +->| :QuarterlySnapshot |
| delivery_20d_zscore  |  | ticker: "TATASTEEL"                |  | • quarter: "Q2FY27"|
| pe_5yr_percentile    |  | isin: "INE081A01020"               |  | • rev_yoy_pct      |
| (no graph nodes)     |  | vendor_id + vendor_as_of on reads  |  | • ebitda_margin    |
+----------------------+  +-----------------+------------------+  | • pledge_pct       |
                                          ^                     | • debt_to_equity   |
            +-----------------------------+---------------+     | • fcf_cr           |
            |                             |               |     | • valid_from_ts    |
            | [:EXECUTED_DEAL]            | [:UPDATED_    |     | • valid_to_ts      |
            | (Point-in-Time: event_ts)   |   HOLDING]    |     +---------+----------+
            v                             v               v               | [:SUPERSEDES]
+-----------------------+   +-----------------------+   +-----------------+-------+
| :InstitutionalActor   |   | :MutualFundHouse      |   | :GuidanceChunk (Vector) |
| • name                |   | • amc_id, name        |   | • concall_summary       |
| • category (FII/PROM) |   | • Edge: valid_from_ts |   | • order_book_cr         |
| • Edge: BULK/INSIDER  |   |   valid_to_ts, delta  |   | • valid_from_ts/to_ts   |
+-----------------------+   +-----------------------+   +-------------------------+
```

---

## 3. FalkorDB Initialization & OpenCypher Query Templates

### 3.1 Index Creation Cypher Script
Run on service startup in `FalkorGraphRAGRepository.ensure_indexes_and_constraints()`:
```cypher
CREATE INDEX FOR (s:Stock) ON (s.ticker);
CREATE INDEX FOR (c:Commodity) ON (c.id);
CREATE INDEX FOR (m:MacroFactor) ON (m.id);
CREATE INDEX FOR (sec:Sector) ON (sec.id);

// Temporal Range Indexes
CREATE INDEX FOR (n:NewsEvent) ON (n.event_ts);
CREATE INDEX FOR (n:NewsEvent) ON (n.id);
CREATE INDEX FOR (q:QuarterlySnapshot) ON (q.valid_from_ts);
CREATE INDEX FOR (q:QuarterlySnapshot) ON (q.valid_to_ts);
CREATE INDEX FOR (g:GuidanceChunk) ON (g.valid_from_ts);
CREATE INDEX FOR (g:GuidanceChunk) ON (g.valid_to_ts);

// Vector Indexes for Semantic RAG
CREATE VECTOR INDEX FOR (n:NewsEvent) ON (n.embedding) OPTIONS {dimension: 1536, similarityFunction: 'cosine'};
CREATE VECTOR INDEX FOR (g:GuidanceChunk) ON (g.embedding) OPTIONS {dimension: 1536, similarityFunction: 'cosine'};
CREATE VECTOR INDEX FOR (s:Stock) ON (s.profile_embedding) OPTIONS {dimension: 1536, similarityFunction: 'cosine'};
```

### 3.2 Master Temporal Subgraph Retrieval Query
Used by `StockContextService.get_stock_dossier()` for `window=LAST_6M | LAST_1Y` (IST-aware `[start_ts, end_ts]`). Every section is bounded with `LIMIT`; duplicates are excluded (`DUPLICATE_OF` targets never carry impact edges):
```cypher
MATCH (s:Stock {ticker: $ticker})

// 1. Direct 1-Hop News (canonical only) — LIMIT 50
OPTIONAL MATCH (n1:NewsEvent)-[r1:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s)
WHERE n1.event_ts >= $start_ts AND n1.event_ts <= $end_ts
  AND NOT (n1)-[:DUPLICATE_OF]->()

// 2. Indirect 2-Hop Contagion News — LIMIT 50
OPTIONAL MATCH (s)-[exp:EXPOSED_TO|BELONGS_TO|SENSITIVE_TO_MACRO|SUPPLIES_TO|COMPETES_WITH]->(bridge)<-[r2:SHOCKS|IMPACTS_SECTOR|ALTERS_MACRO]-(n2:NewsEvent)
WHERE n2.event_ts >= $start_ts AND n2.event_ts <= $end_ts
  AND NOT (n2)-[:DUPLICATE_OF]->()

// 3. Bulk, Block & Insider Deals — LIMIT 50
OPTIONAL MATCH (inst:InstitutionalActor)-[deal:EXECUTED_DEAL]->(s)
WHERE deal.event_ts >= $start_ts AND deal.event_ts <= $end_ts

// 4. Monthly Mutual Fund Holdings Overlapping [start_ts, end_ts]
OPTIONAL MATCH (mf:MutualFundHouse)-[mh:UPDATED_HOLDING]->(s)
WHERE mh.valid_from_ts <= $end_ts AND mh.valid_to_ts >= $start_ts

// 5. Quarterly Snapshots & Guidance Overlapping [start_ts, end_ts]
OPTIONAL MATCH (s)-[:HAS_QTR_STATE]->(qtr:QuarterlySnapshot)
WHERE qtr.valid_from_ts <= $end_ts AND qtr.valid_to_ts >= $start_ts

OPTIONAL MATCH (s)-[:ISSUED_GUIDANCE]->(gd:GuidanceChunk)
WHERE gd.valid_from_ts <= $end_ts AND gd.valid_to_ts >= $start_ts

RETURN s,
       collect(DISTINCT {id: n1.id, date: n1.event_date, ts: n1.event_ts, headline: n1.headline, summary: n1.summary, category: n1.category, sentiment: r1.sentiment, impact_type: type(r1), confidence: r1.confidence, rationale: r1.rationale}) AS direct_news,
       collect(DISTINCT {id: n2.id, date: n2.event_date, ts: n2.event_ts, via_node: bridge.id, exposure_type: type(exp), margin_impact: exp.margin_impact, headline: n2.headline, sentiment: r2.sentiment, exposure_nature: exp.exposure_nature, exposure_confidence: exp.confidence, exposure_rationale: exp.rationale}) AS indirect_news,
       collect(DISTINCT {actor: inst.name, actor_cat: inst.category, deal_type: deal.deal_type, side: deal.side, qty: deal.qty, value_cr: deal.value_cr, date: deal.event_date, ts: deal.event_ts}) AS institutional_deals,
       collect(DISTINCT {amc: mf.name, month: mh.month, delta_stake_pct: mh.delta_stake_pct, from_ts: mh.valid_from_ts}) AS mf_shifts,
       collect(DISTINCT properties(qtr)) AS quarterly_snapshots,
       collect(DISTINCT {id: gd.id, quarter: gd.quarter, concall_summary: gd.concall_summary, order_book_cr: gd.order_book_cr, from_ts: gd.valid_from_ts}) AS guidance_chunks
```

> Anomalies are SQL-only (`daily_stock_metrics.delivery_20d_zscore`, queried with `WHERE abs(...) >= 1.8`) and intentionally absent here.
>
> Every section `LIMIT` is rendered as a clamped literal integer (1–200) by `_render_section_query`: FalkorDB's parser rejects parameters in the `LIMIT`/`SKIP` grammar slots (`LIMIT $param` is a parse error). `exposure_type` uses the relationship-type function `type(exp)` — an edge's type is graph structure, not a property.

### 3.3 L2 — Near-Duplicate Check Before Chunking (No Embedding Spent)
Normalize the headline (lowercase, strip punctuation and trailing source suffixes like `" - Moneycontrol"`), then compare against the same ticker's canonical items within `dedup_window_hours`. A text match links `[:DUPLICATE_OF]` and skips chunking/embedding entirely:
```cypher
MATCH (canon:NewsEvent {ticker: $ticker})
WHERE canon.event_ts >= $now_ts - $window_secs
  AND canon.norm_headline = $norm_headline
  AND NOT (canon)-[:DUPLICATE_OF]->()
RETURN canon
```

### 3.4 L3 — Semantic Deduplication During Vector Storage
After embedding, query the vector index for the same ticker within the dedup window; cosine > `dedup_cosine_threshold` links `[:DUPLICATE_OF]` instead of creating impact edges:
```cypher
CALL db.idx.vector.queryNodes('NewsEvent', 'embedding', 5, vecf32($embedding))
YIELD node, score
WHERE node.ticker = $ticker
  AND node.event_ts >= $now_ts - 172800
  AND score > 0.92
RETURN node AS canonical_candidate
```

### 3.5 Bi-Temporal Validity Rotation (`rotate_validity_interval_node`)
When a new quarter's results or guidance arrives at `valid_from_ts = $new_ts`, run the statements under the job's Redis lock (no `FOREACH` — support is uncertain on FalkorDB):
```cypher
// Statement 1: close the old latest node (no-op if none exists)
MATCH (s:Stock {ticker: $ticker})-[:HAS_QTR_STATE]->(old:QuarterlySnapshot {is_latest: true})
SET old.is_latest = false,
    old.valid_to_ts = $new_ts - 1
RETURN old.id AS old_id;

// Statement 2: create the new node + stock edge
MATCH (s:Stock {ticker: $ticker})
CREATE (new_q:QuarterlySnapshot $new_props)
SET new_q.valid_from_ts = $new_ts,
    new_q.valid_to_ts = 9999999999,
    new_q.is_latest = true
CREATE (s)-[:HAS_QTR_STATE]->(new_q)
RETURN new_q.id AS new_id;

// Statement 3 (only if statement 1 matched): link the chain
MATCH (new_q:QuarterlySnapshot {id: $new_id}),
      (old:QuarterlySnapshot {id: $old_id})
CREATE (new_q)-[:SUPERSEDES]->(old)
RETURN new_q.id AS new_id;
```

> All three statements project scalar business ids (`old.id`/`new_q.id`): the `falkordb` SDK deserializes whole-node `RETURN`s into `Node` objects (internal graph id, no dict access), while `[:SUPERSEDES]` matches on the business `id` property.

---

## 4. PostgreSQL / TimescaleDB DDL Schema

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Immutable vendor staging: every numeric value enters here first.
-- Vintage key includes fetched_at: a revised payload is staged as a NEW row
-- (never overwritten); reads take the latest vintage per key via
-- LATEST_VINTAGE_QUERY (DISTINCT ON ... ORDER BY fetched_at DESC).
CREATE TABLE vendor_quotes_raw (
    vendor_id VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    series VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor_id, ticker, trade_date, series, fetched_at)
);

CREATE TABLE daily_stock_metrics (
    trade_date DATE NOT NULL,
    session_type VARCHAR(10) NOT NULL DEFAULT 'CLOSE', -- 'OPEN' or 'CLOSE'
    ticker VARCHAR(20) NOT NULL,
    open_price NUMERIC(12, 2),
    high_price NUMERIC(12, 2),
    low_price NUMERIC(12, 2),
    close_price NUMERIC(12, 2) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    delivery_qty BIGINT,
    delivery_pct NUMERIC(5, 2),
    delivery_20d_avg NUMERIC(5, 2),
    delivery_20d_zscore NUMERIC(6, 2),  -- anomaly = WHERE abs(delivery_20d_zscore) >= 1.8 (SQL-only)
    pe_ratio NUMERIC(8, 2),
    pb_ratio NUMERIC(8, 2),
    ev_ebitda NUMERIC(8, 2),
    pe_5yr_percentile NUMERIC(5, 2),
    vendor_id VARCHAR(50) NOT NULL,
    vendor_as_of TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (trade_date, session_type, ticker)
);

SELECT create_hypertable('daily_stock_metrics', 'trade_date', if_not_exists => TRUE);

CREATE TABLE daily_macro_and_flows (
    trade_date DATE NOT NULL PRIMARY KEY,
    brent_crude_usd NUMERIC(10, 2),
    hrc_steel_inr NUMERIC(12, 2),
    coking_coal_usd NUMERIC(10, 2),
    usd_inr NUMERIC(8, 4),
    fii_net_cash_cr NUMERIC(12, 2),
    dii_net_cash_cr NUMERIC(12, 2),
    vendor_id VARCHAR(50) NOT NULL,
    vendor_as_of TIMESTAMPTZ NOT NULL
);

CREATE TABLE quarterly_financials (
    ticker VARCHAR(20) NOT NULL,
    quarter_label VARCHAR(10) NOT NULL,
    published_date DATE NOT NULL,
    valid_from_ts BIGINT NOT NULL,
    revenue_cr NUMERIC(14, 2),
    rev_yoy_pct NUMERIC(6, 2),
    ebitda_cr NUMERIC(14, 2),
    ebitda_margin_pct NUMERIC(6, 2),
    pat_cr NUMERIC(14, 2),
    pat_yoy_pct NUMERIC(6, 2),
    debt_to_equity NUMERIC(6, 2),
    operating_cash_flow_cr NUMERIC(14, 2),
    free_cash_flow_cr NUMERIC(14, 2),
    order_book_cr NUMERIC(14, 2),
    promoter_holding_pct NUMERIC(5, 2),
    promoter_pledge_pct NUMERIC(5, 2),
    fii_holding_pct NUMERIC(5, 2),
    dii_holding_pct NUMERIC(5, 2),
    -- Restatements/re-audits land as new vintages (never overwrite).
    PRIMARY KEY (ticker, quarter_label, valid_from_ts)
);

CREATE TABLE institutional_deals_raw (
    trade_date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    actor_name TEXT NOT NULL,
    actor_category VARCHAR(20) NOT NULL,
    deal_type VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    qty BIGINT,
    value_cr NUMERIC(14, 2),
    PRIMARY KEY (trade_date, ticker, actor_name, deal_type, side)
);
SELECT create_hypertable('institutional_deals_raw', 'trade_date', if_not_exists => TRUE);

CREATE TABLE monthly_mf_holdings_raw (
    month DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    amc_id VARCHAR(50) NOT NULL,
    amc_name TEXT NOT NULL,
    shares_held BIGINT,
    stake_pct NUMERIC(6, 3),
    delta_stake_pct NUMERIC(6, 3),
    valid_from_ts BIGINT NOT NULL,
    valid_to_ts BIGINT NOT NULL DEFAULT 9999999999,
    -- In-month corrections land as new vintages (never overwrite).
    PRIMARY KEY (month, ticker, amc_id, valid_from_ts)
);

-- Ops log for the hardened scheduler (Rule 6): every job run records here.
CREATE TABLE ingest_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error TEXT
);

-- Backfill watermark (Rule 7): last data pushed per vendor series.
-- Each sync inserts only rows with trade_date > last_trade_date, then advances it.
CREATE TABLE vendor_sync_state (
    vendor_id VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    series VARCHAR(50) NOT NULL,
    last_trade_date DATE NOT NULL,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor_id, ticker, series)
);
```

## 5. Vendor Adapter Contract & Scheduler Hardening

- `ChartProviderAdapter.get_eod_series(ticker, start, end)` / `get_macro_series(keys, start, end)` are the only vendor touchpoints. Retries with backoff, rate-limit respect, server-side keys. Normalization appends new vintages, never overwrites provisional rows.
- Backfill watermark: read `vendor_sync_state` for `(vendor_id, ticker, series)`, fetch from the vendor, insert staged rows with `trade_date > last_trade_date` only, then `UPDATE vendor_sync_state SET last_trade_date, last_fetched_at`. The watermark only moves forward, so later revisions of already-synced dates are caught by the `check_revisions` revision sweep: re-fetch the trailing `vendor_revision_lookback_days` window (settings), compare payload hashes, and stage any changed payload as a NEW `vendor_quotes_raw` vintage. Revisions/gaps are logged to `ingest_runs` for replay.
- Vintage resolution rule (SQL ↔ graph consistent): downstream normalization reads one row per `(vendor_id, ticker, trade_date, series)` with **latest vintage wins** — `LATEST_VINTAGE_QUERY` (`SELECT DISTINCT ON (...) ... ORDER BY fetched_at DESC`). `quarterly_financials` restatements (PK `ticker, quarter_label, valid_from_ts`) and monthly MF corrections (PK `month, ticker, amc_id, valid_from_ts`) mirror the graph's `valid_from_ts` / `[:SUPERSEDES]` rotation; a vintage is never overwritten.
- APScheduler: separate `stockgraph-scheduler` process, durable `SQLAlchemyJobStore` (Postgres) or `RedisJobStore`, `coalesce=True`, `max_instances=1`, `misfire_grace_time=300`, Redis `SET NX EX` lock per job, all runs logged to `ingest_runs`.
- Tunables (settings, never hardcoded): `dedup_cosine_threshold=0.92`, `dedup_window_hours=48`, `correlation_min_cosine=0.68`, `correlation_window_days=14`, `ontology_min_confidence=0.65`, `app_timezone=Asia/Kolkata`.
- Retention: graph keeps 1Y + 30d grace (both windows bounded/cacheable); SQL keeps full history with compression.