# Remote MCP gateway (AgenticOrg)

This implementation adds a **separate read-only Streamable HTTP MCP service** without modifying the graph, data, and platform API service boundaries.

## Docker Compose

1. Set a strong secret in your local untracked `.env`:

   ```env
   MCP_BEARER_TOKEN=replace-with-a-long-random-secret
   MCP_PORT=8003
   ```

2. Run `docker compose up -d --build graph-api graph-mcp`.

3. The MCP URL is `http://127.0.0.1:8003/mcp`. The MCP endpoint needs an actual MCP client, rather than just a browser GET request. A missing or incorrect `Authorization: Bearer <token>` header returns HTTP 401.

4. `graph-mcp` sends read-only GET requests to the existing `graph-api` service at `http://graph-api:8000`. It does not connect to FalkorDB itself.

The service binds to localhost by default. Setting `MCP_BIND_ADDRESS=0.0.0.0` publishes it on all host interfaces; do so only behind TLS and an appropriate ingress/authentication layer. The bearer token must be set or the MCP container refuses to boot. Other Compose services can run without that token.

## Render

Deploy an **additional** Docker web service from `services/stockgraph/Dockerfile.mcp`, using the repository root as build context.

Set these Render environment variables:

- `STOCKGRAPH_API_URL=https://<your-stockgraph-graph-api>.onrender.com` (not the SQL data API or FalkorDB)
- `MCP_BEARER_TOKEN=<strong secret>`
- `STOCKGRAPH_UPSTREAM_API_KEY` (optional, only if graph REST actually implements bearer authentication)
- `PORT` (Render supplies this automatically)

The MCP endpoint is `https://<your-mcp-service>.onrender.com/mcp`.

In AgenticOrg, register a custom connector with **MCP enabled**, the HTTPS URL, and a compatible bearer-token authentication setting. Confirm MCP tool discovery and execute a test call before using it.

## Tools and safeguards

The remote gateway exposes `get_stock_graph_context(ticker, window, offset, limit, as_of_ts)` only, with fixed `LAST_6M` / `LAST_1Y` windows and bounded pagination. The original local stdio MCP implementation remains unchanged. No trading, SQL, Cypher, database writes, or order execution is exposed.

**Note:** This token protects the gateway only. The upstream graph REST API must be secured separately before public production deployment.


## Separate Data MCP gateway

The Data service (Upstox/FastAPI on port 8001) has a separate MCP gateway. The Data MCP implementation is under `services/stockgraph/src/stockgraph/adapters/api/data_mcp.py` and uses the MCP SDK already installed in the stockgraph Python package; this is a proxy only, **not** direct database access or a dependency on the graph database.

For local Docker Compose:

```dotenv
DATA_MCP_BEARER_TOKEN=another-long-random-secret
DATA_MCP_PORT=8004
```

```sh
docker compose up -d --build data-api data-mcp
```

Use `http://127.0.0.1:8004/mcp` as the local endpoint.

For Render, create a **separate Docker Web Service** from repository root using `services/stockgraph/Dockerfile.data-mcp`, and set:

- `DATA_SERVICE_URL=https://data-api-public.onrender.com` (or the actual deployed Data API base URL)
- `MCP_BEARER_TOKEN=<another strong secret>`
- `DATA_UPSTREAM_API_KEY` only if the Data API actually supports that authentication mechanism
- `PORT` is supplied by Render

Its MCP endpoint is `https://<your-data-mcp-service>.onrender.com/mcp`.

Data MCP tools are `get_stock_financial_history`, `get_stock_profile` and `get_stock_candles`. All are read-only HTTP calls to existing Data API endpoints. Candle filters are `from_date` and `to_date` (ISO dates), matching the REST API's `from`/`to` parameters. Data-service provider credentials, SQL credentials, stock registration and trade execution are not exposed as MCP tools.

Register the **Graph MCP** and **Data MCP** as two AgenticOrg connectors, each with its own HTTPS URL and authentication secret. If AgenticOrg cannot supply a static bearer token for a custom remote MCP connector, its authentication configuration must be resolved before exposure; do not disable authentication.
