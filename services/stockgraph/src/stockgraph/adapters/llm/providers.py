"""Concrete LLM and Embedding Providers (Issue 1 mitigation & Rule 7 extension).

All external LLM/embedding network calls are strictly encapsulated here.
Enforces:
1. Kill-switch (settings.llm_enabled=false -> raise LLMDisabled, safe offline/CI).
2. Redis embedding cache (emb:v1:{model}:{sha256}).
3. Monthly budget check and spend ledger (llm:spend:{yyyymm}).
4. Token truncation and structured-output validation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, SecretStr
from stockgraph.adapters.llm.base import (
    BudgetExceeded,
    CachedEmbeddingProvider,
    ChatProvider,
    OfflineGuardMixin,
    validate_structured_output,
)
from stockgraph.adapters.llm.tokens import count_tokens, truncate_to_tokens
from stockgraph.runtime.settings import settings

logger = logging.getLogger(__name__)


def _openai_credentials(key: SecretStr, model: str) -> dict[str, str]:
    # Do not send a dotenv OpenAI credential to an unrelated LiteLLM provider.
    is_openai = model.startswith(
        ("openai/", "gpt-", "chatgpt-", "o1", "o3", "o4", "text-embedding-")
    )
    return {"api_key": key.get_secret_value()} if is_openai and key.get_secret_value() else {}


def _secret_option(name: str, value: SecretStr, *, required: bool) -> dict[str, str]:
    secret = value.get_secret_value()
    if not secret:
        if required:
            raise RuntimeError(f"{name} is required for the selected LLM provider")
        return {}
    return {"api_key": secret}


def _model_with_prefix(model: str, prefix: str) -> str:
    return model if model.startswith(prefix) else f"{prefix}{model}"


def _chat_route(
    model: str, openai_api_key: SecretStr | None = None
) -> tuple[str, dict[str, str], str]:
    """Resolve the configured chat provider without sharing credentials."""
    provider = settings.llm_provider
    openai_api_key = openai_api_key or settings.openai_api_key
    if provider == "legacy":
        return model, _openai_credentials(openai_api_key, model), provider

    if provider == "baseten":
        options = _secret_option("BASETEN_API_KEY", settings.baseten_api_key, required=True)
        options["api_base"] = settings.baseten_api_base.rstrip("/")
        return _model_with_prefix(model, "openai/"), options, provider

    if provider == "openai":
        return model, _secret_option("OPENAI_API_KEY", openai_api_key, required=True), provider

    if provider == "anthropic":
        options = _secret_option("ANTHROPIC_API_KEY", settings.anthropic_api_key, required=True)
        return _model_with_prefix(model, "anthropic/"), options, provider

    if provider == "openrouter":
        options = _secret_option("OPENROUTER_API_KEY", settings.openrouter_api_key, required=True)
        return _model_with_prefix(model, "openrouter/"), options, provider

    if provider == "openai_compatible":
        if not settings.llm_api_base.strip():
            raise RuntimeError("LLM_API_BASE is required for the openai_compatible provider")
        options = _secret_option("LLM_API_KEY", settings.llm_api_key, required=True)
        options["api_base"] = settings.llm_api_base.rstrip("/")
        return _model_with_prefix(model, "openai/"), options, provider

    # In LiteLLM mode, model names include LiteLLM's provider prefix. The
    # generic key/base allow providers without a dedicated setting to be used.
    options = _secret_option("LLM_API_KEY", settings.llm_api_key, required=False)
    if settings.llm_api_base.strip():
        options["api_base"] = settings.llm_api_base.rstrip("/")
    return model, options, provider


def _response_format(provider: str, schema: type[BaseModel]) -> dict[str, Any] | None:
    mode = settings.llm_json_mode
    if mode == "auto":
        if provider == "anthropic":
            mode = "json_schema"
        elif provider == "litellm":
            # Model capabilities vary across the open-ended LiteLLM provider set.
            mode = "prompt"
        else:
            mode = "json_object"
    if mode == "prompt":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
            "strict": True,
        },
    }


def _prompt_with_schema(prompt: str, schema: type[BaseModel], model: str) -> str:
    """Keep the output contract at the end, where head truncation cannot drop it."""
    suffix = (
        "\n\nOutput contract: return exactly one JSON object matching this schema. "
        "Do not add Markdown fences or surrounding explanation.\n"
        "JSON Schema: "
        + json.dumps(schema.model_json_schema(), separators=(",", ":"), ensure_ascii=False)
    )
    limit = settings.llm_max_tokens_per_call
    available = limit - count_tokens(suffix, model)
    if available <= 0:
        raise ValueError("Output schema exceeds the configured LLM prompt budget")
    while available > 0:
        body = truncate_to_tokens(prompt, available, model)
        combined = body.rstrip() + suffix
        if count_tokens(combined, model) <= limit:
            return combined
        available -= 1
    raise ValueError("Output schema exceeds the configured LLM prompt budget")


class LiteLLMChatProvider(OfflineGuardMixin, ChatProvider):
    """Chat provider with environment-selected LiteLLM routing and validation."""

    def __init__(self, redis_client: Any | None = None, api_key: SecretStr | None = None) -> None:
        self._redis = redis_client
        self._api_key = api_key if api_key is not None else settings.openai_api_key

    def complete_json(
        self, prompt: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        self._require_enabled()
        configured_model = model or settings.llm_chat_model
        routed_model, provider_options, provider = _chat_route(configured_model, self._api_key)
        final_prompt = _prompt_with_schema(prompt, schema, routed_model)
        tokens_est = count_tokens(final_prompt, routed_model)
        cost_est = (tokens_est / 1000.0) * settings.chat_price_per_1k

        self._check_budget(cost_est)

        try:
            import litellm  # lazy import
        except ImportError:
            raise RuntimeError("litellm is required for live LLM completions")

        response_options: dict[str, Any] = {
            "model": routed_model,
            "messages": [{"role": "user", "content": final_prompt}],
            **provider_options,
        }
        response_format = _response_format(provider, schema)
        if response_format is not None:
            response_options["response_format"] = response_format
        try:
            response = litellm.completion(**response_options)
        except Exception as exc:
            # Provider exceptions can contain request details. Keep credentials
            # and request payloads out of worker logs while retaining the class.
            raise RuntimeError(
                f"LLM request failed for provider {provider} ({type(exc).__name__})"
            ) from None
        self._record_spend(cost_est)
        choices = getattr(response, "choices", None)
        if not choices:
            raise ValueError("LLM response contains no completion choices")
        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason not in {"stop", "end_turn", "completed", "stop_sequence"}:
            raise ValueError("LLM response is incomplete or did not finish normally")
        message = getattr(choice, "message", None)
        if message is None or getattr(message, "refusal", None):
            raise ValueError("LLM response was refused or contains no message")
        content = getattr(message, "content", None)
        if not isinstance(content, (str, dict)) or not content:
            raise ValueError("LLM response contains no structured content")
        return validate_structured_output(content, schema)

    def _check_budget(self, estimated_cost_usd: float) -> None:
        if self._redis is None:
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from stockgraph.adapters.llm.base import spend_key

        now = datetime.now(ZoneInfo(settings.app_timezone))
        key = spend_key(now.strftime("%Y-%m"))
        try:
            raw = self._redis.get(key)
        except Exception as exc:
            raise BudgetExceeded("LLM budget ledger is unavailable; inference is paused") from exc
        spent = float(raw) if raw is not None else 0.0
        if spent + estimated_cost_usd >= settings.llm_monthly_usd_cap:
            raise BudgetExceeded(
                f"Monthly LLM cap breached: spent ${spent:.2f} + "
                f"est ${estimated_cost_usd:.2f} >= cap ${settings.llm_monthly_usd_cap:.2f}"
            )

    def _record_spend(self, cost_usd: float) -> None:
        if self._redis is None or cost_usd <= 0:
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from stockgraph.adapters.llm.base import spend_key

        now = datetime.now(ZoneInfo(settings.app_timezone))
        key = spend_key(now.strftime("%Y-%m"))
        try:
            self._redis.incrbyfloat(key, cost_usd)
        except Exception:
            pass


class LiteLLMEmbeddingProvider(CachedEmbeddingProvider):
    """Embedding provider using LiteLLM with Redis cache and dimension checking."""

    def __init__(self, redis_client: Any | None = None, api_key: SecretStr | None = None) -> None:
        super().__init__(redis_client)
        self._api_key = api_key if api_key is not None else settings.openai_api_key

    def _fetch_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        estimated_cost = (
            sum(count_tokens(text, settings.embedding_model) for text in texts) / 1000.0
        )
        estimated_cost *= settings.embedding_price_per_1k
        self._check_budget(estimated_cost)
        try:
            import litellm
        except ImportError:
            raise RuntimeError("litellm is required for live embeddings")

        options = _openai_credentials(self._api_key, settings.embedding_model)
        if settings.embedding_model.startswith("gemini/"):
            options = _secret_option("GEMINI_API_KEY", settings.gemini_api_key, required=True)
            options["dimensions"] = settings.embedding_dimension
        response = litellm.embedding(
            model=settings.embedding_model,
            input=texts,
            **options,
        )
        self._record_spend(estimated_cost)
        return [item["embedding"] for item in response.data]
