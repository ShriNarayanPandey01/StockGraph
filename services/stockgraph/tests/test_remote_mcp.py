"""Tests for the read-only remote MCP gateway."""

import pytest
from starlette.testclient import TestClient
from stockgraph.adapters.api import remote_mcp


def test_authentication_is_required():
    app = remote_mcp.BearerProtectedApp(remote_mcp.mcp.streamable_http_app(), "test-secret")
    with TestClient(app) as client:
        response = client.post("/mcp", json={})
        assert response.status_code == 401


def test_missing_token_rejected():
    with pytest.raises(RuntimeError):
        remote_mcp.BearerProtectedApp(remote_mcp.mcp.streamable_http_app(), "")


@pytest.mark.asyncio
async def test_read_only_graph_context(monkeypatch):
    monkeypatch.setenv("STOCKGRAPH_API_URL", "http://graph-api:8000")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"nodes": [], "edges": [], "pagination": {"has_more": False}}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(remote_mcp.httpx, "AsyncClient", FakeClient)
    output = await remote_mcp.get_stock_graph_context(
        "RELIANCE", window="LAST_1Y", offset=10, limit=20, as_of_ts=123
    )
    assert output["nodes"] == []
    assert captured["url"] == "http://graph-api:8000/api/v1/stocks/RELIANCE/context"
    assert captured["params"] == {
        "window": "LAST_1Y", "offset": 10, "limit": 20, "as_of_ts": 123
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"ticker": "../bad"},
    {"ticker": "RELIANCE", "window": "ALL_TIME"},
    {"ticker": "RELIANCE", "offset": -1},
    {"ticker": "RELIANCE", "limit": 201},
])
async def test_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        await remote_mcp.get_stock_graph_context(**kwargs)
