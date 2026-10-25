"""Local stdio tools use the authenticated Platform policy for every read."""

import os
from urllib.parse import quote
from uuid import UUID

import httpx
from stockgraph.domain.enums import Window


def build_server(base_url: str = "http://localhost:8002", token: str | None = None):
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer("StockGraph")

    async def read(path: str, params: dict | None = None):
        credential = token if token is not None else os.getenv("MARKETGRAPH_PLATFORM_TOKEN", "")
        if not credential:
            raise ToolError("MARKETGRAPH_PLATFORM_TOKEN is required for local MCP calls")
        async with httpx.AsyncClient(base_url=base_url, timeout=30,
                                     headers={"Authorization": "Bearer " + credential}) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def stock_path(ticker, suffix):
        return f"/api/v1/stocks/{quote(ticker.strip().upper(), safe='')}/{suffix}"

    def pagination(window, offset, limit, as_of_ts):
        params = {"window": window.value, "offset": offset, "limit": limit}
        if as_of_ts is not None:
            params["as_of_ts"] = as_of_ts
        return params

    @server.tool()
    async def get_stock_graph_context(ticker: str, window: Window = Window.LAST_6M,
                                      offset: int = 0, limit: int = 50,
                                      as_of_ts: int | None = None) -> dict:
        """Read permitted stock context; preserve the pagination snapshot across pages."""
        return await read(stock_path(ticker, "connections"), pagination(window, offset, limit, as_of_ts))

    @server.tool()
    async def get_professional_evidence(ticker: str, window: Window = Window.LAST_6M,
                                        offset: int = 0, limit: int = 50,
                                        as_of_ts: int | None = None) -> dict:
        """Read professional evidence if the account has the required permission."""
        return await read(stock_path(ticker, "professional-evidence"), pagination(window, offset, limit, as_of_ts))

    @server.tool()
    async def search_stock_documents(ticker: str, query: str = "", offset: int = 0,
                                     limit: int = 50) -> dict:
        """Read permitted committed document excerpts and their citation locators."""
        return await read(stock_path(ticker, "documents/search"), {"q": query, "offset": offset, "limit": limit})

    @server.tool()
    async def get_stock_financial_history(ticker: str, window: Window = Window.LAST_6M) -> dict:
        """Read permitted SQL-owned financial history through Platform."""
        return await read(f"/api/v1/market/stocks/{quote(ticker.strip().upper(), safe='')}/financials", {"window": window.value})

    @server.tool()
    async def get_document_version(version_id: str) -> dict:
        """Read an exact permitted document version."""
        return await read(f"/api/v1/documents/{UUID(version_id)}")

    return server


def main() -> None:
    build_server(os.getenv("MARKETGRAPH_PLATFORM_URL", "http://localhost:8002")).run(transport="stdio")


if __name__ == "__main__":
    main()
