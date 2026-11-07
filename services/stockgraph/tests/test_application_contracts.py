"""Behavioral contracts for injected application dependencies."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from stockgraph.application.errors import BudgetExceeded, InferenceError
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.application.ingestion.handlers import ValidatingChat
from stockgraph.application.ingestion.pipeline import GraphPipeline
from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver
from stockgraph.application.processors.news_candidate_resolver import NewsCandidateResolver
from stockgraph.application.processors.news_correlator import NewsCorrelator
from stockgraph.application.processors.news_dedup import NewsDeduper
from stockgraph.application.processors.news_graph_extractor import NewsGraphExtractor
from stockgraph.application.processors.stock_profile_provider import StockProfileProvider
from stockgraph.domain.entities import NewsArticle
from stockgraph.domain.enums import NewsCategory, Window
from stockgraph.domain.schemas import StockContextCard


def test_dispatcher_routes_each_event_to_its_injected_handler():
    class Handler:
        def __init__(self):
            self.events = []

        def handle(self, event):
            self.events.append(event)

    registry, news = Handler(), Handler()
    pipeline = GraphPipeline(None, None, None, None, registry_handler=registry, news_handler=news)
    first = SimpleNamespace(kind="registry.updated")
    second = SimpleNamespace(kind="news.received")
    pipeline.process(first)
    pipeline.process(second)
    assert registry.events == [first]
    assert news.events == [second]


def test_profile_provider_uses_injected_guidance_without_graph_internals():
    class Profiles:
        def get_entity(self, kind, ticker):
            return {"ticker": ticker, "latest_guidance_highlights": ["fallback"]}

        def get_active_exposures(self, ticker):
            return ["BRENT_CRUDE"]

    class Guidance:
        def guidance_highlights(self, ticker):
            return ["New guidance"]

    result = StockProfileProvider(Profiles(), Guidance()).build_context_card("tcs")
    assert result.ticker == "TCS"
    assert result.latest_guidance_highlights == ["New guidance"]
    assert result.active_exposures == ["BRENT_CRUDE"]


def test_resolver_returns_snapshots_and_rejects_unregistered_provider_tickers():
    resolver = CanonicalEntityResolver.from_catalog({
        "Stock": [{"ticker": "TCS", "name": "Tata Consultancy"}],
    })
    snapshot = resolver.list_stocks()
    snapshot.append("UNKNOWN")
    article = NewsArticle(
        external_id="one", headline="Market update", summary="",
        source_url="https://example.test/news", source="RSS", published_at=datetime.now(UTC),
        category=NewsCategory.MACRO, tickers=("TCS.NS", "UNKNOWN"),
    )
    assert resolver.list_stocks() == ["TCS"]
    assert NewsCandidateResolver(resolver).resolve(article) == ["TCS"]


def test_news_inference_distinguishes_failure_from_empty_success():
    resolver = CanonicalEntityResolver.from_catalog({"Stock": [{"ticker": "TCS"}]})
    card = StockContextCard(ticker="TCS")

    class EmptyChat:
        def complete_json(self, prompt, schema):
            return schema()

    class FailedChat:
        def complete_json(self, prompt, schema):
            raise ConnectionError("provider unavailable")

    assert NewsGraphExtractor(EmptyChat(), resolver).infer("news", "Headline", "", [card]) == []
    with pytest.raises(InferenceError):
        NewsGraphExtractor(FailedChat(), resolver).infer("news", "Headline", "", [card])


def test_correlation_model_failure_is_not_an_empty_success():
    class Candidates:
        def find_correlation_candidates(self, *args, **kwargs):
            return [{"id": "prior", "category": "MACRO", "headline": "Earlier", "event_ts": 1}]

    class FailedChat:
        def complete_json(self, prompt, schema):
            raise ConnectionError("provider unavailable")

    with pytest.raises(InferenceError):
        NewsCorrelator(FailedChat()).correlate(Candidates(), "new", "Headline", "", 2, 2)


@pytest.mark.parametrize(
    ("embedding", "matched"),
    [([1.0, 0.0], True), ([0.0, 1.0], False), (None, False), ([float("nan"), 0.0], False)],
)
def test_semantic_dedup_rescores_candidates_without_a_graph_adapter(monkeypatch, embedding, matched):
    from stockgraph.runtime.settings import settings

    monkeypatch.setattr(settings, "dedup_cosine_threshold", 0.92)

    class NewsStore:
        def find_near_dup(self, query, ticker, now):
            return ({"id": "canonical", "source": "RSS", "embedding": embedding},)

    result = NewsDeduper(NewsStore()).find_semantic_duplicate([1.0, 0.0], "TCS", 100)
    assert (result is not None) is matched
    if matched:
        assert result == {"id": "canonical", "source": "RSS"}


def test_validating_chat_preserves_budget_failures_for_worker_reporting():
    class BlockedChat:
        def complete_json(self, prompt, schema, **kwargs):
            raise BudgetExceeded("budget unavailable")

    with pytest.raises(BudgetExceeded, match="budget unavailable"):
        ValidatingChat(BlockedChat()).complete_json("prompt", StockContextCard)


def test_professional_scope_requires_its_explicit_reader():
    class Graph:
        def get_entity(self, kind, ticker):
            return {"ticker": ticker}

        def context_page(self, *args):
            return {"ontology": [], "direct": [], "indirect": []}

    with pytest.raises(RuntimeError, match="reader is not configured"):
        GraphContextService(Graph()).get_context("TCS", Window.LAST_6M, include_professional=True)
