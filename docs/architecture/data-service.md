# Data Service system design

Package: `services/upstox/` (`upstox-service`), deployed processes: `data-api`,
`data-worker`, and `data-scheduler`.

## Responsibilities

Data is the owner of normalized market/source information and canonical SQL
identities. It stores source payloads and market series in TimescaleDB, publishes
canonical changes through a transactional outbox, and serves bounded REST reads.
It does not own user accounts, plan decisions, graph relationships, embeddings or
trade orders. User-facing access goes through Platform; internal routes require
the shared service credential.

### Components

```mermaid
flowchart TB
    API[FastAPI routes\nmarket · stocks · documents · internal credential validation]
    App[Application services\nStockDataService · RegistrationWorker · ingestion]
    Resolver[CanonicalEntityResolver]
    Repo[Timescale repositories\ncatalog · stock data · documents]
    Provider[Provider adapters\nUpstox · news · exchange Bhavcopy]
    Scoped[ScopedMarketProvider\nper-user request credential]
    Publisher[RedisPublisher / SQL outbox]
    SQL[(TimescaleDB)]
    Redis[(Redis)]
    API --> App
    API --> Scoped
    App --> Resolver
    App --> Provider
    App --> Repo
    Scoped --> Provider
    Repo --> SQL
    App --> Publisher
    Publisher --> SQL
    Publisher --> Redis
    Worker[Worker process] --> App
    Scheduler[Persistent scheduler process] --> App
```

The scheduled worker and API are separate processes. The scheduler owns durable
cadence and single-flight dispatch; the worker performs registration and ingestion.
Provider HTTP credentials and retry/timeout behavior stay inside provider adapters.

## OOP class diagram

```mermaid
classDiagram
    class Settings
    class StockDataService {
      +list_stocks(query, cursor, limit)
      +stock(ticker, exchange)
      +shareholding(ticker, exchange)
      +get_candles(ticker, start, end)
    }
    class RegistrationWorker {
      +run_once()
    }
    class CompanyProvider {
      <<Protocol>>
      +resolve(query, exchange)
      +fetch_company(request) CompanyBundle
    }
    class UpstoxCompanyProvider {
      +resolve(query, exchange)
      +fetch_company(request) CompanyBundle
    }
    class UpstoxClient {
      -token: SecretStr
      +get(path, params)
      +close()
    }
    class UpstoxMarketProvider {
      +resolve_underlying(query, exchange)
      +option_chain(underlying, expiry)
      +smartlist(kind, exchange)
      +derivatives_analytics(kind, query)
    }
    class UpstoxStockDataProvider {
      +resolve(ticker, exchange)
      +fetch_profile(isin)
      +fetch_shareholding(isin)
      +fetch_daily_candles(instrument, range)
    }
    class ScopedMarketProvider {
      +__getattr__(name)
    }
    class CredentialContext {
      +scope: str
      +stock_provider: UpstoxStockDataProvider
      +market_provider: UpstoxMarketProvider
    }
    class CanonicalEntityResolver {
      +resolve_stock(raw, exchange)
      +resolve_registry(raw)
    }
    class DataRepository {
      +create_job(request)
      +commit_company(job, bundle)
      +claim_outbox()
      +publish_outbox(publisher)
    }
    class StockDataRepository {
      +search_instruments(query, cursor, limit)
      +get_profile(isin)
      +get_shareholding(isin)
      +get_candles(ticker, start, end)
    }
    class RedisPublisher {
      +publish(event)
    }
    class NewsFetchService {
      +fetch_cycle()
    }
    class NewsProviderAdapter {
      <<abstract>>
      +fetch(query) ProviderFetchResult
    }
    class PersistentSchedule {
      <<AsyncIOScheduler subclass>>
      +start()
      +shutdown()
    }
    RegistrationWorker --> CompanyProvider : injected port
    UpstoxCompanyProvider ..|> CompanyProvider
    UpstoxCompanyProvider --> UpstoxClient
    UpstoxMarketProvider --> UpstoxClient
    UpstoxStockDataProvider --> UpstoxClient
    ScopedMarketProvider --> CredentialContext
    ScopedMarketProvider --> UpstoxMarketProvider : delegates selected context
    RegistrationWorker --> DataRepository
    RegistrationWorker --> CanonicalEntityResolver
    StockDataService --> StockDataRepository
    DataRepository --> RedisPublisher : transactional outbox relay
    NewsFetchService --> NewsProviderAdapter
    PersistentSchedule --> NewsFetchService
```

## Storage and flow

- `vendor_quotes_raw`, `news_raw`, documents and provider responses are retained
  before normalization or graph inference.
- Numeric series, canonical SQL catalog and registration/ingestion jobs remain
  Data-owned. Daily stock candle reads do not become graph nodes.
- Source adapters normalize identifiers through the canonical resolver; unresolved
  stock IDs are rejected instead of inventing new canonical identities.
- A registration transaction commits SQL records and its outbox row together.
  The separate worker relays outbox records to Redis for StockGraph projection.
- Personal market-data requests use an ephemeral `CredentialContext`; they are
  never used for scheduled/shared ingestion or written into shared historical data.

## Operational entrypoints

`upstox-api` serves REST; `upstox-worker` processes durable registration/outbox
work; `upstox-scheduler` runs persistent cadences. Health/readiness endpoints are
operational and do not bypass the internal-key requirement for domain routes.
