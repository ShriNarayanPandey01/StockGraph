"""The template is importable but cannot accidentally process real work."""

import pytest
from fastapi.testclient import TestClient
from marketgraph_agents.agent import Agent
from marketgraph_agents.platform_client import PlatformClient
from marketgraph_agents.registry import AGENTS
from marketgraph_agents.runtime import create_app
from marketgraph_agents.settings import Settings


def test_health_reports_disabled_execution_without_credentials(monkeypatch):
    monkeypatch.delenv("AGENTS_PLATFORM_SERVICE_KEY", raising=False)
    assert Settings(_env_file=None).platform_service_key.get_secret_value() == ""
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {
            "status": "ok", "service": "marketgraph-agents",
            "execution_enabled": False, "registered_agents": 0,
        }
        assert client.post("/jobs/claim").status_code == 404
    assert dict(AGENTS) == {}


def test_execution_and_transport_remain_abstract():
    with pytest.raises(TypeError):
        Agent()
    with pytest.raises(TypeError):
        PlatformClient()
    with pytest.raises(TypeError):
        AGENTS["research"] = Agent


def test_configuration_rejects_credentials_in_platform_url():
    with pytest.raises(ValueError):
        Settings(_env_file=None, platform_url="https://secret:password@example.com")
