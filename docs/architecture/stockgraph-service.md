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
    EventConsumer --> Resolver
    EventConsumer --> Profile
    EventConsumer --> Ontology
    EventConsumer --> Extractor
    EventConsumer --> Deduper
    EventConsumer --> Correlator
    Ontology --> LLM
    Extractor --> LLM
    Correlator --> LLM
    EventConsumer --> Repo
    PlatformConsumer --> Repo
    Repo --> Graph
    EventConsumer <--> Redis
    PlatformConsumer <--> Redis
    DataClient --> Data[Data Service internal REST]
```

## OOP LLD class diagram

```mermaid
classDiagram
    class GraphContextService {
      +get_context(ticker, window, pagination, evidence_scope)
    }
    class PublicMarketGraphService {
      +get_preview(now_ts)
    }
    class EvidencePipeline {
      +process(event)
    }
    class GraphRepository {
      +get_entity(kind, entity_id)
      +context_page(ticker, window, pagination)
      +professional_page(ticker, window, pagination)
      +public_market_graph_data(start_ts, end_ts)
      +create_developer_edge(source, target, relation, metadata)
      +list_developer_edges(limit, offset)
      +update_developer_edge(edge_id, values)
      +delete_developer_edge(edge_id)
    }
    class FalkorGraphRAGRepository {
      +_run(cypher, params)
      +get_temporal_subgraph(ticker, window)
    }
    class PlatformConsumer {
      +run_once()
    }
    class EventConsumer {
      +run_once()
      +handle(message_id, fields)
    }
    class CanonicalEntityResolver {
      +resolve_stock(raw)
      +resolve_registry(raw)
    }
    class StockProfileProvider {
      +build_context_card(ticker) StockContextCard
    }
    class DynamicOntologyBuilder {
      +infer_edges(card) OntologyEdgeBatch
    }
    class NewsGraphExtractor {
      +extract(article, cards) NewsImpactBatch
    }
    class NewsDeduper {
      +check_l1_seen(source_url)
      +check_l2_text_dup(headline, ticker, now_ts)
      +semantic_link_or_create(article, embedding)
    }
    class NewsCorrelator {
      +correlate(event, candidates) NewsCorrelationBatch
    }
    class GraphNewsEligibilityReviewer {
      +review(request) NewsEligibilityVerdict
    }
    class DeveloperEdgeCreate {
      <<request DTO>>
      +source: DeveloperNodeRef
      +target: DeveloperNodeRef
      +relation: str
      +rationale: str
      +actor: str
      +confidence: float | None
      +metadata: dict
    }
    class DeveloperEdgeUpdate {
      <<request DTO>>
      +relation: str
      +rationale: str
      +actor: str
      +confidence: float | None
      +metadata: dict
    }
    class DeveloperEdgeAPI {
      <<internal REST routes>>
      +list_edges(limit, offset)
      +create_edge(input)
      +update_edge(edge_id, input)
      +delete_edge(edge_id)
    }
    class ChatProvider {
      <<abstract>>
      +complete_json(prompt, schema)
    }
    class EmbeddingProvider {
      <<abstract>>
      +embed(texts)
    }
    class DataServiceClient {
      +register_stock(request)
      +financials(ticker, window)
    }
    GraphRepository --|> FalkorGraphRAGRepository
    GraphContextService --> GraphRepository
    PublicMarketGraphService --> GraphRepository
    EvidencePipeline --> GraphRepository
    EventConsumer --> GraphRepository
    EventConsumer --> CanonicalEntityResolver
    EventConsumer --> StockProfileProvider
    EventConsumer --> DynamicOntologyBuilder
    EventConsumer --> NewsGraphExtractor
    EventConsumer --> NewsDeduper
    EventConsumer --> NewsCorrelator
    DynamicOntologyBuilder --> ChatProvider
    NewsGraphExtractor --> ChatProvider
    NewsCorrelator --> ChatProvider
    EventConsumer --> EmbeddingProvider
    PlatformConsumer --> EvidencePipeline
    GraphNewsEligibilityReviewer --> ChatProvider
    DeveloperEdgeAPI --> GraphRepository : graph-writer lease
    DeveloperEdgeAPI --> DeveloperEdgeCreate
    DeveloperEdgeAPI --> DeveloperEdgeUpdate
    GraphContextService --> GraphRepository : reads manual links by window
```

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
