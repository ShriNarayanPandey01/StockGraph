# MarketGraph architecture diagrams

These diagrams describe the implemented backend boundaries and the Phase 2
access model. They are intended to be read with [service boundaries](../04_SERVICE_BOUNDARIES.md)
and [Phase 2 operations](../PHASE2_PLATFORM.md). Mermaid diagrams render in
GitHub and most Markdown viewers that support Mermaid.

The whole-project document describes runtime topology, storage ownership,
trust boundaries and cross-service sequences. Each service document includes a
component design; the Agents document describes the opt-in LangGraph worker.

## Documents

- [Whole-project system design](whole-system-design.md): runtime topology, data
  ownership, trust boundaries and the main asynchronous flows.
- [Data Service design](data-service.md): Upstox/source adapters, SQL ownership,
  worker, scheduler and OOP LLD class diagram.
- [StockGraph design](stockgraph-service.md): FalkorDB, graph API/workers,
  evidence scoping, processors and OOP LLD class diagram.
- [Platform design](platform-service.md): accounts, RBAC, plans, broker vault,
  developer administration, researcher workflows and OOP LLD class diagram.
- [Agents design](agents-template.md): LangGraph workflows, leased tools, and
  Platform-owned budgets and evidence.

## Runtime status

Data, StockGraph and Platform are implemented services. `services/agents/` is
an opt-in developer pilot. Payments (provider undecided), remote MCP gateways,
and trading execution remain outside the current release.
