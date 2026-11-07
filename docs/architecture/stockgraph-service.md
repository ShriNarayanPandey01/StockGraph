# StockGraph system design

Package: `services/stockgraph/` (`stockgraph-service`), deployed processes:
`graph-api` and `graph-worker`. The local `stockgraph-mcp` executable uses stdio
and proxies user requests through Platform authentication.

## Responsibilities

StockGraph owns FalkorDB graph state, graph traversal, vector search and narrative
evidence processing. It accepts canonical change events, builds and versions
relationships, correlates news, and returns bounded context. Numeric financial
series remain Data-owned. Public graph-domain endpoints are protected by the
internal service key; Platform supplies professional-evidence access scope.

### Components

```mermaid
flowchart TB
    API[Graph FastAPI API]
    Context[GraphContextService]
    Preview[PublicMarketGraphService]
    Evidence[EvidencePipeline]
    Repo[GraphRepository]
    Resolver[CanonicalEntityResolver]
    Profile[StockProfileProvider]
    Ontology[DynamicOntologyBuilder]
    Extractor[NewsGraphExtractor]
    Deduper[NewsDeduper]
    Correlator[NewsCorrelator]
    DeveloperLinks[Developer edge routes\nlist · create · update · delete]
    PlatformConsumer[PlatformConsumer]
    EventConsumer[EventConsumer]
    Pipeline[GraphPipeline dispatcher]
    RegistryHandler[RegistryEventHandler]
    NewsHandler[NewsEventHandler]
    DataClient[DataServiceClient]
    LLM[Chat / embedding providers\nwith budget and cache]
    Graph[(FalkorDB graph + vector indexes)]
    Redis[(Redis streams + locks)]
    API --> Context
    API --> Preview
    API --> Evidence
    API --> DeveloperLinks
    API --> DataClient
    Context --> Repo
    Preview --> Repo
    Evidence --> Repo
    DeveloperLinks -->|writer lease| Repo
    EventConsumer --> Pipeline
    Pipeline --> RegistryHandler
    Pipeline --> NewsHandler
    RegistryHandler --> Resolver
    RegistryHandler --> Profile
    RegistryHandler --> Ontology
    NewsHandler --> Resolver
    NewsHandler --> Profile
    NewsHandler --> Extractor
    NewsHandler --> Deduper
    NewsHandler --> Correlator
    Ontology --> LLM
    Extractor --> LLM
    Correlator --> LLM
    RegistryHandler --> Repo
    NewsHandler --> Repo
    PlatformConsumer --> Repo
    Repo --> Graph
    EventConsumer <--> Redis
    PlatformConsumer <--> Redis
    DataClient --> Data[Data Service internal REST]
```

## Application class diagram

The application owns these structural protocols. The runtime constructs the
FalkorDB and model adapters and supplies them to the application. `GraphPipeline`
accepts injected handlers and otherwise creates its default handlers.

