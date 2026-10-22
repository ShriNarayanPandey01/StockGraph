"""Graph-only MCP tool using the same bounded REST read contract."""

import httpx
from stockgraph.domain.enums import Window


def build_server(base_url: str = "http://localhost:8000"):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("StockGraph")

    @server.tool()
    async def get_stock_graph_context(
        ticker: str,
        window: Window = Window.LAST_6M,
        offset: int = 0,
        limit: int = 50,
        as_of_ts: int | None = None,
    ) -> dict:
        """Get paginated stock nodes, edges, direct/indirect news and processing status.

        Follow pagination.next_offset, passing the returned as_of_ts, until no more
        results remain. Numeric financial history belongs to the data service.
        """
        params = {"window": window.value, "offset": offset, "limit": limit}
        if as_of_ts is not None:
            params["as_of_ts"] = as_of_ts
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            response = await client.get(f"/api/v1/stocks/{ticker}/context", params=params)
            response.raise_for_status()
            return response.json()

    return server


def main() -> None:
    import os

    build_server(os.environ.get("STOCKGRAPH_API_URL", "http://localhost:8000")).run(
        transport="stdio"
    )


if __name__ == "__main__":
    main()
