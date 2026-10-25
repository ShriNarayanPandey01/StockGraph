"""Graph service scope is trusted only after internal authentication."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.domain.enums import Window
from stockgraph.runtime.api import create_app
from stockgraph.runtime.settings import settings


class Repo:
    def get_entity(self, kind, ticker):
        return {"ticker": ticker}

    def context_page(self, *args):
        return {"ontology": [], "direct": [], "indirect": []}

    def professional_page(self, *args):
        raise AssertionError("Restricted professional query was executed")


def test_authentication_cannot_be_bypassed_by_evidence_or_developer_headers(monkeypatch):
    with TestClient(create_app(Repo(), object(), object())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/stocks/TCS/context", headers={"X-MarketGraph-Evidence-Scope": "professional"}).status_code == 401
        assert client.get("/api/v1/stocks/TCS/context", headers={"X-Internal-Service-Key": "wrong"}).status_code == 401
        headers = {"X-Internal-Service-Key": "test-internal-key"}
        response = client.get("/api/v1/stocks/TCS/context", headers=headers)
        assert response.status_code == 200
        assert response.json()["professional_evidence"] == []
        assert response.json()["evidence_policy"] == {}
        assert client.get("/api/v1/stocks/TCS/professional-evidence", headers=headers).status_code == 403
        monkeypatch.setattr(settings, "internal_service_key", SecretStr(""))
        assert client.get("/api/v1/stocks/TCS/context", headers=headers).status_code == 503


def test_ordinary_context_never_queries_or_counts_professional_records():
    result = GraphContextService(Repo()).get_context("TCS", Window.LAST_6M)
    assert result.professional_evidence == []
    assert result.pagination["has_more"]["professional_evidence"] is False
    assert result.evidence_policy == {}


async def test_local_mcp_sends_user_token_only_to_platform(monkeypatch):
    import stockgraph.adapters.api.mcp_server as module
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, path, params=None):
            calls.append((path, params))
            response = AsyncMock()
            response.raise_for_status = lambda: None
            response.json = lambda: {"items": []}
            return response

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    server = module.build_server("http://platform:8002", token="account-token")
    result = await server.call_tool("get_stock_graph_context", {"ticker": "TCS", "window": "LAST_6M"})
    assert not result.is_error
    assert calls[0]["base_url"] == "http://platform:8002"
    assert calls[0]["headers"] == {"Authorization": "Bearer account-token"}
    assert calls[1][0] == "/api/v1/stocks/TCS/connections"
    calls.clear()
    monkeypatch.delenv("MARKETGRAPH_PLATFORM_TOKEN", raising=False)
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="MARKETGRAPH_PLATFORM_TOKEN"):
        await module.build_server().call_tool("get_stock_graph_context", {"ticker": "TCS"})
    assert not calls
