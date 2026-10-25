# MarketGraph architecture diagrams

These diagrams describe the implemented backend boundaries and the Phase 2
access model. They are intended to be read with [service boundaries](../04_SERVICE_BOUNDARIES.md)
and [Phase 2 operations](../PHASE2_PLATFORM.md). Mermaid diagrams render in
GitHub and most Markdown viewers that support Mermaid.

## Documents

- [Whole-project system design](whole-system-design.md): runtime topology, data
  ownership, trust boundaries and the main asynchronous flows.
- [Data Service design](data-service.md): Upstox/source adapters, SQL ownership,
  worker and scheduler, and the OOP class diagram.
- [StockGraph design](stockgraph-service.md): FalkorDB, graph API/workers,
  evidence scoping, processors and the OOP class diagram.
- [Platform design](platform-service.md): accounts, RBAC, plans, broker vault,
  researcher workflows, external-agent jobs and the OOP class diagram.
- [Agents template design](agents-template.md): deliberately empty runtime,
  extension interfaces and the OOP class diagram.

## Runtime status

Data, StockGraph and Platform are implemented services. `services/agents/` is a
health-only package scaffold: it does not execute agents, poll for jobs, or
connect to Platform. Payments (provider undecided), frontend, remote MCP
gateways and trading execution are outside the current release.
