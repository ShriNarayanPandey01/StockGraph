# API Access and Data Contracts

This document is the route and data-type inventory for the currently implemented
MarketGraph APIs. It identifies each route's intended caller, the shape of data
it accepts, and the kind of data it returns. It does not contain request or
response examples. Endpoint-level schemas, validation detail, status codes, and
examples belong in the Swagger/OpenAPI reference.

The implementation and current access policy are described in
[service boundaries](04_SERVICE_BOUNDARIES.md) and
[Phase 2 operations](PHASE2_PLATFORM.md). FastAPI services publish generated
Swagger UI at `/docs` and OpenAPI JSON at `/openapi.json` unless disabled by the
deployment.

## Services and access model

| Service | Default local base URL | Responsibility | Who calls its domain routes |
|---|---|---|---|
| Platform | `http://localhost:8002` | Accounts, user permissions, plans, research workflows, and user-scoped market/graph access | End users with a Platform bearer session; unauthenticated callers only for the listed account-lifecycle routes |
| StockGraph | `http://localhost:8000` | FalkorDB graph reads, graph processing requests, and graph administration | Trusted services presenting `X-Internal-Service-Key`; end users use the Platform routes |
| Upstox Data Service | `http://localhost:8001` | Canonical catalog, source ingestion, financial data, and market-data reads | Trusted services presenting `X-Internal-Service-Key`; end users use the Platform routes |
| Agents | Optional worker; health process on `http://localhost:8005` | Developer-pilot LangGraph research, discovery, and monitoring | Worker claims leased Platform jobs; health process does not execute them |

Platform authenticates people with `Authorization: Bearer <session>`. Its normal
user routes apply ownership, account state, active-stock selection, and the
effective Free/Pro plan. The Developer identity is provisioned from server
configuration; it is not assignable in a public request. Developer operations
are audited and may bypass ownership and plan limits. Professional authoring
requires the verified `PROFESSIONAL` role; review requires `REVIEWER` or
Developer. Professional authoring and Pro access to professional intelligence
are separate permissions.

Every StockGraph and Data Service business route, including routes whose path
starts with `/api/v1`, is behind `X-Internal-Service-Key`. The services also
accept trusted context headers from Platform for developer operations and
professional-evidence filtering. Health, readiness, and generated API schema
routes are available without that key. These service keys and context headers
are for service-to-service calls and must not be sent by end-user applications.

External-agent integration uses `X-Agent-Key: <PLATFORM_AGENT_SERVICE_KEY>`.
After a job is claimed, job-specific operations also require `X-Job-Lease`.
Agent requests are scoped to the stored job owner, selected tickers, evidence
permissions, and lease. This credential is separate from the internal service
key and a Platform user session.

The local `stockgraph-mcp` process exposes stdio tools that call authenticated
Platform routes using `MARKETGRAPH_PLATFORM_TOKEN`. MCP reads inherit that
account's ownership and access policy; there is no remote HTTP MCP gateway.

## Shared data conventions

| Type | Meaning |
|---|---|
| `string` | UTF-8 text or an enumerated string value |
| `integer` | Whole-number JSON value |
| `number` | JSON integer or floating-point value |
| `boolean` | JSON true/false value |
| `object` | JSON object; some provider-owned payloads are intentionally open-ended |
| `array<T>` | JSON array whose elements have type `T` |
| `UUID` | UUID-formatted string |
| `date` | ISO calendar date, `YYYY-MM-DD` |
| `timestamp` | ISO 8601 timestamp; source/event timestamps include a timezone unless stated otherwise |
| `epoch` | Unix timestamp in seconds |
| `window` | `LAST_6M` or `LAST_1Y`; fixed research window, not a free-form date range |
| `ticker` | Canonical uppercase NSE/BSE trading symbol |

For paginated graph reads, `offset` and `limit` are integers. Responses may
include `next_offset`, `has_more`, and an `as_of_ts` snapshot timestamp. Reuse
the returned snapshot timestamp while continuing a graph pagination sequence.

## Shared contract types

These names are used in the route inventory below to avoid repeating full field
lists. They describe field types and contents, not example payloads.

