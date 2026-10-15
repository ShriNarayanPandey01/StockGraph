# 01 — Project Use Case, Problem Statement & Data Source Playbook

## 1. Detailed Problem Statement
Equity research and algorithmic swing trading require synthesizing two fundamentally different types of information:
1. **Explicit Direct Information:** Earnings releases, order book updates, insider buying, bulk deals, and delivery volume spikes directly on a stock (`TATASTEEL`).
2. **Implicit 2nd-Order Contagion:** Global commodity shocks (e.g., Coking Coal or Brent Crude spiking), currency moves (`USD/INR`), regulatory shifts (RBI Repo Rate changes, import duties), or geopolitical events (Red Sea freight disruptions).

### Why Existing Approaches Fail
- **Traditional SQL Databases:** Cannot traverse multi-hop relationships (e.g., *"Which stocks in my universe suffer margin compression when Brent Crude rises >5%?"*) without brittle, hardcoded join tables.
- **Standard Vector RAG:**
  1. Cannot connect an article about *"China infrastructure stimulus lifting HRC Steel prices"* to `TATASTEEL` if the string `"Tata Steel"` is absent from the article.
  2. Suffers from **Temporal Collapse**: retrieves outdated Q1 guidance alongside Q3 guidance because both match the semantic embedding for *"revenue guidance"*.
  3. Fails at **Time-Bounded Queries**: cannot reliably reconstruct what the market knew strictly between `2025-10-15` and `2026-10-15`.

---

## 2. How Our Solution Works (The End-to-End Flow)

### Flow A: Scheduled Background Ingestion (The Cron Pipeline)
1. **Cron Triggers:** Scheduled workers wake up at specific intervals (every 30m for news, 7:00 PM IST daily for EOD exchange files, monthly for MF/Inflation, and quarterly for earnings).
2. **Dual Routing:**
   - **Numeric Time-Series -> PostgreSQL/TimescaleDB:** Daily Delivery %, P/E, P/B, EV/EBITDA, FII/DII flows, and raw financial tables are upserted into SQL.
   - **Anomalies & Qualitative Catalysts -> FalkorDB:**
     - If `QuantAnomalyDetector` spots an abnormal Delivery % spike (e.g., Z-score > 1.8), it writes a `:DailyAnomalyEvent` node to FalkorDB.
     - When `NewsGraphExtractor` processes a news article, it resolves entities via `CanonicalEntityResolver`, generates a vector embedding, and links the `:NewsEvent` either **1-Hop directly** to a `:Stock` or **2-Hop indirectly** to a `:Commodity`, `:Currency`, `:Sector`, or `:MacroFactor`.
     - When Monthly MF or Quarterly Guidance/Results arrive, `FalkorGraphRAGRepository` closes the validity interval (`valid_to_ts`) of the previous period's node and attaches the new node with `is_latest = true`.

### Flow B: Downstream Agent Query (The Context Service)
1. An external agent (e.g., Phase 2 Trading Bot or Research Agent) calls:
   `GET /api/v1/stocks/TATASTEEL/dossier?from_date=2025-10-15&to_date=2026-10-15` (or omits dates for all-time history).
2. `StockContextService` converts the dates into UTC epoch bounds `[start_ts, end_ts]` (`[0, 9999999999]` if unfiltered).
3. It runs two parallel async queries:
   - **FalkorDB Query:** Traverses 1-hop direct news, 2-hop commodity/currency/macro/sector news, institutional deals, daily anomalies, and validity-interval quarterly/guidance nodes active within `[start_ts, end_ts]`.
   - **TimescaleDB Query:** Fetches the valuation percentile, delivery trend, and price/volume summary for `[start_ts, end_ts]`.
4. Returns a single deterministic, time-sorted `StockDossierResponse` JSON.

---

## 3. Complete 12-Item Data Ingestion Playbook (Indian Markets)

