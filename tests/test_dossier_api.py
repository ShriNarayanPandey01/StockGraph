"""Milestone 3: dossier REST API + MCP adapter (mock service, no live DB)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.mcp_server import build_tool_schema, call_tool
from src.domain.enums import Window
from src.domain.schemas import StockDossierResponse
from src.services.stock_context_service import UnknownTickerError


class FakeService:
    def __init__(self):
        self.calls: list[tuple] = []

    async def get_stock_dossier(self, ticker: str, window: Window):
        self.calls.append((ticker, window))
        if ticker == "NOPE":
            raise UnknownTickerError("Unknown ticker 'NOPE': not in registry")
        return StockDossierResponse(ticker=ticker, window=window, start_ts=1, end_ts=2)


def _client():
    app = create_app(falkor_repo=object(), timescale_repo=object())
    app.state.stock_context_service = FakeService()
    return TestClient(app)


def test_healthz():
    assert _client().get("/healthz").json() == {"status": "ok"}


def test_dossier_200_and_canonical_shape():
    r = _client().get("/api/v1/stocks/TATASTEEL/dossier", params={"window": "LAST_6M"})
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "TATASTEEL" and body["window"] == "LAST_6M"
    assert body["direct_news"] == [] and body["quant_summary"] is None


def test_dossier_404_unknown_ticker():
    r = _client().get("/api/v1/stocks/NOPE/dossier")
    assert r.status_code == 404


def test_dossier_422_bad_window():
    assert _client().get("/api/v1/stocks/TATASTEEL/dossier", params={"window": "ALL"}).status_code == 422


def test_mcp_tool_schema_and_call():
    schema = build_tool_schema()
    assert schema["name"] == "get_stock_dossier"
    assert "ticker" in schema["inputSchema"]["required"]
    import asyncio
    out = asyncio.run(call_tool(FakeService(), {"ticker": "infy", "window": "LAST_1Y"}))
    assert out["ticker"] == "infy" and out["window"] == "LAST_1Y"
    with pytest.raises(ValueError):
        asyncio.run(call_tool(FakeService(), {"ticker": "INFY", "window": "NOPE"}))
