# Revised MarketGraph design target

The latest Website Design Brief supersedes the earlier architecture proposal. The current wireframe is for research and monitoring only.

| Requirement | Current design |
| --- | --- |
| Accounts | Signup, login and settings layouts; account access uses email and password |
| Dashboard | Selected stocks, recent context, in-app alert usage, update timestamps and scheduled-data labels |
| Stock catalog | A 12-company catalog layout; NSE/BSE result filtering; explicit activation separate from searching/opening |
| Stock detail | Company context, citations, financial/history empty layouts and documents |
| Connections explorer | LAST_6M/LAST_1Y; two-record page example; graph/list alternative; retained pinned evidence; direct/indirect labels; rationale, dates, confidence unavailability |
| Work lifecycle | User-selected loading, pending, collecting, graph processing, complete, empty and failed state illustrations; retry retains filters |
| Watchlists | Selected-stock local rules and in-app research alerts only |
| Professional intelligence | Synthetic cited professional opinions; author, event, direction, horizon, expiry, status and version; conflicting evidence; no boost without credential eligibility |
| Current evidence | Expired/retracted/superseded professional records excluded from current view; separate history toggle |
| Research chat & discovery | Registered agent unavailable; connected/error layout previews; no agent request or job is run |
| Upstox | Market-data-only status/reconnect layout; token entry disabled; no credential returned or saved |
| Free / Pro | Exact entitlements from the brief, monthly issuance allowance and IST calendar reset; manual assignment/expiry, no payments |
| Developer/admin | Unrestricted environment-managed developer layout; user role/status, plan, verification, reviewer and local audit settings |

## Access specifics

Free: maximum 10 active stocks, one selected-stock research scope, selected-stock connections/financial context and monitoring, 10 new opportunity alerts per IST calendar month, restricted professional intelligence.

Pro: no product limit on active stocks or new alerts, broader permitted research/context/discovery/monitoring and professional intelligence access. Underlying service availability is still required. A plan never makes the unregistered agent service available.

Developer: unrestricted application layout access; role-preview switching is not production authorization. Accounts can be disabled in the local admin example while the environment-managed developer remains accessible.

## Removed from the previous wireframe

- Order tickets, order proposals, confirmation and execution/reconciliation workflows.
- Automated trading and trading-bot presentation.
- Portfolio/holdings screens and broker trading permissions.
- Paid subscription tiers, checkout, invoices, renewal/cancellation and purchase calls to action.
- Scripted chat responses or candidate scans presented as agent behavior.
- Telegram/WhatsApp delivery controls (the updated brief specifies an in-app feed).

## Data / service truthfulness

The source graph remains a historical 2024 fixture with real company/source links. Prices and catalog data are layout samples, not current backend results. Annual-report cutoff dates are fixture assumptions, not production ingestion history. Confidence is not fabricated. Professional identities/theses and local admin states are synthetic, not verified people or actual permissions.

The target service boundaries are Data Service (PostgreSQL/TimescaleDB), StockGraph (FalkorDB), Platform (its own PostgreSQL), and Agents (health-only scaffold; actual agents developed separately). No API integration is claimed. News ingestion is hourly; market records follow scheduled cadences and do not stream over websockets.

The established visual direction, animated 3D graph/mesh, mascot rig and motion behavior remain. The supplied historical system-design attachment was not edited; this updated brief is authoritative for the wireframe.

## Updated role policy and access layouts

Ordinary accounts retain User; Professional and Reviewer privileges are combinable. Professional authoring does not unlock Pro intelligence. Verified author status and independent authorized assignment gate ordinary publication. Assigned reviewers can approve or reject; they cannot self-approve their own work or gain admin/Pro access from their role. Developer is environment-managed, cannot be assigned by public signup or normal role APIs, has unrestricted supported application/admin access and an audited self-approval exception. Budgets still apply.

Added dedicated User/Professional/Admin signup/signin layouts, role-specific dashboards, combined-role navigation, local admin sessions/records/catalog/link-edit examples and policy checks. These are prototype interactions, not production authentication or permissions. Free/Pro plans and disabled billing remain as before.

## Management discoverability and the stock workflow

Developer dashboard cards and sidebar links expose user CRUD, professional privilege/verification management, per-user Upstox credential flows, and a visual stock-graph inspector/editor. These are local sample operations with audit records. Real credentials are never accepted; Add/Update/Remove changes metadata only. User removal is confirmed; Developer provisioning remains protected.

Explore Stocks opens a stable stock URL with graph and structured connections, price-history layout, sources, documents, unavailable stock-chat state and separate watchlist/activation/monitoring controls. Price history is explicitly synthetic. Background evaluation, Data Service reads and agent calls require the authenticated backend. Existing research-only scope, Free/Pro policy and original non-Three.js hero remain intact.
