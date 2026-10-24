"""Authenticated Streamable HTTP MCP gateway for StockGraph.

A dedicated MCP process proxies bounded read-only calls to the graph API.
"""
import hmac
import os
from urllib.parse import quote

import httpx
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("StockGraph")


@mcp.tool()
async def get_stock_graph_context(
    ticker: str,
    window: str = "LAST_6M",
    offset: int = 0,
    limit: int = 50,
    as_of_ts: int | None = None,
) -> dict:
    """Read graph nodes, edges, news and status for a registered stock."""
    if not ticker or len(ticker) > 50 or not all(c.isalnum() or c in "._-" for c in ticker):
        raise ValueError("Invalid ticker")
    if window not in ("LAST_6M", "LAST_1Y"):
        raise ValueError("Unsupported window")
    if offset < 0 or not 1 <= limit <= 200 or (as_of_ts is not None and as_of_ts < 0):
        raise ValueError("Invalid pagination")
    base = os.environ["STOCKGRAPH_API_URL"].rstrip("/")
    params = {"window": window, "offset": offset, "limit": limit}
    if as_of_ts is not None:
        params["as_of_ts"] = as_of_ts
    headers = {}
    if os.getenv("STOCKGRAPH_UPSTREAM_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["STOCKGRAPH_UPSTREAM_API_KEY"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        result = await client.get(
            f"{base}/api/v1/stocks/{quote(ticker, safe='')}/context", params=params
        )
        result.raise_for_status()
        return result.json()


class BearerProtectedApp:
    def __init__(self, app, token: str):
        if not token:
            raise RuntimeError("MCP_BEARER_TOKEN must be configured")
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            authorization = dict(scope.get("headers", [])).get(b"authorization", b"").decode("utf-8", "replace")
            if not hmac.compare_digest(authorization, "Bearer " + self.token):
                body = b'{"error":"Unauthorized"}'
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def main() -> None:
    import uvicorn
    if not os.getenv("STOCKGRAPH_API_URL"):
        raise RuntimeError("STOCKGRAPH_API_URL is required")
    app = BearerProtectedApp(
        mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0"), os.getenv("MCP_BEARER_TOKEN", "")
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