```mermaid
classDiagram
    class GraphPipeline {
      +process(event)
    }
    class RegistryEventHandler {
      +handle(event)
    }
    class NewsEventHandler {
      +handle(event)
      +route(news, resolver, chat)
    }
    class StockProfileProvider {
      +build_context_card(ticker) StockContextCard
    }
    class CanonicalEntityResolver {
      +resolve_stock(text)
      +resolve_registry(text)
      +list_stocks()
      +registry_catalog()
    }
    class DynamicOntologyBuilder {
      +infer_edges(card)
      +filter_edges(ticker, edges, time)
    }
    class NewsDeduper {
      +find_semantic_duplicate(embedding, ticker, time)
    }
    class NewsGraphExtractor {
      +infer(news, cards)
      +infer_market_impacts(news)
    }
    class NewsCorrelator {
      +correlate(repo, news)
    }
    class GraphContextService {
      +get_context(ticker, window, pagination)
    }
    class EvidencePipeline {
      +process(event)
    }
    class RegistryStore {
      <<Protocol>>
      +catalog()
      +project_entity()
      +rotate_dynamic_ontology_edges()
    }
    class NewsStore {
      <<Protocol>>
      +find_near_dup()
      +reconcile_news_impacts()
    }
    class StockProfileReader {
      <<Protocol>>
      +get_entity(kind, id)
      +get_active_exposures(ticker)
    }
    class GuidanceReader {
      <<Protocol>>
      +guidance_highlights(ticker)
    }
    class GraphContextReader {
      <<Protocol>>
      +context_page(ticker, start, end, offset, limit)
    }
    class ProfessionalEvidenceReader {
      <<Protocol>>
      +professional_page(ticker, start, end, offset, limit)
    }
    class EvidenceWriter {
      <<Protocol>>
      +project_professional(event, payload)
      +project_document(event)
    }
    class ChatModel {
      <<Protocol>>
      +complete_json(prompt, schema)
    }
    class EmbeddingModel {
      <<Protocol>>
      +embed_one(text)
    }
    class GraphRepository
    class EvidenceRepository
    class LiteLLMChatProvider
    class LiteLLMEmbeddingProvider

    GraphPipeline --> RegistryEventHandler
    GraphPipeline --> NewsEventHandler
    RegistryEventHandler --> RegistryStore
    RegistryEventHandler --> NewsEventHandler : historical replay
    RegistryEventHandler ..> StockProfileProvider
    RegistryEventHandler ..> DynamicOntologyBuilder
    RegistryEventHandler --> EmbeddingModel
    NewsEventHandler --> NewsStore
    NewsEventHandler ..> NewsDeduper
    NewsEventHandler ..> NewsGraphExtractor
    NewsEventHandler ..> NewsCorrelator
    StockProfileProvider --> StockProfileReader
    StockProfileProvider --> GuidanceReader
    DynamicOntologyBuilder --> CanonicalEntityResolver
    DynamicOntologyBuilder --> ChatModel
    NewsGraphExtractor --> CanonicalEntityResolver
    NewsGraphExtractor --> ChatModel
    NewsCorrelator --> ChatModel
    GraphContextService --> GraphContextReader
    GraphContextService --> ProfessionalEvidenceReader
    EvidencePipeline --> EvidenceWriter
    EvidencePipeline --> EmbeddingModel
    GraphRepository ..|> RegistryStore
    GraphRepository ..|> NewsStore
    GraphRepository ..|> StockProfileReader
    GraphRepository ..|> GraphContextReader
    EvidenceRepository ..|> GuidanceReader
    EvidenceRepository ..|> ProfessionalEvidenceReader
    EvidenceRepository ..|> EvidenceWriter
    LiteLLMChatProvider ..|> ChatModel
    LiteLLMEmbeddingProvider ..|> EmbeddingModel
```

The protocols describe structural contracts; adapters do not need to inherit
from them. Inference failures raise `InferenceError`, while an empty successful
model result remains an empty list. News-impact reconciliation is required of
the news store, so replacing a repository cannot silently switch to merge-only
writes.

## Projection and access flow

The event worker handles canonical SQL outbox events; the Platform stream worker
applies versioned, approved professional evidence. Graph writes are idempotent
and preserve version history. A Platform request sends either ordinary or
professional evidence scope. StockGraph filters professional graph results before
page limits and cache keys, and includes them only when the caller is entitled.

```mermaid
sequenceDiagram
    participant R as Redis stream
    participant W as EventConsumer
    participant P as StockProfileProvider
    participant L as LLM adapter
    participant G as GraphRepository
    participant F as FalkorDB
    R->>W: Canonical stock/news event
    W->>P: Load canonical profile and active context
    P->>G: Read profile, current exposure and financial context
    G->>F: Bounded graph query
    P-->>W: StockContextCard
    W->>L: Infer schema-constrained impacts/relationships
    L-->>W: Candidate edges with rationale/confidence
    W->>W: Resolve IDs and apply threshold/dedup rules
    W->>G: Idempotent versioned projection
    G->>F: MERGE nodes/edges and vector values
```

Numerical values requiring provenance are fetched from Data and retain their
provider timestamp. Graph traversals use fixed `LAST_6M` / `LAST_1Y` windows and
bounded pagination. Canonical catalog changes arrive through Data's event stream.
Developer-created links use the internal mutation API, validated node references,
and the graph-writer lease; updates retain link edit history and links appear in
stock context. Other provider, inferred and baseline edges remain owned by their
normal versioned projection flows.