| Contract | Data shape |
|---|---|
| `RegistrationInput` | Object with required `query: string`; optional `exchange: NSE \| BSE`; optional `strengths: array<string>` and `business_exclusions: array<string>`. A query is a company name, ticker, or ISIN. |
| `RegistrationJob` | Object with `job_id: UUID`, state string, optional ticker, attempt count, error string or null, warning strings, and creation/update timestamps. A Graph-facing or Platform status result may also include `data_state`, `graph_state`, and Graph status. |
| `Principal` | Object with user UUID, name, optional email, professional-verified boolean, developer and disabled booleans, role string array, plan enum (`FREE` or `PRO`), optional plan-expiry timestamp, and active-selection-initialized boolean. |
| `EntityInput` | Object with canonical `id`, `name`, `description`, `aliases: array<string>`, optional `unit`, macro explainer strings, commodity `related_ids: array<string>`, and `related_rationale`. Supported kinds are `Commodity`, `MacroFactor`, and `Sector`; Stock identity is created through registration. |
| `EntityMutation` | Object with canonical `entity_id`, revision integer, changed boolean, and processing-state string. |
| `CatalogEntity` | Object with kind, entity ID, revision integer, and a canonical entity `payload: object`. A catalog response is an `entities: array<CatalogEntity>`. |
| `ManualNewsInput` | Object with optional external ID; headline and summary strings; source URL and source strings; timezone-aware publication timestamp; category enum; optional sentiment number; canonical `tickers: array<ticker>`; and `ticker_sentiment: object<string, number>`. Sentiment scores are bounded from -1 to 1. |
| `NewsSubmission` | Object with external ID, state string, and eligibility source/reason metadata. |
| `StockSummary` | Object with exchange, instrument key, ticker, ISIN, legal and optional short name, source timestamp, and registered boolean. |
| `StockDetail` | `StockSummary` plus a profile object, vendor ID, and vendor-as-of timestamp. Profile fields include business summary, optional sector and sector-market-cap objects, and prospectus document links. |
| `Shareholding` | Object with exchange, ticker, ISIN, vendor ID, vendor-as-of timestamp, and reporting periods. Each period has a period string, optional promoter/FII/DII/public percentages, and a breakdown map of string to number. |
| `Candle` | Object with trade date, numeric OHLC values, integer volume, vendor ID, and vendor-as-of timestamp. The response adds exchange, ticker, ISIN, requested date bounds, vendor ID, and `candles: array<Candle>`. |
| `FinancialHistory` | Object with ticker, fixed window, start/end dates, `daily_metrics: array<object>`, `quarterly_financials: array<object>`, and `statements: array<object>`. Numeric rows carry vendor provenance where available; raw statement `payload` is provider-defined JSON. |
| `MarketEnvelope<T>` | Object with source string, fetched timestamp, optional provider-as-of timestamp, and `data: T`. |
| `DocumentInput` | Object with ticker, title, public source URL, media type (`application/pdf` or `text/plain`), document-kind enum, base64 content string, and literal-true redistribution permission. |
| `DocumentVersion` | Object containing version/document UUIDs, ticker, title/source metadata, revision, content hash, timestamps, extracted pages and chunks. `/original` returns binary document bytes with its media type instead of JSON. |
| `GraphNode` | Object with ID, kind, and properties object. |
| `GraphEdge` | Object with ID, source and target IDs, relation string, optional confidence number and rationale string, provenance object, and relationship-properties object. |
| `GraphContext` | Object with ticker, window, start/end epoch timestamps, processing status, node and edge arrays, direct and indirect news arrays, professional-evidence array, evidence-policy object, and pagination object. News cards may include a citation object containing canonical URL, title, publisher, and event date. |
| `PublicMarketGraph` | Object with generation/start/end epoch timestamps, selection counts and partial-result flag, and node/edge arrays. |
| `ContributionInput` | Object with ticker, title, body, direction enum (`BULLISH`, `BEARISH`, `NEUTRAL`), horizon, timezone-aware event/expiry timestamps, disclosures string, and one or more evidence citations. Each citation has URL, title, locator, and optional document-version UUID. |
| `ContributionRecord` | Object with contribution identity, author, status, revision, timestamps, version records, and review records as applicable. Version content uses `ContributionInput` fields. |
| `ResearchInput` | Object with question string, canonical ticker array, and fixed window. Conversations require an explicit single ticker for Free accounts; discovery is a Pro feature. |
| `AgentJob` | Object with job UUID, kind, state, owner-scoped input and status/result fields. Secrets, lease tokens, and internal fingerprints are not returned through user-facing job reads. Pro-only result content is filtered for accounts without Pro access. |
| `EvidenceReference` | Object with evidence-kind enum (`news`, `professional`, `document`, `financial`), ID string, optional locator, and quoted text. |
| `MarketResponse` data types | Option expiry, option-chain, smartlist, institutional-flow, holiday, exchange-status, and derivatives-analytics data are typed by route; provider-extensible values remain JSON objects or arrays. |

