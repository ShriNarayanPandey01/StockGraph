"""Read-only Streamable HTTP MCP gateway for the SQL-owned Data API.

This process uses HTTP exclusively; it does not access TimescaleDB or FalkorDB.
"""
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP
from stockgraph.adapters.api.remote_mcp import BearerProtectedApp

mcp = FastMCP("StockGraph Data", stateless_http=True, json_response=True)


def _ticker(ticker: str) -> str:
    if not ticker or len(ticker) > 50 or not all(c.isalnum() or c in "._-" for c in ticker):
        raise ValueError("Invalid ticker")
    return quote(ticker, safe="")


async def _get(path: str, params: dict | None = None) -> dict:
    base = os.environ["DATA_SERVICE_URL"].rstrip("/")
    headers = {}
    if os.getenv("DATA_UPSTREAM_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["DATA_UPSTREAM_API_KEY"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(base + path, params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def get_stock_financial_history(ticker: str, window: str = "LAST_6M") -> dict:
    """Read source-attributed stock financial history (LAST_6M or LAST_1Y)."""
    if window not in ("LAST_6M", "LAST_1Y"):
        raise ValueError("Unsupported window")
    return await _get(f"/api/v1/stocks/{_ticker(ticker)}/financials", {"window": window})


@mcp.tool()
async def get_stock_profile(ticker: str) -> dict:
    """Read a public company profile from the data-service stock catalog."""
    return await _get(f"/api/v1/stocks/{_ticker(ticker)}")


@mcp.tool()
async def get_stock_candles(ticker: str, limit: int = 50) -> dict:
    """Read up to 200 daily stock candles from the SQL-owned data service."""
    if not 1 <= limit <= 200:
        raise ValueError("Invalid limit")
    return await _get(f"/api/v1/stocks/{_ticker(ticker)}/candles", {"limit": limit})


def main() -> None:
    import uvicorn
    if not os.getenv("DATA_SERVICE_URL"):
        raise RuntimeError("DATA_SERVICE_URL must point to the Data REST API")
    app = BearerProtectedApp(mcp.streamable_http_app(), os.getenv("MCP_BEARER_TOKEN", ""))
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
