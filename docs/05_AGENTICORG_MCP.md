# AgenticOrg remote MCP deployment

The repository already has a **stdio** MCP tool at `stockgraph-mcp`. This adds a separate **Streamable HTTP** gateway; it does not replace the REST service or grant direct database access.

## Render setup

Create a **new Web Service** from the same GitHub repository and branch, using Docker with Dockerfile path `services/stockgraph/Dockerfile.mcp`.

Set environment variables (as Render secrets):

- `STOCKGRAPH_API_URL`: HTTPS base URL of the **StockGraph graph REST service** (not the Upstox Data Service, and not FalkorDB).
- `MCP_BEARER_TOKEN`: a long random secret shared only with AgenticOrg.
- `STOCKGRAPH_UPSTREAM_API_KEY` (optional): if the graph REST API supports bearer authentication, its credential.

Render supplies `PORT`; the gateway listens on `0.0.0.0:$PORT`.

Once deployed, register `https://YOUR-MCP-RENDER-SERVICE.onrender.com/mcp` in AgenticOrg as a remote MCP connector with bearer-token authentication (if supported by the AgenticOrg connector form). Confirm the discovered `get_stock_graph_context` tool is read-only.

**Security:** The gateway requires a bearer token on every HTTP request. It does **not** secure the existing StockGraph REST service; secure that independently before production use. Never place tokens in a connector's agent prompt or in the repository. The gateway does not expose graph mutations, arbitrary Cypher/SQL, messaging, or orders.

## Validation

1. Without a token, an HTTP request to `/mcp` should return `401`.
2. With a valid token, an MCP client should initialize, list tools and find `get_stock_graph_context`.
3. Call the tool with a registered ticker and verify that it returns a bounded graph response.
4. Verify invalid windows and pagination values are rejected.

The MCP protocol uses POST and negotiation headers; visiting `/mcp` in a browser is **not** a sufficient functional test.
