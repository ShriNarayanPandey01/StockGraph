# StockGraph frontend

The Vite frontend contains the public landing page, account access, and an authenticated research workspace. The visual direction comes from the supplied wireframe. Workspace content is loaded from the Platform API; the landing-page graph is an explicitly labelled historical illustration.

## Local development

1. Start the Platform, Data, and Graph services and their dependencies using the repository's service guide.
2. From this directory run `npm install`, then `npm run dev` (use `npm.cmd` in PowerShell if script execution is disabled).
3. Open the local URL printed by Vite. Vite proxies `/api` to `http://127.0.0.1:8002` by default.

The workspace uses a bearer session stored in the current browser tab's session storage. Signing out revokes the session when the service is reachable and clears it locally. Backend permissions and quotas remain authoritative.

## Deployment

Run `npm run build` to create `dist/`. Serve that directory and route `/api/v1/*` to the Platform service on the same origin. Alternatively set `VITE_API_BASE_URL` at build time to a Platform origin configured to permit the frontend origin. Do not expose internal Data or Graph service credentials to the browser.

Stock selection, registration, stock context, watchlists, alerts, research conversations, discovery, monitoring, Upstox settings, contributions, and developer account editing use Platform endpoints. The LangGraph agent worker is an opt-in developer pilot; the UI reports its availability, job state, and missing data rather than filling the workspace with sample records.

The Watchlists screen switches between saved lists and the account's active-stock
selection. Stocks in a saved list can be added to or removed from the active
selection without removing them from that list. The active view reports matching
monitoring-rule status and agent availability. Selecting a stock alone does not
create a monitoring rule; configure rules in Monitoring.

Professional authors can use Review insights to track submissions. Reviewers
and developers can open the same page to inspect sources and approve or reject
queued insights; developers can also reach it from Administration. Backend review
permissions and independent-review rules apply.

## Stock connections

The stock view has a separate connection explorer with a 1, 2 or 3 hop selector.
Select nodes with a click or Enter/Space to inspect their descriptions, relationships,
confidence and sources. Nodes form a constellation around the stock, with positions shaped by their
connections. The canvas grows with the graph; Rearrange creates another layout
without fetching new data. Scroll vertically or horizontally, drag the background to
pan, and drag individual nodes to arrange them. Use the zoom controls or
Ctrl + scroll to zoom; Reset view restores the original arrangement and centers the stock.
Selecting an offscreen node in the Nodes tab brings it into view. The graph displays up to 200 nodes and 500
edges and indicates when the result is truncated.

Relationships, news and nodes have a separate bounded information panel. Its
pagination and retry controls update only that panel; the graph, price chart and
company details stay mounted. Changing depth fetches a new graph independently
of the evidence page. Node information can also be opened from the Nodes tab.

Deploy the frontend, Platform API and Graph API together for the optional `hops`
contract. Data ingestion and the Data Service do not need changes for this view.

Run `npm test` for model regressions. `npm run test:browser` runs Chromium checks
against mocked APIs and starts its own Vite server. It requires an installed
Playwright package and Chromium; `PLAYWRIGHT_MODULE` can point to an existing
`playwright` or `playwright-core` installation. `STOCKGRAPH_TEST_URL` can select an
already running frontend. On restricted Windows environments, build with
`npm.cmd run build -- --configLoader runner` if config bundling cannot read parent
directories.