## Upstox Data Service API

All routes in this section require `X-Internal-Service-Key`, except health,
readiness, and generated documentation. Platform proxies appropriate user
requests after applying the Platform session and entitlement checks.

### Service status, registration, registry, and financials

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /health` | Health probe | None | Service name and status strings. |
| `GET /ready` | Health probe | None | Readiness status string; unavailable dependencies produce an error response. |
| `POST /internal/v1/upstox/validate-credential` | Platform service only | Object with `access_token: secret string`. | Connection status string, market-data-validated boolean, and trading-enabled boolean. The token is not returned. |
| `POST /api/v1/stocks` | Platform or trusted service | `RegistrationInput`. | `RegistrationJob` acceptance state. |
| `GET /api/v1/jobs/{job_id}` | Platform or trusted service | Path `job_id: UUID`. | `RegistrationJob`; may include graph-processing status while projection is running. |
| `GET /api/v1/entities` | Platform or trusted service | Optional query `kind` enum: `Stock`, `Commodity`, `MacroFactor`, or `Sector`. | `entities: array<CatalogEntity>`. |
| `POST /api/v1/entities/{kind}` | Platform developer proxy or trusted service | Path kind (`Commodity`, `MacroFactor`, or `Sector`) and `EntityInput`. Stock kind is rejected. | `EntityMutation`. |
| `PATCH /api/v1/admin/entities/{kind}/{entity_id}` | Platform developer proxy or trusted service | Kind and entity ID in path; body with `changes: object` and `reason: string`. Changed fields are limited by entity kind. | Entity ID, kind, new revision, changed boolean, and processing-state string. |
| `POST /api/v1/manual/news` | Platform developer proxy or trusted service | `ManualNewsInput`; tickers and sentiment keys must be canonical registered tickers. | `NewsSubmission`. |
| `GET /api/v1/stocks/{ticker}/financials` | Platform or trusted service | Ticker path and required `window`. | `FinancialHistory`. |

### Stock directory and stored financial data

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /api/v1/stocks` | Platform or trusted service | Optional `query: string`, `exchange: NSE \| BSE`, `cursor: string`, and `limit: integer` (1–100). | Page with `items: array<StockSummary>` and optional next-cursor string. |
| `GET /api/v1/stocks/{ticker}` | Platform or trusted service | Ticker path and optional exchange enum, default NSE. | `StockDetail`. |
| `GET /api/v1/stocks/{ticker}/shareholding` | Platform or trusted service | Ticker path and optional exchange enum, default NSE. | `Shareholding`. |
| `GET /api/v1/stocks/{ticker}/candles` | Platform or trusted service | Ticker path, optional exchange, optional `from` and `to` calendar dates. | Candle response with ticker identity, date bounds, vendor provenance, and `candles: array<Candle>`. |

These directory reads may fetch or persist source data as implemented by the
Data Service. They do not register a stock or emit a graph-registration event.

### Document intake and reads

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `POST /api/v1/documents` | Platform developer proxy only | `DocumentInput` plus `X-Internal-Api-Key`. The intake key is separate from the service key. | Accepted document/version metadata, content hash, page/chunk counts, revision, receipt timestamp, processing state, and duplicate flag. |
| `GET /api/v1/documents/{version_id}` | Platform or trusted service | Path `version_id: UUID`. | `DocumentVersion` JSON metadata, extracted pages, and chunks. |
| `GET /api/v1/documents/{version_id}/original` | Platform or trusted service | Path `version_id: UUID`. | Original PDF or plain-text bytes with the stored media type. |

### On-demand market data

All market reads return `MarketEnvelope<T>`. If a personal Upstox credential is
used, the trusted caller supplies `X-Upstox-Access-Token` and a scoped
`X-MarketGraph-Credential-Scope`; the Data Service only accepts these headers
for GET market-data routes. These headers are internal and are never returned
to the end user.

