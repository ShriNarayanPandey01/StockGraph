"""LLM + embedding provider abstraction (Issue 1 mitigation).

Rule 7 extension: NO vendor SDK import (openai/litellm/requests) is allowed
outside this package. All LLM/embedding traffic flows through
`EmbeddingProvider` / `ChatProvider`, which enforce:

1. Kill-switch (`settings.llm_enabled=false` → raise, CI-safe offline).
2. Redis embedding cache (`emb:v1:{model}:{sha256}`) — 5-10x spend saver.
3. Monthly USD budget (`llm:spend:{yyyymm}` GET pre-check + INCRBYFLOAT
   ledger; `BudgetExceeded` hard-stop at cap, fail-closed when Redis present,
   fail-open when Redis is absent e.g. unit tests).
4. Token counting/truncation (`stockgraph.adapters.llm.tokens`, tiktoken) — prompts and
   chunks are measured and head-truncated to `llm_max_tokens_per_call`
   before any network call.
5. Chunking spec (`stockgraph.adapters.llm.chunking`): news ≤512tok single-chunk;
   concall PDFs ≤512tok windows with 50tok overlap, deterministic ids.
6. Structured-output contract (callers pass a Pydantic model; raw text
   responses are rejected, never parsed with regex).

Splitting rationale (cost/quality): `llm_chat_model` (gpt-4o-mini) serves the
high-volume 30m news router; `llm_ontology_model` (gpt-4o) serves the
low-volume quarterly ontology refresh. Single-model setups are simpler but
lose on both axes — the split is settings-driven, so operators can collapse
it to one model with zero code change.

Current Milestone 1 scope: interfaces + offline-safe stubs (no network).
Concrete LiteLLM/OpenAI wiring lands in Milestone 4 alongside
`DynamicOntologyBuilder` / `NewsGraphExtractor` / `NewsCorrelator`.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError
from stockgraph.runtime.settings import settings

EMBEDDING_CACHE_PREFIX = "emb:v1"
SPEND_KEY_PREFIX = "llm:spend"


def embedding_cache_key(model: str, text: str) -> str:
    """Deterministic Redis key for an embedding (model-scoped, TTl-managed)."""
    digest = hashlib.sha256(text.strip().lower().encode()).hexdigest()
    return f"{EMBEDDING_CACHE_PREFIX}:{model}:{digest}"


def spend_key(year_month: str) -> str:
    """Monthly spend ledger key, e.g. `llm:spend:2026-10`."""
    return f"{SPEND_KEY_PREFIX}:{year_month}"


class BudgetExceeded(RuntimeError):
    """Raised when the monthly USD cap would be breached (fail-closed)."""


class LLMDisabled(RuntimeError):
    """Raised when providers are called with `llm_enabled=false` (offline/CI)."""


class EmbeddingProvider(ABC):
    """Embed texts → vectors of `settings.embedding_dimension`."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class ChatProvider(ABC):
    """Complete a prompt → validated Pydantic model (structured output only)."""

    @abstractmethod
    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...


def validate_structured_output(payload: str | dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    """Parse + validate an LLM JSON payload against a Pydantic schema.

    Raises `ValueError` on malformed JSON or schema violation — callers treat
    this as a retryable LLM error, never as a graph write.
    """
    data = json.loads(payload) if isinstance(payload, str) else payload
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"LLM output failed {schema.__name__} validation: {exc}") from exc


class OfflineGuardMixin:
    """Kill-switch guard shared by concrete providers (CI-safe default)."""

    def _require_enabled(self) -> None:
        if not settings.llm_enabled:
            raise LLMDisabled(
                "LLM calls are disabled (LLM_ENABLED=false). "
                "Set LLM_ENABLED=true with API keys for live inference."
            )


class CachedEmbeddingProvider(OfflineGuardMixin, EmbeddingProvider):
    """Abstract embedding provider with Redis cache + budget pre-check.

    Concrete subclasses implement `_fetch_embeddings()` (the only method that
    touches the network). Cache key includes the model name, so swapping
    `EMBEDDING_MODEL` never serves stale-dimension vectors.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._require_enabled()
        self._check_budget(0.0)  # pre-flight: refuse before spending when capped
        if not texts:
            return []
        cached: dict[int, list[float]] = {}
        missing: list[tuple[int, str]] = []
        for idx, text in enumerate(texts):
            hit = self._cache_get(embedding_cache_key(settings.embedding_model, text))
            if hit is not None:
                cached[idx] = hit
            else:
                missing.append((idx, text))
        fetched = self._fetch_embeddings([t for _, t in missing]) if missing else []
        for (idx, text), vec in zip(missing, fetched):
            self._assert_dimension(vec)
            self._cache_set(embedding_cache_key(settings.embedding_model, text), vec)
            cached[idx] = vec
        return [cached[i] for i in range(len(texts))]

    def _fetch_embeddings(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Concrete provider must implement network fetch")

    def _current_month_key(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(settings.app_timezone))
        return spend_key(now.strftime("%Y-%m"))

    def _check_budget(self, estimated_cost_usd: float) -> None:
        """Fail-closed pre-flight gate when a Redis ledger is present.

        Reads `llm:spend:{yyyymm}`; raises `BudgetExceeded` if
        spent + estimate >= cap. With no Redis (unit tests) this is a
        fail-open no-op — budget is enforced in prod wiring only.
        """
        if self._redis is None:
            return
        try:
            raw = self._redis.get(self._current_month_key())
        except Exception as exc:
            raise BudgetExceeded("LLM budget ledger is unavailable; inference is paused") from exc
        spent = float(raw) if raw is not None else 0.0
        if spent + estimated_cost_usd >= settings.llm_monthly_usd_cap:
            raise BudgetExceeded(
                f"Monthly LLM cap breached: spent ${spent:.2f} + "
                f"est ${estimated_cost_usd:.2f} >= cap ${settings.llm_monthly_usd_cap:.2f}"
            )

    def _record_spend(self, cost_usd: float) -> float:
        """Append actual spend to the monthly ledger; returns new total."""
        if self._redis is None or cost_usd <= 0:
            return 0.0
        return float(self._redis.incrbyfloat(self._current_month_key(), cost_usd))

    def _cache_get(self, key: str) -> list[float] | None:
        if self._redis is None:
            return None
        raw = self._redis.get(key)
        return json.loads(raw) if raw else None

    def _cache_set(self, key: str, vec: list[float]) -> None:
        if self._redis is None:
            return
        self._redis.setex(key, settings.llm_cache_ttl_days * 86400, json.dumps(vec))

    @staticmethod
    def _assert_dimension(vec: list[float]) -> None:
        if len(vec) != settings.embedding_dimension:
            raise ValueError(
                f"Embedding dim {len(vec)} != settings.embedding_dimension "
                f"{settings.embedding_dimension} (model {settings.embedding_model!r})"
            )
