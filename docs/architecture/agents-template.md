# Agents service template system design

Package: `services/agents/` (`marketgraph-agents`). This package is not an
executing agent service. Its opt-in `agents-template` Compose profile serves a
health endpoint on localhost port 8005 and reports `execution_enabled: false`
with an empty registry.

## Current system design

```mermaid
flowchart LR
    Probe[Health probe] --> Runtime[FastAPI runtime]
    Runtime --> Registry[Empty immutable registry]
    Registry --> Count[registered_agents = 0]
    NoJobs[No job polling or Platform calls]
```

Normal Compose startup excludes the template. The health application does not
need a database, Redis, LLM key, broker credential or Platform service key. There
is no scheduler, job-consumer loop, claim/heartbeat callback or concrete handler.

## OOP class diagram

```mermaid
classDiagram
    class Settings {
      +platform_url: str
      +platform_service_key: SecretStr
    }
    class Agent {
      <<abstract>>
      +run(job) dict
    }
    class PlatformClient {
      <<abstract>>
      +claim() dict
      +heartbeat(job_id, lease) dict
      +context(job_id, lease, ticker) dict
      +complete(job_id, lease, result) dict
      +fail(job_id, lease, retryable) dict
    }
    class RegistryModule {
      <<module; immutable Mapping>>
      +AGENTS: Mapping[str, type[Agent]]
    }
    class RuntimeFactory {
      <<module function>>
      +create_app()
    }
    RuntimeFactory --> RegistryModule : reports len(AGENTS)
    Agent ..> PlatformClient : future implementation dependency
```

## Future transport boundary

When real handlers are specified, the intended transport is Platform REST:
`X-Agent-Key` authenticates the machine and `X-Job-Lease` scopes each context,
heartbeat, completion and failure request. Platform remains authoritative for
account permissions, source selection, citations and alerts. Agents will not
connect directly to SQL/graph stores or receive user broker credentials. Existing
separately hosted agent deployments remain independent of this empty package.
