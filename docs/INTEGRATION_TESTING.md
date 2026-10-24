# Phase 1 end-to-end verification

This suite validates service integration separately from external provider
availability and model quality. RBAC, Pine Labs and live orders remain Phase 2.

## Test matrix

| Layer | Dependencies | Assertions |
|---|---|---|
| Offline regression | Python only | Input validation, ownership, free access, review rules, retry/correction policy, quotas and contracts |
| Live Data SQL | Local PostgreSQL/TimescaleDB | Transaction/outbox atomicity, immutable vintages, migrations, source documents, checkpoint attribution/recovery |
| Live Platform SQL | Disposable database/schemas | Publication/correction/retraction, concurrent claims, leases, source-backed completion, alert deduplication, usage |
| Live Graph | Disposable Falkor graphs | Native query syntax, atomic edge replacement, professional weighting/expiry/retraction, revision-safe guidance, vecf32 storage/search |
| Recovery | Isolated PostgreSQL schemas and local temporary objects | Binary COPY roundtrip, checksums, immutable history, cyclic foreign keys, sequences, existing-data protection |
| Cross-service E2E | Three real loopback HTTP APIs, real SQL/Redis/Falkor | Registration → outbox → graph; document/claim publication; agent research → canonical alert; corrections/retractions and ownership |
| Upstox smoke | Configured valid access token and internet | Read-only implemented market, historical, fundamentals, shareholding, options and analytics capabilities |
| Browser | Connections page and fixture graph | Pagination, professional filtering, mobile layout, safe source text, transient token handling |

The cross-service suite injects deterministic company/LLM/embedding adapters at
their external ports. Database drivers, application routes, HTTP connections,
SQL transactions, outbox relays, Redis Streams consumers and Falkor queries are
real. It validates plumbing and recovery, not paid-model quality or profitability.
The separate Upstox smoke test makes actual provider reads and does not write
provider results or submit orders.

## Preconditions and commands

Start the existing project after following the PGDATA migration precautions in
[Phase 1 operations](PHASE1_PLATFORM.md). The runner will not restart containers
or reset existing application data. Start a separate Redis for E2E work:

```powershell
docker run --detach --name stockgraph-e2e-redis-phase1 --publish 127.0.0.1:16380:6379 redis:7-alpine redis-server --appendonly yes --appendfsync always
uv sync --all-packages --group dev --inexact
.venv/Scripts/python.exe scripts/run_integration.py --live --e2e --upstox
```

If that test container already exists, start it with `docker start
stockgraph-e2e-redis-phase1`; do not recreate or remove unrelated containers.
The E2E test rejects the production Redis port and uses its own stream/graph
identities. The runner creates `platform_test_phase1_e2e` if absent. SQL test
schemas and Falkor graphs are generated and cleaned after testing. The empty
test database can be reused. No Redis FLUSH, project reset or volume deletion
is performed. Stop the dedicated test Redis afterward if it is no longer needed.

Reports are stored under `.cache/integration/<UTC timestamp>/report.json` and
`pytest.xml`. Reports contain statuses and counts, not tokens, account holdings,
provider response bodies or API secrets. Failed preconditions are failures,
not silently skipped live coverage.

For individual layers, enable `RUN_DATA_SQL_TESTS=1`, `RUN_GRAPH_LIVE_TESTS=1`,
or `PLATFORM_TEST_DATABASE_DSN` for the relevant tests. The combined runner sets
these explicitly; the ordinary offline command leaves live tests skipped.

## Upstox credentials and callback

Both `UPSTOX_ANALYTICS_TOKEN` and `UPSTOX_AUTHTOKEN` are accepted locally and in
Compose. A nonempty Analytics Token takes precedence. An API key/client secret
are OAuth app credentials, not bearer tokens. When an existing bearer token is
valid, the smoke test does not require a browser or callback.

The registered redirect URI is `https://127.0.0.1:5000/`. A future OAuth login
must use that exact scheme, address, port and trailing slash, and a listening
TLS callback. The current read-only Data Service does not implement an OAuth
callback server or silently renew a standard token.

Upstox documents the standard token expiry at 03:30 IST and the separate
read-only Analytics Token with one-year validity. Never infer the token type
from its environment variable name alone. [OAuth authentication](https://upstox.com/developer/api-documentation/authentication/),
[token expiry](https://upstox.com/developer/api-documentation/get-token/),
[Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/).