| Method and path | Caller | Input data | `data` type returned |
|---|---|---|---|
| `GET /api/v1/option-chains/expiries` | Platform or trusted service | Required `underlying: string`; optional `exchange: NSE \| BSE`. | Underlying, exchange, instrument key, and `expiries: array<date>`. |
| `GET /api/v1/option-chains` | Platform or trusted service | Required underlying and expiry string; optional exchange. Expiry is an ISO date or supported relative-expiry keyword. | Underlying, exchange, instrument key, expiry, and strike rows as JSON objects. |
| `GET /api/v1/market/smartlists/{kind}` | Platform or trusted service | Kind `mtf`, `options`, or `futures`; optional asset type; category; page number; page size. Options/futures require asset type and category. | Asset type, category, metric key, optional provider timestamp, smartlist object array, and page counts. |
| `GET /api/v1/market/institutional-flows` | Platform or trusted service | Required investor `FII \| DII`, segment string; optional interval `1D \| 1M` and start date. | Investor, interval, and segment-to-row-array object. |
| `GET /api/v1/market/holidays` | Platform or trusted service | Optional calendar date. | Array of holiday-session objects or provider JSON object. Holiday objects contain dates, descriptions/types, closed exchanges, and open sessions. |
| `GET /api/v1/market/status/{exchange}` | Platform or trusted service | Exchange path string from the supported exchange set. | Exchange, status string, optional provider update epoch, and provider-extensible fields. |
| `GET /api/v1/market/pcr` | Platform or trusted service | Underlying, expiry, exchange, required date, optional bucket interval. | Derivatives analytics object with metric, underlying, exchange, instrument key, date, and metric data object. |
| `GET /api/v1/market/oi` | Platform or trusted service | Underlying, expiry, exchange, required date; no interval fields. | Derivatives analytics object. |
| `GET /api/v1/market/change-oi` | Platform or trusted service | Underlying, expiry, exchange, required date, optional interval. | Derivatives analytics object. |
| `GET /api/v1/market/max-pain` | Platform or trusted service | Underlying, expiry, exchange, required date, optional bucket interval. | Derivatives analytics object. |
| `GET /api/v1/market/{metric}` | Platform or trusted service | Unknown metric path. | No market data; this compatibility fallback returns a not-found error for unsupported metric names. |

## StockGraph API

All routes in this section require `X-Internal-Service-Key`, except health,
readiness, and generated documentation. End-user permissions are applied by
Platform before it calls the relevant graph route.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /health` | Health probe | None | Service name and status strings. |
| `GET /ready` | Health probe | None | Readiness status string; unavailable dependencies produce an error response. |
| `POST /internal/v1/news/eligibility` | Data Service only | Headline and summary strings, candidate ticker string array, and preliminary news-category enum. | Eligibility boolean, optional accepted category, and reason string. This review does not persist graph data. |
| `POST /api/v1/stocks` | Platform or trusted service | `RegistrationInput`. | `RegistrationJob` acceptance state. |
| `POST /api/v1/manual/stocks` | Platform developer proxy or trusted service | `RegistrationInput`. | `RegistrationJob` acceptance state. |
| `POST /api/v1/manual/entities/{kind}` | Platform developer proxy or trusted service | Kind `Commodity`, `MacroFactor`, or `Sector`; `EntityInput`. | `EntityMutation`. |
| `POST /api/v1/manual/news` | Platform developer proxy or trusted service | `ManualNewsInput`. | `NewsSubmission`-type enqueue result. |
| `GET /api/v1/jobs/{job_id}` | Platform or trusted service | Path `job_id: UUID`. | Combined `RegistrationJob` data and separate data/graph state where available. |
| `GET /api/v1/stocks/{ticker}/context` | Platform, trusted agent, or trusted service | Ticker; `window`; optional `offset`, `limit` (1–200), and `as_of_ts: epoch`. Only fixed windows are accepted. | `GraphContext`. Professional evidence and its policy section are included only when trusted caller context permits it. |
| `GET /api/v1/public/market-graph` | Trusted service caller | No query parameters. | `PublicMarketGraph`, a bounded public-data preview with selection counts and partial-result flag. The route still requires the internal service key. |
| `POST /api/v1/developer/edges` | Platform developer proxy only | Existing-node source and target references; relation and rationale strings; actor string; optional confidence number and metadata object. | Developer edge record with edge ID, endpoints, relation, rationale, actor, optional confidence, event epoch, and metadata. |
| `GET /api/v1/developer/edges` | Platform developer proxy only | Optional `limit` (1–500) and `offset` integers. | Page with edge-record array, limit, and offset. |
| `PUT /api/v1/developer/edges/{edge_id}` | Platform developer proxy only | Edge ID; relation, rationale, actor, optional confidence, and metadata object. | Updated developer edge record. |
| `DELETE /api/v1/developer/edges/{edge_id}` | Platform developer proxy only | Edge ID path. | Edge ID and deleted boolean. |
| `GET /api/v1/stocks/{ticker}/professional-evidence` | Platform or trusted agent with professional-evidence scope | Ticker; optional fixed `window`, `limit`, `offset`, and `as_of_ts`. | Professional-evidence page containing contribution/version data, authorship/publishing timestamps, weighting policy, contradiction handling, and pagination. |
| `GET /api/v1/stocks/{ticker}/documents/search` | Platform or trusted agent | Ticker; optional `q: string`, `offset`, and `limit` (1–100). | Ticker, document-excerpt item array with citation locators, and pagination fields. |

Manual stock, entity, and news submissions flow through Data Service validation,
canonical persistence, and the normal outbox/worker processing path. Developer
edge operations are separate audited overrides and only operate on existing
graph nodes.

## Agents template API

The optional Agents template deployment has no job-processing or business
routes. Its only implemented API route is a public health probe.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /health` | Health probe | None | Status and service strings, `execution_enabled: boolean`, and `registered_agents: integer`. |