| # | Data Point | Cadence & Cron Time (IST) | Primary Source / Format | Storage Target | Graph Mapping in FalkorDB |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **News, Geopolitics & Reg-30 Filings** | Every 30 mins (`*/30 * * * *`) | NSE/BSE Corporate Announcements API, Financial RSS feeds | **FalkorDB** (Vector + Graph) | `(:NewsEvent)` -> `[:DIRECTLY_IMPACTS]` -> `(:Stock)` OR `[:SHOCKS]` -> `(:Commodity/:MacroFactor)` |
| **2** | **Delivery % & Volume** | Daily EOD (`19:00 IST`) | NSE/BSE EOD Bhavcopy CSV (`MTO_*.DAT` / UDiFF CSV) | **TimescaleDB** (All) + **FalkorDB** (Anomalies) | If 20D Z-Score >= 1.8: `(:Stock)-[:TRIGGERED_ANOMALY]->(:DailyAnomalyEvent)` |
| **3** | **FII & DII Provisional Flows** | Daily EOD (`19:30 IST`) | NSE FII/DII Provisional Cash & SEBI/NSDL FPI daily reports | **TimescaleDB** + **FalkorDB** | Updates `(:MarketRegime)` daily flow node & links institutional liquidity state |
| **4** | **Bulk, Block & Insider Deals** | Daily EOD (`20:00 IST`) | NSE/BSE Bulk & Block CSVs + SEBI SAST Reg 7(2) Insider CSV | **TimescaleDB** + **FalkorDB** | `(:InstitutionalActor)-[:EXECUTED_DEAL {deal_type, side, value_cr, event_ts}]->(:Stock)` |
| **5** | **Valuation Ratios (P/E, P/B, EV/EBITDA)** | Daily EOD (`20:15 IST`) | NSE Index/Equity valuation files + Computed from trailing 4Q XBRL EPS/EBITDA | **TimescaleDB** (Series) + **FalkorDB** (Latest) | Updates latest valuation & 5Y percentile on `(:Stock)` node; logs extreme valuation anomalies |
| **6** | **Raw Materials & Currency (Crude, Steel, USD/INR)** | Daily EOD (`21:00 IST`) | Yahoo Finance / FRED / FBIL Reference Rate / MCX EOD | **TimescaleDB** (Series) + **FalkorDB** (Shocks) | Updates `(:Commodity)` & `(:Currency)` nodes; creates `:NewsEvent` shock edge if 1D/5D move > threshold |
| **7** | **Sectoral Business Updates** | Monthly (`1st–5th of Month`) | BSE/NSE Monthly Business Update filings (Auto sales, Cement, Power) | **FalkorDB** (Vector + Graph) | `(:NewsEvent {category: "SECTOR_UPDATE"})-[:IMPACTS_SECTOR]->(:Sector)` |
| **8** | **Mutual Fund Portfolio Disclosures** | Monthly (`12th of Month`) | AMFI / AMC Monthly Portfolio Excel/CSV disclosures | **TimescaleDB** + **FalkorDB** | `(:MutualFundHouse)-[:UPDATED_HOLDING {delta_stake_pct, valid_from_ts, valid_to_ts}]->(:Stock)` |
| **9** | **Macro Data (CPI Inflation, RBI Repo Rate)** | Monthly (12th) & Bi-Monthly (RBI MPC schedule) | MoSPI CPI Release & RBI Monetary Policy Statements | **TimescaleDB** + **FalkorDB** | `(:NewsEvent)-[:ALTERS_MACRO {stance}]->(:MacroFactor)<-[:SENSITIVE_TO_MACRO]-(:Stock)` |
| **10** | **Quarterly Financial Results (P&L)** | Quarterly (`Jan, Apr, Jul, Oct-Nov`) | NSE/BSE XBRL Financial Result XML/JSON filings | **TimescaleDB** + **FalkorDB** | `(:Stock)-[:HAS_QTR_STATE]->(:QuarterlySnapshot {valid_from_ts, valid_to_ts})` |
| **11** | **Management Guidance & Order Book** | Quarterly (Post-Results) | NSE/BSE Investor Presentations & Earnings Call Transcripts (PDF) | **FalkorDB** (Vector RAG) | `(:Stock)-[:ISSUED_GUIDANCE]->(:GuidanceChunk {embedding, order_book_cr, valid_from_ts, valid_to_ts})` |
| **12** | **Shareholding Pattern & Balance Sheet / Cash Flow** | Quarterly (SHP) & Semi-Annual (BS/CF) | NSE/BSE Reg-31 Shareholding XBRL + Semi-Annual/Annual XBRL BS/CF | **TimescaleDB** + **FalkorDB** | Stored in `:QuarterlySnapshot` (`promoter_pledge_pct`, `debt_to_equity`, `fcf_cr`); creates `:GovernanceRisk` edge if pledge spikes |