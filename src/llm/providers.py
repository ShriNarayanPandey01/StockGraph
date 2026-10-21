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

from pydantic import BaseModel

from src.config.settings import settings
from src.llm.base import (
    BudgetExceeded,
    CachedEmbeddingProvider,
    ChatProvider,
    OfflineGuardMixin,
    validate_structured_output,
)
from src.llm.tokens import count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)


class LiteLLMChatProvider(OfflineGuardMixin, ChatProvider):
    """Chat provider wrapping LiteLLM / OpenAI with budget checks and structured output."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self._require_enabled()
        # Head-truncate prompt to maximum tokens
        truncated_prompt = truncate_to_tokens(prompt, settings.llm_max_tokens_per_call)
        tokens_est = count_tokens(truncated_prompt)
        cost_est = (tokens_est / 1000.0) * settings.chat_price_per_1k

        self._check_budget(cost_est)

        try:
            import litellm  # lazy import
        except ImportError:
            raise RuntimeError("litellm is required for live LLM completions")

        response = litellm.completion(
            model=settings.llm_chat_model,
            messages=[{"role": "user", "content": truncated_prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        self._record_spend(cost_est)
        return validate_structured_output(content, schema)

    def _check_budget(self, estimated_cost_usd: float) -> None:
        if self._redis is None:
            return
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from src.llm.base import spend_key

        now = datetime.now(ZoneInfo(settings.app_timezone))
        key = spend_key(now.strftime("%Y-%m"))
        try:
            raw = self._redis.get(key)
        except Exception:
            return
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
        from src.llm.base import spend_key

        now = datetime.now(ZoneInfo(settings.app_timezone))
        key = spend_key(now.strftime("%Y-%m"))
        try:
            self._redis.incrbyfloat(key, cost_usd)
        except Exception:
            pass


class LiteLLMEmbeddingProvider(CachedEmbeddingProvider):
    """Embedding provider using LiteLLM with Redis cache and dimension checking."""

    def _fetch_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            import litellm
        except ImportError:
            raise RuntimeError("litellm is required for live embeddings")

        response = litellm.embedding(
            model=settings.embedding_model,
            input=texts,
        )
        return [item["embedding"] for item in response.data]