## Platform API

`GET /health`, `GET /ready`, and generated documentation do not require a user
session. Account signup, login, verification, verification resend, password
recovery, and password reset are public account-lifecycle operations. Other
user routes require a bearer session unless they are identified below as
Developer-only or external-agent routes.

### Account lifecycle, identity, and user administration

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /health` | Health probe | None | Service name, phase, and status. |
| `GET /ready` | Health probe | None | Readiness status string. |
| `POST /api/v1/auth/signup` | Public | Email, name, and secret password strings. | Object with a generic `detail: string`; an eligible account is immediately usable and account existence is not disclosed. |
| `POST /api/v1/auth/login` | Public | Email and secret password strings. | Object with `access_token: string`, token type, expiry timestamp, and authenticated `Principal` data. |
| `POST /api/v1/auth/logout` | Authenticated user | Bearer session in Authorization header; no body. | Object with session-revocation `detail: string`. |
| `POST /api/v1/auth/change-password` | Authenticated user | Current and new secret password strings. | Object with password-change `detail: string`. |
| `GET /api/v1/me` | Authenticated user | None | User identity/roles/plan and effective access-policy object. |
| `GET /api/v1/access-policy` | Authenticated user | None | Effective plan, feature booleans/tier labels, limits, timezone, and policy revision. |
| `GET /api/v1/me/usage` | Authenticated user | None | Usage-counter array, active-stock count, current-month alert count, reset timestamp, and access-policy object. |
| `GET /api/v1/admin/users` | Developer only | Optional `limit` (1–200) and `offset` integers. | Paginated user-record array. |
| `GET /api/v1/admin/users/{user_id}` | Developer only | Path `user_id: UUID`. | User account record with role, verification, plan, and account-state fields. |
| `PATCH /api/v1/admin/users/{user_id}` | Developer only | Path UUID; optional account fields: name string, roles array, professional-verified boolean, plan enum (`FREE` or `PRO`), timezone-aware plan-expiry timestamp/null, disabled boolean. | Updated user account record. |
| `POST /api/v1/admin/users/{user_id}/revoke-sessions` | Developer only | Path `user_id: UUID`; no body. | Session-revocation result/count. |

### Active-stock selection, plan policy, and Upstox connections

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /api/v1/me/active-stocks` | Authenticated user | None | Canonical ticker array, selection-initialized boolean, and effective access policy. |
| `PUT /api/v1/me/active-stocks` | Authenticated user | Object with `tickers: array<ticker>`. | Updated ticker array, initialization state, and effective access policy. |
| `GET /api/v1/admin/plans` | Developer only | None | Plan-policy item array; each policy has plan, active-stock/monthly-alert limits, feature map, and revision. |
| `PUT /api/v1/admin/plans/{plan}` | Developer only | Plan `FREE \| PRO`; expected revision integer; optional positive stock/alert limits; complete feature-name-to-boolean map. | Updated plan-policy object with revision and feature map. |
| `GET /api/v1/me/broker-connections/upstox` | Authenticated user, own account | None | Connection status, revision, and optional validation timestamp. No credential is returned. |
| `PUT /api/v1/me/broker-connections/upstox` | Authenticated user, own account | Object with secret `access_token` string. | Connection status, revision, and validation timestamp. The submitted token is not returned. |
| `DELETE /api/v1/me/broker-connections/upstox` | Authenticated user, own account | No body. | Disconnected status, revision, and null validation timestamp. |

### Professional contributions and evidence

