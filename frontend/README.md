# StockGraph Frontend — React + TypeScript + Vite

A modular, high-performance React application transforming [`interactive_wireframe.html`](./interactive_wireframe.html) into a well-organized component-driven architecture.

## Architecture & Directory Structure

```text
frontend/
├── index.html                     # HTML root entrypoint
├── package.json                   # Dependencies (React 18, Vite, Three.js, Lucide, Tailwind)
├── tsconfig.json                  # Strict TypeScript configuration
├── vite.config.ts                 # Vite setup with vendor chunking
├── tailwind.config.js             # Jamie McKaye deep obsidian palette (--color-ink-0..2)
├── src/
│   ├── main.tsx                   # React root mount
│   ├── App.tsx                    # Main layout coordinator & keyboard shortcut manager
│   ├── index.css                  # Tailwind directives, glassmorphic panels, and halo auras
│   ├── types/
│   │   ├── graph.ts               # Entities, Edges, Modes, and Detailed card contracts
│   │   └── api.ts                 # REST and MCP snippet contracts, MetricRow types
│   ├── data/
│   │   ├── mockGraphData.ts       # Canonical entities (TATASTEEL, RELIANCE, HDFCBANK, CRUDE, REPO)
│   │   ├── apiSnippets.ts         # cURL, MCP Tool, Python httpx, and Dossier JSON
│   │   ├── pillarsData.ts         # 4 Technical Pillars (Bhavcopy, Dynamic Ontology, L1-L4, RAG)
│   │   └── dualStoreData.ts       # TimescaleDB hypertable metrics & FalkorDB graph nodes
│   └── components/
│       ├── layout/
│       │   ├── TopAnnouncement.tsx   # Dual-store liveness, theme toggle, Cmd+K trigger
│       │   ├── Header.tsx            # Sticky navigation & graph explorer CTA
│       │   └── Footer.tsx            # Services, cadences, standards, markdown mirror
│       ├── hero/
│       │   ├── HeroSection.tsx       # Main headline, value prop, quick ticker pills, trust metrics
│       │   └── HeroRocketCanvas.tsx  # Three.js 3D rocket & dynamic launch trajectory canvas
│       ├── constellation/
│       │   ├── ConstellationSection.tsx # Explorer container with mode switcher
│       │   ├── ConstellationCanvas.tsx  # Canvas particle constellation (hoverable dots, edge rays)
│       │   ├── GraphSearchPill.tsx      # Floating search pill ("I want to learn about: ...")
│       │   ├── NodeCardOverlay.tsx      # Hoverable blossomed preview cards
│       │   └── BottomDock.tsx           # Active entity inspector with "Open Detailed View"
│       ├── modal/
│       │   ├── DetailedViewModal.tsx    # Slide-in modal matching detailed view.png with halo cards
│       │   └── CommandPaletteModal.tsx  # Cmd+K global search palette with ESC listener
│       ├── pillars/
│       │   └── TechnicalPillars.tsx     # 4 Core technical pillars
│       ├── architecture/
│       │   ├── DualStoreArchitecture.tsx # "Numbers in SQL, Relationships in FalkorDB"
│       │   └── InteractiveSqlGraphic.tsx # Interactive SQL hypertable sandbox vs FalkorDB traversal
│       └── api/
│           └── ApiSandbox.tsx           # Multi-language code tabs (cURL, MCP, Python, JSON)
```

## Running the Application

### 1. Development Server
```bash
cd frontend
npm run dev
```
Runs at `http://localhost:5173`.

### 2. Production Build
```bash
cd frontend
npm run build
```
Generates optimized code-split bundles into `dist/`.

### 3. Preview Production Build
```bash
cd frontend
npm run preview
```

## Key Features & Improvements
1. **Jamie McKaye Color Palette:** Deep obsidian void (`--color-ink-0: #0b0c0e`, `--color-ink-1: #121316`, `--color-ink-2: #1a1c20`).
2. **Interactive Constellation Canvas:**
   - Pointer cursor on hover.
   - Micro-particles and background dots are hoverable and react to mouse proximity.
   - Blossom edges with relationship tags (`[:EXPOSED_TO]`, `[:SENSITIVE_TO_MACRO]`, `[:DIRECTLY_IMPACTS]`).
   - Connected nodes show solid color preview cards.
   - 3 view modes: Constellation, Radial Cluster, and Linear Flow.
3. **Three.js Dynamic Rocket Launch Canvas:** Built in the hero section with interactive mouse-parallax, thruster particle physics, and ascending star trails.
4. **Interactive Dual-Store Graphic:**
   - TimescaleDB hypertable table sandbox with live anomaly filtering (`abs(z) >= 1.8`).
   - FalkorDB OpenCypher query traversal inspector.
   - Dual-store ingestion pipeline flow comparison.
5. **Detailed View Modal:** Complete halo aura cards (Orange, Purple, Emerald) matching `detailed view.png`.
6. **Command Palette (`⌘K` / `Ctrl+K`):** Instant ticker and entity navigation with keyboard shortcuts.

