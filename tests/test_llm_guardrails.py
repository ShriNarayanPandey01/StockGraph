"""LLM/embedding guardrails (Issue 1 mitigation). Fully offline, no network."""

import json

import pytest
from pydantic import BaseModel

from src.config.settings import settings
from src.llm.base import (
    BudgetExceeded,
    CachedEmbeddingProvider,
    LLMDisabled,
    embedding_cache_key,
    spend_key,
    validate_structured_output,
)
from src.llm.chunking import (
    GUIDANCE_CHUNK_TOKENS,
    GUIDANCE_OVERLAP_TOKENS,
    NEWS_CHUNK_TOKENS,
    chunk_guidance,
    chunk_news,
)
from src.llm.tokens import count_tokens, truncate_to_tokens


class _ToySchema(BaseModel):
    ticker: str
    confidence: float


class _StubEmbedder(CachedEmbeddingProvider):
    def __init__(self, redis_client=None):
        super().__init__(redis_client)
        self.calls = 0

    def _fetch_embeddings(self, texts):
        self.calls += 1
        dim = settings.embedding_dimension
        return [[float(len(t) % 7)] * dim for t in texts]


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def incrbyfloat(self, key, amount):
        total = float(self.store.get(key, 0.0)) + amount
        self.store[key] = str(total)
        return total


def test_llm_kill_switch_defaults_off():
    assert settings.llm_enabled is False
    with pytest.raises(LLMDisabled):
        _StubEmbedder().embed(["hello"])


def test_embedding_cache_key_is_model_scoped_and_normalized():
    a = embedding_cache_key("m", "RBI holds repo rate")
    b = embedding_cache_key("m", "  rbi HOLDS repo RATE ")
    assert a == b
    assert embedding_cache_key("m2", "RBI holds repo rate") != a


def test_spend_key_shape():
    assert spend_key("2026-10") == "llm:spend:2026-10"


def test_structured_output_validation_rejects_garbage():
    ok = validate_structured_output('{"ticker": "RELIANCE", "confidence": 0.9}', _ToySchema)
    assert ok.ticker == "RELIANCE"
    with pytest.raises(ValueError):
        validate_structured_output('{"ticker": "RELIANCE"}', _ToySchema)  # missing field
    with pytest.raises(ValueError):
        validate_structured_output("not json {{{", _ToySchema)


def test_embedding_dimension_mismatch_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "embedding_dimension", 1536)
    provider = _StubEmbedder()
    monkeypatch.setattr(provider, "_fetch_embeddings", lambda texts: [[1.0, 2.0]])
    with pytest.raises(ValueError, match="dim"):
        provider.embed(["x"])


def test_embedding_cache_avoids_refetch(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    fake = _FakeRedis()
    provider = _StubEmbedder(fake)
    first = provider.embed(["rbi holds rate", "tata steel results"])
    second = provider.embed(["rbi holds rate", "tata steel results"])
    assert first == second
    assert provider.calls == 1  # second batch fully served from cache
    key = embedding_cache_key(settings.embedding_model, "rbi holds rate")
    assert json.loads(fake.store[key])[0] == first[0][0]


def test_budget_hard_stop_enforced_with_ledger(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_monthly_usd_cap", 50.0)
    fake = _FakeRedis()
    provider = _StubEmbedder(fake)
    provider._check_budget(0.0)  # empty ledger → passes
    fake.store[provider._current_month_key()] = "49.99"
    provider._check_budget(0.0)  # 49.99 + 0.0 < 50 → passes
    with pytest.raises(BudgetExceeded):
        provider._check_budget(0.02)  # 49.99 + 0.02 >= 50 → hard-stop
    # Ledger write path accumulates actuals.
    total = provider._record_spend(1.5)
    assert total == pytest.approx(51.49)


def test_budget_fail_open_without_ledger(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    provider = _StubEmbedder(None)  # no Redis → no-op, never raises
    provider._check_budget(9999.0)
    assert provider._record_spend(1.0) == 0.0


def test_token_count_and_truncate():
    assert count_tokens("") == 0
    n = count_tokens("RBI holds repo rate steady")
    assert n > 0
    short = truncate_to_tokens("hello world", max_tokens=1000)
    assert short == "hello world"
    long_text = "word " * 5000
    cut = truncate_to_tokens(long_text, max_tokens=10)
    assert count_tokens(cut) <= 10


def test_chunking_spec_news_single_and_guidance_overlap():
    assert NEWS_CHUNK_TOKENS == 512
    assert GUIDANCE_CHUNK_TOKENS == 512
    assert GUIDANCE_OVERLAP_TOKENS == 50
    news = chunk_news("doc1", "RBI holds rate. " * 200)
    assert len(news) == 1  # news is truncate-only, never split
    assert news[0].id == "doc1#c0"
    assert news[0].tokens <= NEWS_CHUNK_TOKENS
    long_text = "guidance word " * 2000
    chunks = chunk_guidance("concall1", long_text)
    assert len(chunks) >= 2
    assert chunks[0].id == "concall1#c0"
    assert all(c.tokens <= GUIDANCE_CHUNK_TOKENS for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunk_guidance("empty", "") == []