Contribution draft creation, versioning, submission, and retraction require a
verified Professional author or Developer. Review-queue reads and reviews
require Reviewer or Developer. Normal users can access only their own drafts;
Developer access is audited. Professional-evidence reads require the effective
Pro plan or Developer.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `POST /api/v1/contributions` | Verified Professional author or Developer | `ContributionInput`; required `Idempotency-Key` header. | `ContributionRecord` with its initial draft version. |
| `GET /api/v1/contributions` | Authenticated user; Developer can inspect all authors' records | None. | Contribution-record array, limited by the service. |
| `GET /api/v1/contributions/{contribution_id}` | Owner or Developer | Path `contribution_id: UUID`. | `ContributionRecord` with version and review arrays. |
| `POST /api/v1/contributions/{contribution_id}/versions` | Verified Professional author or Developer | `ContributionInput` fields plus `expected_revision: integer`. | Updated `ContributionRecord` with immutable version history. |
| `POST /api/v1/contributions/{contribution_id}/submit` | Verified Professional author or Developer | `expected_revision: integer`. | Updated contribution state/revision and version metadata. |
| `GET /api/v1/review-queue` | Reviewer or Developer | None. | Submitted contribution/version array with author and submission metadata. |
| `POST /api/v1/contributions/{contribution_id}/review` | Reviewer or Developer | Expected revision; decision (`APPROVE` or `REJECT`); reason string. | Contribution/version IDs, resulting state, and revision. |
| `POST /api/v1/contributions/{contribution_id}/retract` | Author or Developer | Expected revision and reason string. | Contribution ID, retracted state, and revision. |
| `GET /api/v1/stocks/{ticker}/professional-evidence` | Pro account or Developer; ticker must be eligible under account policy | Ticker; optional `limit` (1–100) and `offset` integers. | Evidence item array, access marker, weighting-policy metadata, contradiction-retention boolean, and pagination. |

### User stock, financial, graph, and document reads

