# Platform system design

Package: `services/platform/` (`marketgraph-platform`), with separate `platform-api`
and `platform-worker` processes and its own ordinary PostgreSQL database
(`marketgraph_platform`) on the shared PostgreSQL server.

## Responsibilities and boundaries

Platform owns public accounts and sessions, combinable application roles,
Free/Pro plan policy, selected stocks, usage/quota accounting, professional
submission/review history, encrypted personal Upstox credentials, user-facing
REST authorization, job leases, evidence ledgers, outputs and alerts. Billing is
disabled; Pro is manually assigned by the developer. Platform never connects to
FalkorDB or TimescaleDB. It calls Data and StockGraph through service-key-protected
REST APIs. The worker relays transactional outbox records and schedules monitors;
it does not execute agent jobs.

### Components

```mermaid
flowchart TB
    Routes[REST routers\naccounts · admin · policy · connections · research]
    Auth[Bearer auth + Accounts\nArgon2id · OTP · SMTP]
    Entitlements[Entitlements + Access\nroles · Free/Pro · selections]
    Contributions[Repository\nversions · independent review · outbox]
    Broker[BrokerConnections + BrokerVault\nencrypted token handling]
    Jobs[agent_repository\nscoped jobs · lease · evidence · alert quota]
    Clients[CanonicalClient + scoped Data/Graph callers]
    Worker[Platform worker\noutbox relay · monitor scheduling]
    DB[(Ordinary PostgreSQL)]
    Redis[(Redis streams)]
    Data[Data Service REST]
    Graph[StockGraph REST]
    Agent[External agent service]
    Routes --> Auth
    Routes --> Entitlements
    Routes --> Contributions
    Routes --> Broker
    Routes --> Jobs
    Routes --> Clients
    Auth --> DB
    Entitlements --> DB
    Contributions --> DB
    Broker --> DB
    Jobs --> DB
    Worker --> DB
    Worker <--> Redis
    Contributions --> Redis
    Clients --> Data
    Clients --> Graph
    Agent -->|machine key + job lease| Routes
```

## OOP class diagram

```mermaid
classDiagram
    class Principal {
      +UUID id
      +roles: list
      +plan: FREE|PRO
      +is_developer: bool
      +professional_verified: bool
    }
    class Accounts {
      +signup(name, email, password)
      +request_code(email, purpose)
      +consume_code(email, purpose, code, password)
      +login(email, password)
      +change_password(user, current, next)
      +bootstrap_developer()
    }
    class Repository {
      +authenticate(token_digest)
      +create_contribution(user, input, idempotency_key)
      +review(contribution, reviewer, revision, decision)
      +published(ticker, limit, offset)
      +claim_outbox()
    }
    class Access {
      +user: Principal
      +policy: dict
      +tickers: tuple
      +allows(feature)
      +require(feature, tickers, single)
      +require_job(job)
    }
    class Entitlements {
      +access(user_id) Access
      +check(user, feature, tickers, single) Access
      +select(user, tickers)
      +usage(user)
    }
    class BrokerVault {
      -key: SecretStr
      +encrypt(owner, token) bytes
      +decrypt(owner, ciphertext) SecretStr
    }
    class BrokerConnections {
      +connect(user, token)
      +status(user_id)
      +disconnect(user_id)
      +headers_for(user_id)
      +read(user_id, path, params)
    }
    class CanonicalClient {
      +get(path, params, headers)
      +post_internal(path, payload, headers)
      +validate_ticker(ticker)
      +validate_citations(content)
    }
    class AgentRepositoryModule {
      <<module functions>>
      +create_job(owner, actor, request)
      +claim_job()
      +reserve_tool_call(job, lease)
      +register_evidence(job, lease, sources)
      +complete_job(job, lease, result)
    }
    class AgentWorkerContract {
      <<REST boundary>>
      +claim(X-Agent-Key)
      +context(X-Agent-Key, X-Job-Lease)
      +heartbeat(X-Agent-Key, X-Job-Lease)
      +complete(X-Agent-Key, X-Job-Lease)
    }
    class WorkerModule {
      <<module functions>>
      +relay_once()
      +run()
    }
    class Settings
    Accounts --> Repository
    Accounts --> Settings
    Entitlements --> Access
    Entitlements --> Repository
    BrokerConnections --> BrokerVault
    BrokerConnections --> CanonicalClient
    AgentRepositoryModule --> Entitlements : rechecks current policy
    AgentWorkerContract --> AgentRepositoryModule
    WorkerModule --> Repository
    WorkerModule --> Settings
```

## Key decisions and sequences

### Access evaluation

`current_user` validates an opaque session digest and operational request budget.
Feature routes load current user status, roles, plan policy and active-stock
selection from PostgreSQL. Free uses a ten-stock selection and ten newly created
alerts per Asia/Kolkata calendar month. Pro unlocks broader research/discovery and
professional intelligence. The developer identity comes only from environment
bootstrap and bypasses per-user ownership/plan/quota checks; privileged changes
are audited. Global provider, LLM and queue budgets still apply.

The same policy is rechecked when jobs are submitted, claimed, given evidence,
and completed. Professional records are kept in SQL with immutable versions,
review decisions, citations, validity and outbox events. Non-developer authors
require an independent reviewer; developer self-approval is permitted and logged.

### Broker connection

```mermaid
sequenceDiagram
    actor User
    participant P as Platform API
    participant V as BrokerVault
    participant DB as Platform PostgreSQL
    participant D as Data Service
    User->>P: PUT token (authenticated)
    P->>D: Validate token with bounded market-data request
    D-->>P: Connected / rejected / provider unavailable
    P->>V: Encrypt token with owner-bound authenticated encryption
    P->>DB: Store ciphertext and increment credential revision
    Note over P,D: On-demand data calls decrypt just in time and use credential-scoped client/cache
    P->>D: Market read + personal credential headers
    D-->>P: User-scoped market response
    P-->>User: Data/status; never the stored token
```

Scheduled ingestion never uses a personal user token. If a saved personal token
is rejected, the user must reconnect; Platform does not silently substitute the
shared environment credential. Disconnecting explicitly restores the shared
market-data fallback. Portfolio, holdings/funds endpoints and trading are excluded.

### External-agent job lifecycle

Platform stores canonical job scope, owner, initiating developer if applicable,
required plan, idempotency key, lease, evidence ledger, result and alerts. An agent
claims through `X-Agent-Key`; all subsequent calls require `X-Job-Lease`. Context
is assembled by Platform from graph and SQL services after access checks. Completion
validates current evidence/version/expiry, deduplicates alerts, applies monthly
quota transactionally, and stores citations with the output. A retry with the same
result is idempotent.

## Storage and migration

Migrations `001` through `004` are ordered and checksummed. Accounts and plan
policy live in ordinary PostgreSQL tables alongside contributions, job state,
audits, sessions, selection and encrypted credentials. Back up Platform data
before applying migrations. Restore tooling must include every migrated table.

SMTP-dependent public signup, verification and recovery return a retryable
configuration error until SMTP is set. Developer login is independent of SMTP.
