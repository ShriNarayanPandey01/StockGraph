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