Authenticated stock search is available to Platform users. Stock-scoped data
and context reads require the stock to be in the user's active selection on Free
plans; Pro and Developer access follows the effective policy. Professional
evidence remains separately filtered.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /api/v1/market/stocks` | Authenticated user | Optional query string, exchange enum, cursor string, and limit integer (1–100). | Stock directory page with `items: array<StockSummary>` and optional next cursor. |
| `GET /api/v1/market/stocks/{ticker}` | Authenticated user with stock access | Ticker and optional exchange enum. | `StockDetail`. |
| `GET /api/v1/market/stocks/{ticker}/candles` | Authenticated user with stock access | Ticker, optional exchange, optional `from`/`to` dates. | Candle response with `candles: array<Candle>`. |
| `GET /api/v1/market/stocks/{ticker}/shareholding` | Authenticated user with stock access | Ticker and optional exchange enum. | `Shareholding`. |
| `GET /api/v1/market/stocks/{ticker}/financials` | Authenticated user with stock access | Ticker and optional fixed `window` (default `LAST_6M`). | `FinancialHistory`. |
| `POST /api/v1/market/stock-registrations` | Authenticated user | `RegistrationInput`. | `RegistrationJob` acceptance result. |
| `GET /api/v1/market/stock-registrations/{job_id}` | Authenticated user | Path job ID string. | `RegistrationJob` with data and graph status where available. |
| `GET /api/v1/stocks/{ticker}/connections` | Authenticated user with stock access | Ticker; optional fixed `window`, `offset`, `limit` (1–200), and `as_of_ts: epoch`. | `GraphContext`. |
| `GET /api/v1/stocks/{ticker}/documents/search` | Authenticated user with stock access | Ticker; optional `q: string` (maximum 200 characters), `offset`, and `limit` (1–100 effective Graph-service range). | Ticker, document-excerpt item array with text and citation locator fields, and pagination. |
| `GET /api/v1/documents/{version_id}` | Authenticated user with access to the document's stock | Path `version_id: UUID`. | `DocumentVersion` JSON metadata, extracted pages, and chunks. |

Platform market-data proxy routes prefer the authenticated user's Upstox
credential when connected; otherwise they use the shared read-only provider
credential. A rejected personal credential is reported for reconnection rather
than silently switching credentials. Stock registration and scheduled shared
ingestion use the service credential.

### Watchlists, research, monitoring, and alerts

Watchlists, conversations, monitors, jobs, and alerts are user-owned. Developers
can inspect or operate across accounts where the route permits it. Research,
monitoring, and discovery also apply the feature and active-stock rules from
the current policy.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `GET /api/v1/watchlists` | Authenticated user; Developer can read all | Optional `limit` integer (1–500). | Watchlist-record array. |
| `POST /api/v1/watchlists` | Authenticated user | Watchlist name string and canonical ticker array. | Watchlist record with owner, name, tickers, and timestamps. |
| `PUT /api/v1/watchlists/{list_id}` | Owner or Developer | Path UUID; watchlist name and canonical ticker array. | Updated watchlist record. |
| `DELETE /api/v1/watchlists/{list_id}` | Owner or Developer | Path UUID; no body. | No content. Pending monitor jobs for the list are cancelled. |
| `POST /api/v1/conversations` | Authenticated user | Conversation title string. | Conversation record. |
| `GET /api/v1/conversations/{conversation_id}/messages` | Owner or Developer | Conversation UUID; optional `limit` integer (1–500). | Message item array; Pro-only content is marked restricted when access is absent. |
| `POST /api/v1/conversations/{conversation_id}/messages` | Owner or Developer | `ResearchInput`; required `Idempotency-Key` header. | `AgentJob` acceptance state. |
| `POST /api/v1/discovery/scans` | Pro account or Developer | `ResearchInput`; required `Idempotency-Key` header. | `AgentJob` acceptance state. |
| `GET /api/v1/agent-jobs/{job_id}` | Owner or Developer | Path job UUID. | `AgentJob`; Pro-only result fields are filtered when the reader lacks access. |
| `POST /api/v1/monitor-rules` | User with monitoring permission; market scope requires Pro or Developer | Watchlist UUID or null; scope (`watchlist` or `market`); question string; interval integer in seconds. | Monitor record with owner, scope, schedule, and state fields. |
| `GET /api/v1/monitor-rules` | Authenticated user; Developer can read all | Optional `limit` integer (1–500). | Monitor-record array, including effective ticker scope. |
| `DELETE /api/v1/monitor-rules/{monitor_id}` | Owner or Developer | Path monitor UUID; no body. | No content. Outstanding monitor work is cancelled. |
| `GET /api/v1/alerts` | Authenticated user; Pro-only items require Pro/Developer | Optional `limit` (1–200) and cursor UUID. | Alert item array and optional next-cursor UUID. |
| `POST /api/v1/alerts/{alert_id}/acknowledge` | Owner with access to the alert, or Developer | Path alert UUID; no body. | Alert ID and seen-at timestamp. |

### Developer operations

All routes in this section require a Developer bearer session. Operations that
change records or read another user's information are audited.

| Method and path | Input data | Returned data |
|---|---|---|
| `GET /api/v1/admin/users/{owner_id}/records/{resource}` | Owner UUID; resource enum (`watchlists`, `conversations`, `messages`, `monitors`, `jobs`, `alerts`, `contributions`); optional limit (1–500) and offset integers. | Record item array. Lease tokens and internal fingerprints are omitted. |
| `GET /api/v1/admin/audit` | Optional limit (1–500) and offset integers. | Audit-record item array. |
| `GET /api/v1/admin/graph/entities` | Optional canonical kind enum. | `entities: array<CatalogEntity>`. |
| `GET /api/v1/admin/graph/stocks/{ticker}/context` | Ticker; optional fixed window, offset, limit (1–200), and `as_of_ts: epoch`. | Full developer-scoped `GraphContext`, including professional evidence where available. |
| `PATCH /api/v1/admin/graph/entities/{kind}/{entity_id}` | Canonical kind and ID; `changes: object`; `reason: string`. | Versioned `EntityMutation` state. |
| `GET /api/v1/admin/users/{owner_id}/broker-connections/upstox` | Owner UUID. | Broker status, revision, and optional validation timestamp; no token. |
| `DELETE /api/v1/admin/users/{owner_id}/broker-connections/upstox` | Owner UUID. | Disconnected broker status; no token. |
| `POST /api/v1/admin/manual/stocks` | `RegistrationInput`. | `RegistrationJob` acceptance state. |
| `POST /api/v1/admin/manual/entities/{kind}` | Kind `Commodity`, `MacroFactor`, or `Sector`; `EntityInput`. | `EntityMutation`. |
| `POST /api/v1/admin/manual/news` | `ManualNewsInput`. | `NewsSubmission`. |
| `POST /api/v1/admin/graph/edges` | Source/target node references, relation, rationale, optional confidence and metadata. Platform supplies the developer actor identity. | Developer edge record. |
| `GET /api/v1/admin/graph/edges` | Optional limit (1–500) and offset integers. | Developer-edge item array and pagination values. |
| `PUT /api/v1/admin/graph/edges/{edge_id}` | Edge ID; relation, rationale, optional confidence, metadata, and required edit reason. | Updated developer-edge record with retained edit history. |
| `DELETE /api/v1/admin/graph/edges/{edge_id}` | Edge ID. | Edge ID and deleted boolean. |
| `GET /api/v1/admin/market/{resource}` | Resource enum: option expiries, option chain, institutional flows, holidays, PCR, OI, change-OI, or max-pain; query fields are forwarded to the matching Data Service route. | Matching `MarketEnvelope<T>`. |
| `POST /api/v1/admin/documents` | `DocumentInput`. | Accepted document/version metadata and processing status. |

### External-agent leased API

These routes use the agent service credential rather than a user bearer token or
the internal service key. `X-Job-Lease` is required for operations on a claimed
job. The Platform derives user identity, plan, stock scope, and evidence access
from the stored job.

| Method and path | Caller | Input data | Returned data |
|---|---|---|---|
| `POST /internal/v1/agent/jobs/claim` | Configured external agent with `X-Agent-Key` | No body. | Nullable claimed job (including its lease token for use in `X-Job-Lease`), available tool-name array, maximum tool-call count, source-content trust label, and execution-enabled boolean. |
| `POST /internal/v1/agent/jobs/{job_id}/heartbeat` | Agent with `X-Agent-Key` and matching `X-Job-Lease` | Job UUID path and lease header; no body. | Lease-expiry timestamp. |
| `GET /internal/v1/agent/jobs/{job_id}/context/{ticker}` | Agent with matching lease and ticker in job scope | Job UUID and ticker paths; lease header; optional offset, limit, and graph snapshot epoch. | Ticker, `GraphContext`, `FinancialHistory`, available-evidence array, source-trust label, and analysis-policy object. |
| `GET /internal/v1/agent/jobs/{job_id}/documents/{ticker}` | Agent with matching lease and ticker in job scope | Job UUID and ticker paths; lease header; optional query string, offset, and limit (1–100). | Document search page, available-evidence array, and source-trust label. |
| `POST /internal/v1/agent/jobs/{job_id}/fail` | Agent with matching lease | Job UUID and lease; body with `retryable: boolean`. | Updated public `AgentJob` status. |
| `POST /internal/v1/agent/jobs/{job_id}/complete` | Agent with matching lease | Job UUID and lease; `AgentResult` described below. | Updated public `AgentJob` status/result fields. |
| `GET /internal/v1/agent/jobs/{job_id}/candidates` | Agent with matching discovery/monitor lease | Offset and limit. | Stable, job-scoped 72-hour candidate snapshot with source material versions and coverage. |
| `GET /internal/v1/agent/jobs/{job_id}/conversation` | Agent with matching chat lease | No query parameters. | Bounded permission-filtered conversation history. |
| `GET /internal/v1/agent/jobs/{job_id}/monitor-baseline` | Agent with matching monitor lease | No query parameters. | Authorized prior evaluation metadata and coverage. |
| `POST /internal/v1/agent/jobs/{job_id}/model-reservations` | Agent with matching lease | Request UUID, configured model, input and output token ceilings. | Platform cost reservation, subject to the developer pilot and budget ceilings. |
| `POST /internal/v1/agent/jobs/{job_id}/model-reservations/{id}/settle` | Agent with matching lease | Provider-reported input and output token usage. | Settled reservation; uncertain calls retain their full reservation. |
| `POST /internal/v2/agent/jobs/{job_id}/complete` | Agent with a version 2 lease | Structured claims, evidence references, opportunities, and coverage. | Validated result, monitor evaluation, and deduplicated alerts. |

The user-facing pilot adds `GET /api/v1/agent-status`, conversation and job
listing, cited job-evidence reads, job cancellation, monitor pause/resume, and
monitor evaluation history. The LangGraph worker requests version 2 developer
jobs; existing version 1 external-agent clients retain their contract.

`AgentResult` contains answer text, status (`supported` or
`insufficient_evidence`), evidence references, alert records, and reported token
count. Supported answers require evidence references. Each alert has a ticker,
event ID, material version, direction, summary, and one or more evidence
references. Insufficient-evidence results cannot contain alerts.

## Local MCP tools

The five local stdio tools call Platform with the configured bearer token. They
accept the types shown here and return the corresponding Platform route data.

| Tool | Input data | Returned data |
|---|---|---|
| `get_stock_graph_context` | Ticker, optional fixed window, offset, limit, graph snapshot epoch. | `GraphContext`. |
| `get_professional_evidence` | Ticker, optional fixed window, offset, limit, graph snapshot epoch. | Professional-evidence page, subject to the bearer account's plan. |
| `search_stock_documents` | Ticker, optional query string, offset, limit. | Document-excerpt page with citation locators. |
| `get_stock_financial_history` | Ticker and optional fixed window. | `FinancialHistory`. |
| `get_document_version` | Document-version UUID string. | `DocumentVersion`, after Platform checks access to its stock. |
