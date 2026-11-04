from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr
from stockgraph.runtime.settings import settings


class Answer(BaseModel):
    value: str


def _settings(monkeypatch, provider="baseten"):
    values = {
        "llm_enabled": True,
        "llm_provider": provider,
        "llm_json_mode": "auto",
        "llm_chat_model": "meta-models/muse-spark-open-1026",
        "llm_ontology_model": "meta-models/muse-spark-open-1026",
        "llm_max_tokens_per_call": 4000,
        "llm_monthly_usd_cap": 50.0,
        "chat_price_per_1k": 0.00015,
        "embedding_price_per_1k": 0.00002,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 2,
        "baseten_api_key": SecretStr("baseten-secret"),
        "baseten_api_base": "https://inference.baseten.co/v1",
        "openai_api_key": SecretStr("openai-secret"),
        "anthropic_api_key": SecretStr("anthropic-secret"),
        "openrouter_api_key": SecretStr("openrouter-secret"),
        "llm_api_key": SecretStr("custom-secret"),
        "llm_api_base": "https://custom.example/v1",
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def _response(content='{"value":"ok"}', finish_reason="stop", refusal=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ]
    )


def _install_litellm(monkeypatch, *, completion=None, embedding=None):
    import sys

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=completion, embedding=embedding),
    )


def test_baseten_chat_uses_exact_model_endpoint_and_only_baseten_key(monkeypatch):
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response()

    _install_litellm(monkeypatch, completion=completion)
    result = LiteLLMChatProvider().complete_json("short prompt", Answer)

    assert result.value == "ok"
    assert calls[0]["model"] == "openai/meta-models/muse-spark-open-1026"
    assert calls[0]["api_base"] == "https://inference.baseten.co/v1"
    assert calls[0]["api_key"] == "baseten-secret"
    assert "openai-secret" not in repr(calls[0])
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON Schema:" in calls[0]["messages"][0]["content"]


@pytest.mark.parametrize(
    ("provider", "model", "expected_model", "expected_key"),
    [
        ("anthropic", "claude-3-5-haiku-latest", "anthropic/claude-3-5-haiku-latest", "anthropic-secret"),
        ("openrouter", "anthropic/claude-3.5-haiku", "openrouter/anthropic/claude-3.5-haiku", "openrouter-secret"),
        ("openai_compatible", "my-model", "openai/my-model", "custom-secret"),
    ],
)
def test_named_chat_providers_route_their_own_key(monkeypatch, provider, model, expected_model, expected_key):
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch, provider)
    monkeypatch.setattr(settings, "llm_chat_model", model)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response()

    _install_litellm(monkeypatch, completion=completion)
    LiteLLMChatProvider().complete_json("prompt", Answer)

    assert calls[0]["model"] == expected_model
    assert calls[0]["api_key"] == expected_key
    assert calls[0]["api_key"] != "openai-secret"
    if provider == "openai_compatible":
        assert calls[0]["api_base"] == "https://custom.example/v1"
    if provider == "anthropic":
        assert calls[0]["response_format"]["type"] == "json_schema"


def test_litellm_and_legacy_routes_preserve_model_string_behavior(monkeypatch):
    from stockgraph.adapters.llm.providers import _chat_route

    _settings(monkeypatch, "litellm")
    model, options, provider = _chat_route("gemini/gemini-2.5-flash")
    assert (model, provider) == ("gemini/gemini-2.5-flash", "litellm")
    assert options == {"api_key": "custom-secret", "api_base": "https://custom.example/v1"}

    monkeypatch.setattr(settings, "llm_provider", "legacy")
    model, options, provider = _chat_route("gpt-4o-mini")
    assert (model, provider) == ("gpt-4o-mini", "legacy")
    assert options == {"api_key": "openai-secret"}


def test_openai_chat_provider_uses_openai_key(monkeypatch):
    from stockgraph.adapters.llm.providers import _chat_route

    _settings(monkeypatch, "openai")
    model, options, provider = _chat_route("gpt-4o-mini")
    assert model == "gpt-4o-mini"
    assert provider == "openai"
    assert options == {"api_key": "openai-secret"}


