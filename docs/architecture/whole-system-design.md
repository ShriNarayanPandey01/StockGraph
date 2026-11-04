# Whole-project system design

## Runtime topology and ownership

Each backend package owns its domain and storage. Platform has its own logical
ordinary PostgreSQL database on the existing PostgreSQL server. TimescaleDB
continues to own market and source data; FalkorDB owns graph relationships and
vector indexes. Redis provides stream transport, leases, cache and coordination.

```mermaid
flowchart LR
    User[Browser or API client]
    LocalMCP[Local stdio stockgraph-mcp]
    ExternalAgent[Separately hosted agents]
    AgentWorker[LangGraph agent worker\nopt-in developer pilot]

    Platform[Platform API :8002\naccounts · RBAC · plans · jobs]
    PlatformWorker[Platform worker\noutbox · monitor scheduling]
    DataAPI[Data API :8001\nmarket reads · ingestion APIs]
    DataWorker[Data worker\nregistration · normalization]
    DataScheduler[Data scheduler\nnews and market cadences]
    GraphAPI[StockGraph API :8000\ncontext · graph administration]
    GraphWorker[StockGraph worker\nstream projection · evidence]

    PlatformDB[(marketgraph_platform\nordinary PostgreSQL)]
    MarketDB[(TimescaleDB\nmarket data · source records)]
    GraphDB[(FalkorDB\nontology · news · vectors)]
    Redis[(Redis\nstreams · leases · cache)]

    User -->|Bearer session| Platform
    LocalMCP -->|Platform REST with user token| Platform
    ExternalAgent -->|X-Agent-Key + X-Job-Lease| Platform
    AgentWorker -->|X-Agent-Key + X-Job-Lease| Platform
    Platform --> PlatformDB
    PlatformWorker --> PlatformDB
    PlatformWorker <--> Redis
    Platform -->|internal REST + service key| DataAPI
    Platform -->|internal REST + service key| GraphAPI
    DataAPI --> MarketDB
    DataAPI <--> Redis
    DataAPI -->|internal REST + service key| GraphAPI
    DataWorker --> MarketDB
    DataWorker <--> Redis
    DataScheduler --> MarketDB
    DataScheduler <--> Redis
    GraphAPI --> GraphDB
    GraphAPI <--> Redis
    GraphWorker --> GraphDB
    GraphWorker <--> Redis
    DataWorker -->|SQL outbox stream| Redis
    Redis -->|stockgraph:events:v1| GraphWorker
    PlatformWorker -->|professional outbox stream| Redis
    Redis -->|stockgraph:platform-events:v1| GraphWorker
    GraphAPI -->|on-demand market data| DataAPI
```

The agent worker is omitted from ordinary Compose startup. Its Platform calls
are scoped by a machine key and a per-job lease.

## Responsibility and data flow

| Service | Owns | Reads from | Writes to |
|---|---|---|---|
| Platform | Accounts, roles, plans, active stocks, quotas, contributions, sessions, broker credentials, jobs and alerts | Data and Graph internal APIs | Platform PostgreSQL, Redis streams |
| Data | Canonical SQL instrument registry, source payloads, market series, documents and ingestion runs | Upstox/exchange/news providers; Platform-scoped credential headers for on-demand data | TimescaleDB, Redis streams |
| StockGraph | Canonical graph projection, exposures, news impacts/correlations, professional graph evidence and vector indexes | Data API and both Redis streams | FalkorDB, Redis coordination |
| Agents worker | In-memory LangGraph job state | Leased Platform APIs and configured model provider | Validated Platform job results |

Numbers and source payloads stay in SQL. FalkorDB stores entities, relationships,
text evidence and vectors; graph numeric context is fetched from Data when needed.
Platform never connects to either database directly. The services communicate
through REST and versioned Redis events, not sibling imports.

## Main asynchronous flows

### Stock registration and graph projection

