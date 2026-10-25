# MarketGraph agents template

See [the scaffold system design and class diagram](../../docs/architecture/agents-template.md).

This independently installable package is a **scaffold**, not an implemented
agent service. It provides an abstract `Agent`, an abstract `PlatformClient`, an
empty read-only registry and a health-only runtime. Future research, discovery
and monitoring implementations belong in `src/marketgraph_agents/implementations/`.

```powershell
uv sync --all-packages --group dev --inexact
uv run --package marketgraph-agents marketgraph-agents
```

`GET http://localhost:8005/health` reports `execution_enabled: false` and
`registered_agents: 0`. No startup hooks contact Platform or claim work. There is
no worker-readiness endpoint because no executable handler exists.

For the optional Docker template:

```powershell
docker compose --profile agents-template up -d --build agents-template
```

Normal `docker compose up` excludes this service. The template binds only to
`127.0.0.1:8005`. Its health endpoint needs no database, model or broker credentials.

## Future implementation boundary

Set `AGENTS_PLATFORM_URL` and `AGENTS_PLATFORM_SERVICE_KEY` only when implementing
a real Platform client. The key authenticates future calls as `X-Agent-Key`;
claimed work provides its owner and a `lease_token`. Subsequent scoped context,
heartbeat, completion and failure requests also supply `X-Job-Lease`.

Platform remains authoritative for users, roles/plans, job scopes, evidence
eligibility, deduplicated alerts and persistent job state. Agents do not connect
to application databases, receive Upstox tokens, or choose an arbitrary user ID.
The existing separately hosted agents continue using the same leased REST
contract; creating this package does not replace them.

Execution methods are deliberately abstract/unimplemented. Do not add a polling
loop or register a handler until its behavior is specified. This release has no
model integration, scraping, scheduling, trading, Redis consumer or remote MCP
server. No agent is run by the health application.

```powershell
uv run --all-packages pytest services/agents/tests -q
```