def test_missing_provider_credentials_and_endpoint_fail_before_network(monkeypatch):
    from stockgraph.adapters.llm.providers import _chat_route

    _settings(monkeypatch, "baseten")
    monkeypatch.setattr(settings, "baseten_api_key", SecretStr(""))
    with pytest.raises(RuntimeError, match="BASETEN_API_KEY is required"):
        _chat_route("meta-models/muse-spark-open-1026")

    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_base", " ")
    with pytest.raises(RuntimeError, match="LLM_API_BASE is required"):
        _chat_route("model")

    monkeypatch.setattr(settings, "llm_api_base", "https://custom.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr(""))
    with pytest.raises(RuntimeError, match="LLM_API_KEY is required"):
        _chat_route("model")


def test_custom_endpoint_accepts_only_required_key_and_base(monkeypatch):
    from stockgraph.adapters.llm.providers import _chat_route

    _settings(monkeypatch, "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_base", "https://custom.example/v1/")
    _, options, _ = _chat_route("my-model")
    assert options == {"api_key": "custom-secret", "api_base": "https://custom.example/v1"}


def test_embeddings_keep_openai_model_and_credential_when_chat_uses_baseten(monkeypatch):
    from stockgraph.adapters.llm.providers import LiteLLMEmbeddingProvider

    _settings(monkeypatch, "baseten")
    calls = []

    def embedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [1.0, 0.0]}])

    _install_litellm(monkeypatch, embedding=embedding)
    assert LiteLLMEmbeddingProvider().embed_one("text") == [1.0, 0.0]
    assert calls == [
        {"model": "text-embedding-3-small", "input": ["text"], "api_key": "openai-secret"}
    ]


def test_gemini_embeddings_use_gemini_key_and_configured_dimension(monkeypatch):
    from stockgraph.adapters.llm.providers import LiteLLMEmbeddingProvider

    _settings(monkeypatch)
    monkeypatch.setattr(settings, "embedding_model", "gemini/gemini-embedding-2")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("gemini-secret"))
    calls = []

    def embedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [1.0, 0.0]}])

    _install_litellm(monkeypatch, embedding=embedding)
    assert LiteLLMEmbeddingProvider().embed_one("text") == [1.0, 0.0]
    assert calls == [{"model": "gemini/gemini-embedding-2", "input": ["text"],
                      "api_key": "gemini-secret", "dimensions": 2}]


@pytest.mark.parametrize(
    ("content", "finish_reason", "refusal"),
    [
        ("{truncated", "stop", None),
        ('{"other":"field"}', "stop", None),
        ('{"value":"ok"}', "length", None),
        ('{"value":"ok"}', "stop", "safety refusal"),
    ],
)
def test_incomplete_refused_malformed_and_invalid_responses_are_rejected(
    monkeypatch, content, finish_reason, refusal
):
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch)
    _install_litellm(
        monkeypatch,
        completion=lambda **kwargs: _response(content, finish_reason, refusal),
    )
    with pytest.raises(ValueError):
        LiteLLMChatProvider().complete_json("prompt", Answer)


def test_disabled_inference_does_not_make_provider_call(monkeypatch):
    from stockgraph.adapters.llm.base import LLMDisabled
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_enabled", False)
    called = []
    _install_litellm(monkeypatch, completion=lambda **kwargs: called.append(kwargs))
    with pytest.raises(LLMDisabled):
        LiteLLMChatProvider().complete_json("prompt", Answer)
    assert called == []


def test_monthly_budget_blocks_chat_before_provider_call(monkeypatch):
    from stockgraph.adapters.llm.base import BudgetExceeded
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch)
    called = []

    class Redis:
        def get(self, key):
            return "50"

    _install_litellm(monkeypatch, completion=lambda **kwargs: called.append(kwargs))
    with pytest.raises(BudgetExceeded):
        LiteLLMChatProvider(Redis()).complete_json("prompt", Answer)
    assert called == []


def test_schema_contract_survives_prompt_truncation(monkeypatch):
    import stockgraph.adapters.llm.providers as providers

    _settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_max_tokens_per_call", 800)
    monkeypatch.setattr(providers, "count_tokens", lambda text, model=None: len(text))
    monkeypatch.setattr(providers, "truncate_to_tokens", lambda text, count, model=None: text[:count])

    result = providers._prompt_with_schema("x" * 5000, Answer, "model")
    assert "JSON Schema:" in result
    assert '"title":"Answer"' in result
    assert len(result) <= 800


def test_provider_exception_does_not_expose_credentials_or_request(monkeypatch):
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider

    _settings(monkeypatch)

    def completion(**kwargs):
        raise RuntimeError("request failed with baseten-secret and private request body")

    _install_litellm(monkeypatch, completion=completion)
    with pytest.raises(RuntimeError) as error:
        LiteLLMChatProvider().complete_json("private request body", Answer)
    assert "baseten-secret" not in str(error.value)
    assert "private request body" not in str(error.value)
    assert "RuntimeError" in str(error.value)


def test_all_provider_secrets_are_hidden_from_settings_repr(monkeypatch):
    from stockgraph.runtime.settings import Settings

    secret = SecretStr("do-not-print-this")
    instance = Settings(
        _env_file=None,
        openai_api_key=secret,
        baseten_api_key=secret,
        anthropic_api_key=secret,
        openrouter_api_key=secret,
        llm_api_key=secret,
    )
    assert "do-not-print-this" not in repr(instance)