```mermaid
sequenceDiagram
    actor Client
    participant P as Platform API
    participant G as StockGraph API
    participant D as Data API
    participant SQL as TimescaleDB
    participant R as Redis Streams
    participant GW as StockGraph worker
    participant F as FalkorDB
    Client->>P: Register canonical stock (Bearer)
    P->>G: Registration request (service key)
    G->>D: Resolve/fetch source data (service key)
    D->>SQL: Commit source records + canonical revision + outbox
    D-->>G: Accepted job
    G-->>P: Accepted job ID
    D->>R: Publish outbox event, at least once
    R->>GW: stockgraph:events:v1
    GW->>F: Idempotent canonical graph projection
    Client->>P: Read registration status
    P->>G: Read job status (service key)
```

### Research and opportunity alerts

```mermaid
sequenceDiagram
    actor User
    participant P as Platform API
    participant DB as Platform PostgreSQL
    participant A as External agent service
    participant D as Data API
    participant G as StockGraph API
    User->>P: Submit research / discovery request
    P->>DB: Check current role, plan, stocks and idempotency
    P->>DB: Persist scoped job and conversation message
    A->>P: Claim job (X-Agent-Key)
    P-->>A: Owner, job scope and lease (X-Job-Lease)
    A->>P: Request context within ticker scope
    P->>G: Graph context with evidence-access scope
    P->>D: SQL financial context
    P->>DB: Revalidate policy and record supplied evidence
    P-->>A: Cited sources and material versions
    A->>P: Complete with cited result and alerts
    P->>DB: Revalidate lease/evidence; dedupe and allocate quota
    User->>P: Read authorized result / alerts
```

### Developer administration and graph changes

```mermaid
sequenceDiagram
    actor Developer
    participant P as Platform API
    participant DB as Platform PostgreSQL
    participant D as Data API
    participant SQL as TimescaleDB
    participant R as Redis Streams
    participant W as StockGraph worker
    participant G as StockGraph API
    participant F as FalkorDB
    Developer->>P: PATCH user roles, verification, plan or status
    P->>DB: Update account and append admin audit
    Developer->>P: PATCH canonical graph entity description
    P->>D: Internal catalog update with reason
    D->>SQL: Append entity version and outbox event in one transaction
    P->>DB: Audit the edited fields and returned revision
    D->>R: Publish registry.updated event
    R->>W: Deliver canonical change
    W->>F: Project node and version curated relationship changes
    Developer->>P: POST / PUT / DELETE developer graph link
    P->>G: Internal developer-scoped graph operation
    G->>F: Mutate DEVELOPER_LINK under graph-writer lease
    G-->>P: Updated link and retained edit history
    P->>DB: Append admin audit
```

Canonical catalog changes stay owned by Data and reach FalkorDB through the
outbox. Developer-created links use the protected StockGraph mutation API and
appear in paginated stock context. Public account requests cannot set developer
status; it belongs to the environment-managed Platform identity.

Authorization is checked again at job claim, context retrieval and completion.
Professional graph evidence is filtered by StockGraph before pagination; SQL
professional sources are queried only for a currently permitted job. Platform
stores results with a required plan so existing outputs follow current access.

## Trust and recovery boundaries

- Public requests authenticate at Platform. Direct market-data and graph domain
  routes require `MARKETGRAPH_INTERNAL_SERVICE_KEY`.
- External agents authenticate with a separate machine key and a per-job lease.
  They never receive bearer sessions, database credentials or Upstox tokens.
- Optional per-user Upstox tokens are encrypted at rest by Platform and forwarded
  only to Data for a user-scoped provider request. Shared ingestion uses the
  environment-owned provider credential. Trading is not enabled.
- Data source changes and Platform professional publication use transactional
  SQL outboxes. Consumers are idempotent because Redis delivery is at least once.
- Job lease, evidence and alert writes are transactional. Acknowledgment/retry
  does not duplicate alerts or charge the per-user monthly count twice.
- Redis provider/model budgets and global operational limits stay independent of
  a user's Free/Pro policy. Database backups and migrations are operational gates.

## Deferred pieces

Payments (provider undecided), live order execution, and remote HTTP MCP gateways
are not part of the deployed design. The agent implementation remains an opt-in pilot.
The existing local stdio MCP tools call Platform's authenticated REST APIs.
