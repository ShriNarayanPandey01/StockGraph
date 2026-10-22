# Upstox / Market Data Service

This independently installed service owns PostgreSQL/TimescaleDB. It does not
import StockGraph, FalkorDB, or an LLM SDK. Upstox credentials are encapsulated in
the read-only HTTP adapter and must be supplied through `UPSTOX_ANALYTICS_TOKEN`.

## Processes

- `upstox-api`: REST API on port 8001; durable registration requests only.
- `upstox-worker`: leased registration jobs and SQL-outbox publication.
- `upstox-scheduler`: durable hourly news cron (minute zero, Asia/Kolkata), plus
  weekday OPEN 09:30 and CLOSE 19:00 checkpoints with official Bhavcopy delivery.
- `upstox-bootstrap`: safe, empty-registry-only five-stock bootstrap.

Run locally with `uv run --package upstox-service upstox-api`, or use the root
Docker Compose stack. The worker and scheduler are separate processes from API.

## REST contract

`POST /api/v1/stocks` accepts `{"query":"TCS","exchange":"NSE"}` and optional
`strengths` / `business_exclusions` arrays. It returns HTTP 202 with `job_id`.
Poll `GET /api/v1/jobs/{job_id}` for `pending`, `data_collection`,
`graph_processing`, `completed`, or `failed`; warnings identify optional provider
endpoints that could not be collected. Ambiguous names fail rather than importing
an arbitrary instrument; use an exact ticker or ISIN.

`GET /api/v1/stocks/{ticker}/financials?window=LAST_6M|LAST_1Y` returns SQL numeric
checkpoints and the latest available full provider statements with provenance.
The statement payloads preserve provider reporting periods; they are not graph
entities. Values Upstox does not supply are not invented.

`GET /api/v1/entities` returns the SQL canonical catalog. Register or replace
commodities, macro factors, and sectors using `POST /api/v1/entities/{kind}`
(`Commodity`, `MacroFactor`, `Sector`). Macro descriptive versions change only
when their content changes. Numeric macro measurements belong in SQL ingestion,
not in this descriptive catalog API.

## OOP boundaries

`RegistrationWorker` depends on the `CompanyProvider` interface and a repository.
`UpstoxCompanyProvider` composes official instrument resolution, company profile,
statement reads, and completed daily checkpoints through `UpstoxClient`; the
client privately owns the masked token, retry policy, and transport.
`DataRepository` owns catalog/job transactions and the transactional outbox.
`RedisPublisher` handles transport only. API and scheduler modules are composition
roots; source adapters and application services do not depend on graph internals.

News adapters retain Marketaux, Currents, Alpha Vantage, and FMP provider support,
quotas, replayable raw staging and SQL watermarks. Raw news, normalized news,
watermark advancement and graph events commit together. Redis publication is
at-least-once, ordered by outbox sequence; consumers must deduplicate event IDs.

## Tests

`uv run pytest services/upstox/tests` runs offline tests. Set
`RUN_DATA_SQL_TESTS=1` to include the real SQL smoke test: it creates an isolated
schema inside an outer transaction and rolls everything back, without changing
application rows. See `migrations/README.md` for schema ownership.
