# StockGraph agents

This package contains LangGraph workflows for cited research, recent-event discovery, and watchlist/market monitoring. A separate worker claims developer-owned jobs through Platform REST. Graph, Data, and Platform remain the owners of their respective stores; the worker has no database or broker credential.

## Development and pilot

The worker is disabled by default. The pilot is restricted to the environment-managed developer account. It uses the configured chat provider/model (the root `.env.example` selects Meta's Muse Spark through Baseten) and defaults to low reasoning effort to leave output tokens for its validated structured answers. `AGENTS_LLM_CHAT_MODEL` and other `AGENTS_` settings can override the shared model configuration. Before enabling it, configure the chat provider/model, `LLM_ENABLED=true`, a shared machine key (`PLATFORM_AGENT_SERVICE_KEY` and local `AGENTS_PLATFORM_SERVICE_KEY`), and these Platform settings:

```dotenv
PLATFORM_AGENT_MODEL_ID=<same value as LLM_CHAT_MODEL>
PLATFORM_AGENT_INPUT_USD_PER_MILLION=<conservative input rate>
PLATFORM_AGENT_OUTPUT_USD_PER_MILLION=<conservative output rate>
PLATFORM_AGENT_MONTHLY_USD_CAP=10
PLATFORM_AGENT_JOB_USD_CAP=0.25
```

Rates are operator-supplied cost estimates, not verified invoices. Missing rates or an unavailable Platform ledger prevent model calls. Reservations survive worker crashes and remain charged until confirmed usage is settled. The separate Graph-service budget is unchanged.

See the [Meta model and AI usage guide](../../docs/AI_AND_MODEL_USAGE.md) for
the division between chat inference, embeddings and agent workflows.

`AGENTS_MAX_OUTPUT_TOKENS` sets the maximum generated tokens per model call and
the amount reserved for output. It defaults to 8192 and may be configured up to
32000, the Platform reservation API's current limit. A larger setting can make
reservations exceed the existing per-job budget; provider context length does
not itself establish an output limit. Input context has a separate size guard.

After starting the Platform, Data, Graph, and database services, set `AGENTS_ENABLED=true`. For local execution run:

```powershell
uv sync --all-packages --group dev --inexact
uv run --package marketgraph-agents stockgraph-agents-worker
```

For Compose, `docker compose --profile agents up -d --build agents-worker` starts the optional worker. It receives the same `PLATFORM_AGENT_SERVICE_KEY` as the Platform API and the configured chat-provider variables. The existing `agents-template` profile still provides a separate health-only API. Neither profile is enabled by ordinary Compose startup.

To include the worker in ordinary Compose startup, set `COMPOSE_PROFILES=agents`.
Set `AGENTS_RESTART_POLICY=unless-stopped` to restart an enabled worker after a
Docker restart; the default restart policy is `no`.

Each job attempt uses an in-memory LangGraph checkpointer. Platform stores conversation history, evidence, results, monitoring progress, budget reservations, and alerts. A lost worker or lease restarts the job attempt and may repeat model work within the original job ceiling. The worker stops work on a lost or unconfirmed lease and uses server-enforced evidence and budget validation.

Every physical model request is recorded as JSONL in `logs/agents/agent-model-usage.jsonl`. The log includes call/job/reservation IDs, provider and model, token limits, provider-reported token usage, request status and duration, reservation and settled cost estimates, and the configured rates. Each call has `call_started` and `call_finished` records so interrupted requests remain visible. Prompts, responses, credentials, and provider error messages are never written. Logs rotate at 10 MiB and retain five backups; Docker Compose mounts the directory from the host so it survives worker recreation. Cost values are Platform estimates based on configured rates, not provider invoices.

Research answers consist of cited claims. Discovery and monitoring examine canonical events from the last 72 hours, use confidence-qualified relationships and independent corroboration, and produce qualitative 2–30 session equity theses. Partial scans identify their coverage. Alerts are in-app and deduplicated against validated source revisions.

## Validation

`uv run --all-packages pytest -q services/agents/tests services/platform/tests` runs offline checks. The opt-in Platform integration suite requires `STOCKGRAPH_TEST_AGENT_DSN` pointing to a disposable local `agent_test` database on a non-default port; it creates and removes isolated schemas there. Live model evaluation remains opt-in and the 30-scenario developer precision gate must be met before broader rollout.

After a developer reviews at least 30 labelled scenarios, run `uv run python -m scripts.evaluate_agent_pilot <benchmark.json>`. The input format is described in the script; it reports the number of generated ideas and their reviewed precision. Passing fixtures with mocked model responses does not establish live-model precision.
