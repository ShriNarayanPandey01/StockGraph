# StockGraph Landing Page — Comprehensive Wireframe Specification

> **Design Archetype:** Precision Financial Intelligence & Technical Minimalist Architecture  
> **Inspirations:** [The Kunumi Institute](https://www.kunuminst.org/en) (Interactive Constellation Graph & Node Card Transformation), [Jamie McKaye](https://jamiemckaye.com) (Text-Driven, High-Density Technical Aesthetic, Command Palette, No-Fluff Transparency), and Dual-Store Temporal GraphRAG Architecture (`FalkorDB` + `TimescaleDB`).

---

## 1. Executive Design Vision

StockGraph is not a generic stock screener or a consumer retail app; it is a **mission-critical intelligence engine** for quantitative analysts, equity researchers, and algorithmic trading agents.

### Core User Mental Model
1. **The Problem:** Markets are not isolated ticker rows. A spike in Australian Coking Coal impacts Tata Steel's Q3 operating margin, while Red Sea freight rate surges trigger indirect inventory revaluations across Indian auto component makers.
2. **The Solution:** StockGraph connects these invisible multi-hop dots via **Temporal GraphRAG** (FalkorDB) while keeping time-series pricing and official Bhavcopy delivery data mathematically pristine in **TimescaleDB**.
3. **The Landing Page Mission:** Immediately prove this multi-hop causal power through an **interactive, tactile constellation graph** (Section 3), surrounded by **Jamie McKaye-style architectural transparency** (no corporate marketing fluff, raw API curl snippets, live system health, and transparent data models).

---

## 2. Visual Identity & Design Tokens

| Token | Dark Mode Value | Light Mode Value | Purpose |
| :--- | :--- | :--- | :--- |
| **Canvas Background** | `#0B0F17` (Deep Obsidian Void) | `#F8FAFC` (Clean Technical Paper) | Base page background |
| **Surface / Card** | `rgba(18, 24, 38, 0.75)` (Glassmorphism) | `rgba(255, 255, 255, 0.85)` | Elevated containers, cards, floating pills |
| **Hairline Border** | `rgba(255, 255, 255, 0.08)` | `rgba(15, 23, 42, 0.08)` | Precise, razor-thin borders |
| **Primary Accent** | `#38BDF8` (Electric Sky Blue) | `#0284C7` (Cobalt Blue) | Primary nodes, stock nodes, graph edges |
| **Commodity Shock** | `#F97316` (Amber Flare) | `#EA580C` | Commodity nodes, raw material shocks |
| **Macro Vector** | `#A855F7` (Deep Violet) | `#9333EA` | RBI Repo, USD/INR, US Fed rates |
| **Positive Margin** | `#10B981` (Emerald Green) | `#059669` | Positive margin impact, bullish sentiment |
| **Negative Margin** | `#EF4444` (Crimson Rose) | `#DC2626` | Negative margin impact, risk alerts |
| **Monospace Font** | `JetBrains Mono, SF Mono, Menlo, monospace` | Same | Metrics, timestamps, tickers, API endpoints |
| **Display Font** | `Inter, -apple-system, BlinkMacSystemFont, sans-serif` | Same | High-clarity technical typography |

---

## 3. Structural Page Wireframe Blueprint

```
+---------------------------------------------------------------------------------------------------+
|  [Logo] StockGraph    [STATUS: FalkorDB Live | NSE Bhavcopy Synced]        [⌘K Quick Search] [API Docs] |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [HERO SECTION]                                                                                   |
|  TAG: TEMPORAL GRAPHRAG ENGINE FOR INDIAN EQUITIES (NSE/BSE)                                     |
|  HEADLINE: The Intelligence Engine That Connects the Invisible Dots.                              |
|  SUBHEAD: Beyond flat SQL rows and hallucinating vector RAG. Maps 2nd-order commodity shocks,   |
|           macro contagions, and management guidance into a bi-temporal knowledge graph.            |
|                                                                                                   |
|  [ Try TATASTEEL ]  [ Try RELIANCE ]  [ Try BRENT_CRUDE ]  [ Try RBI_REPO_RATE ]                  |
|  [ Explore Live Graph ↓ ]    [ View REST / MCP API Contract ]                                     |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [THE KUNUMI-STYLE INTERACTIVE CONSTELLATION GRAPH SECTION]                                       |
|  +---------------------------------------------------------------------------------------------+  |
|  |  Floating Search Pill: [ I want to learn about: TATASTEEL                     ... ] [x]     |  |
|  |                                                                                             |  |
|  |                             (Commodity: COKING_COAL)                                        |  |
|  |                                       \                                                     |  |
|  |                                        \  [:EXPOSED_TO {Margin: NEGATIVE}]                  |  |
|  |                                         \                                                   |  |
|  |      (Macro: RBI_REPO) ---- [ Stock: TATASTEEL ] ---- (Commodity: HRC_STEEL)                |  |
|  |                                         /                                                   |  |
|  |                                        /  [:DIRECTLY_IMPACTS {Confidence: 0.91}]            |  |
|  |                                       /                                                     |  |
|  |                             [ News: China Stimulus ]                                        |  |
|  |                                                                                             |  |
|  |  Floating Bottom Bar:                                                                       |  |
|  |  [Active: TATASTEEL (NSE)] [4 Edges] [View: Graph | Cluster | Linear] [Open Detailed View →]  |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                                                                   |
|  * Detailed View Drawer/Overlay (Matches `detailed view.png`):                                     |
|    When user clicks any node or "Open Detailed View", cards slide into focus with halo auras:      |
|    - Card 1: Coking Coal shock -> 8% margin compression risk (Tags: Commodity, 20 min read)      |
|    - Card 2: Reg-30 Filing: Expansion of Kalinganagar cold rolling mill (Tags: NSE, Reg-30)        |
|    - Card 3: Concall Q2 Guidance Chunk: Captive iron ore insulation (Tags: Guidance, Overlap)     |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [JAMIE MCKAYE STYLE: FOUR TECHNICAL PILLARS (NO MARKETING FLUFF)]                                |
|  +--------------------------------+--------------------------------+                              |
|  | 01 / DIRECT 1ST-ORDER FACTS    | 02 / 2ND-ORDER SUPPLY CONTAGION|                              |
|  | - Official NSE Bhavcopy EOD    | - Coking Coal -> HRC Steel     |                              |
|  | - Reg-30 Corporate Filings     | - Brent Crude -> Paint/Aviation|                              |
|  | - Delivery % Volume Z-Scores   | - Dynamic LLM Ontology Builder |                              |
|  +--------------------------------+--------------------------------+                              |
|  | 03 / CROSS-NEWS CAUSAL CHAINS  | 04 / BI-TEMPORAL DOSSIER RAG   |                              |
|  | - L1-L4 Deduplication Engine   | - Fixed LAST_6M / LAST_1Y      |                              |
|  | - [:CORRELATED_WITH] Links     | - Interval validity overlap    |                              |
|  | - Multi-day narrative tracking | - Zero number hallucination    |                              |
|  +--------------------------------+--------------------------------+                              |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [SYSTEM ARCHITECTURE & DUAL-STORE SEPARATION]                                                    |
|  Dual-Store Matrix: FalkorDB (Graph + Vector) vs. TimescaleDB (Numeric Time-Series)               |
|  Traceability Guarantee: Every quant metric strictly cites `vendor_id + vendor_as_of`             |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [INTERACTIVE DEVELOPER PLAYGROUND & MCP SERVER]                                                  |
|  Tabs: [ cURL ] [ Python SDK ] [ MCP Tool Server (Cursor / Claude) ] [ OpenAPI JSON ]             |
|  Real-time response preview: `GET /api/v1/stocks/TATASTEEL/context?window=LAST_6M`                |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [FOOTER: JAMIE MCKAYE MARKDOWN MIRROR & TRANSPARENCY]                                            |
|  "The entire platform, plain text" | Direct Markdown Mirror link | Zero trackers | NSE Disclaimers|
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Key Interactive Components & Behaviors

### 4.1 The Kunumi-Style Constellation Graph
1. **Idle State:** A field of 80+ delicate micro-particles drifts smoothly across the canvas. Subtle connecting lines link natural seed clusters (Metals, Energy, Banking, Infrastructure).
2. **Search Input Bar:** A floating pill styled with glassmorphic backdrop filter and subtle border. Features preset quick-switch chips: `TATASTEEL`, `RELIANCE`, `HDFCBANK`, `BRENT_CRUDE`.
3. **Node Selection & Bloom:**
   - Clicking any dot (or searching) brings it to center.
   - Connected edges animate outward with glowing pulse lines.
   - Neighboring nodes morph into rich interactive preview cards showing badge type, entity name, relation name (`[:EXPOSED_TO]`, `[:DIRECTLY_IMPACTS]`), and confidence gauge.
4. **Detailed View Overlay (`detailed view.png`):**
   - Triggered either by clicking a node card or the bottom pill button.
   - Switches the viewport into a focused feed with blurred background.
   - Cards display halo glows, tag chips (`Article`, `Reg-30`, `Commodity Shock`), reading time / timestamps, and full causal rationale text extracted directly from the graph.

### 4.2 Jamie McKaye Content Hierarchy
- **Typography as Interface:** High contrast, crisp line-heights, zero stock photography, zero generic illustrations.
- **Data Density:** Real schema types (`vecf32($embedding)`, `(:Stock)-[:SENSITIVE_TO_MACRO]->(:MacroFactor)`).
- **Command Palette (`⌘K`):** Accessible globally to jump between tickers, entities, and API documentation.
- **Markdown Mirror:** Footer provides a 1-click `/llms.txt` and raw markdown documentation feed for AI crawlers.

