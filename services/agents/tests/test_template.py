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
            "execution_enabled": False, "registered_agents": 3,
        }
        assert client.post("/jobs/claim").status_code == 404
    assert set(AGENTS) == {'chat', 'discovery', 'monitor'}


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


@pytest.mark.asyncio
async def test_configured_output_limit_is_reserved_and_sent_to_provider(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import litellm
    from marketgraph_agents.model import ReservedModel

    calls = {}

    class Client:
        async def reserve(self, job_id, lease, body):
            calls['reservation'] = body
            return {'id': 'reservation'}

        async def settle(self, *args):
            return {}

    async def completion(**kwargs):
        calls['provider'] = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='stop',
                     message=SimpleNamespace(content='{"answer":"No opportunity","status":"no_opportunity"}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

    monkeypatch.setattr(litellm, 'acompletion', completion)
    settings = Settings(_env_file=None, enabled=True, llm_enabled=True,
                        max_output_tokens=12000, usage_log_path=str(tmp_path / 'usage.jsonl'))
    result = await ReservedModel(settings, Client(), 'job', 'lease').complete('prompt')
    assert result.status == 'no_opportunity'
    assert calls['reservation']['output_tokens'] == 12000
    assert calls['provider']['max_tokens'] == 12000
