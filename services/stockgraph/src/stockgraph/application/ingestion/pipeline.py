"""Committed-event graph processing: no provider calls and no relational repository."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from stockgraph.adapters.llm.base import LLMDisabled
from stockgraph.application.processors.batching import card_batches
from stockgraph.application.processors.dynamic_ontology_builder import DynamicOntologyBuilder
from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver
from stockgraph.application.processors.news_candidate_resolver import NewsCandidateResolver
from stockgraph.application.processors.news_correlator import NewsCorrelator
from stockgraph.application.processors.news_dedup import (
    NewsDeduper,
    build_news_props,
    canonicalize_url,
    url_seen_key,
)
from stockgraph.application.processors.news_eligibility import (
    GraphNewsEligibilityReviewer,
    NewsEligibilityRequest,
    hard_rejection_reason,
    is_approved_event,
)
from stockgraph.application.processors.news_graph_extractor import NewsGraphExtractor
from stockgraph.application.processors.stock_profile_provider import StockProfileProvider
from stockgraph.domain.entities import NewsArticle
from stockgraph.domain.enums import NewsCategory
from stockgraph.domain.events import CommittedEvent
from stockgraph.runtime.settings import settings


class CheckedChat:
    """Make swallowed legacy inference errors observable to the event worker."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._error: Exception | None = None

    def complete_json(self, prompt: str, schema: Any, **kwargs: Any) -> Any:
        try:
            result = self._provider.complete_json(prompt, schema, **kwargs)
            if isinstance(result, dict):
                result = schema.model_validate(result)
            if not isinstance(result, schema):
                raise ValueError("LLM provider did not return the requested structured schema")
            return result
        except Exception as exc:
            self._error = exc
            raise

    def require_success(self) -> None:
        if self._error is not None:
            raise RuntimeError("LLM inference failed; event remains retryable") from self._error


class GraphPipeline:
    def __init__(self, repo: Any, redis: Any, chat: Any, embedder: Any) -> None:
        self._repo, self._redis = repo, redis
        self._chat, self._embedder = chat, embedder

    def process(self, event: CommittedEvent) -> None:
        if event.kind == "registry.updated":
            self._registry(event)
        else:
            self._news(event)

    def _require_inference(self) -> None:
        if not settings.llm_enabled:
            raise LLMDisabled(
                "LLM_ENABLED=false: projection is pending semantic inference, not completed"
            )

    def _registry(self, event: CommittedEvent) -> None:
        kind, entity = event.payload["kind"], event.payload["entity"]
        if kind not in ("Stock", "Commodity", "MacroFactor", "Sector"):
            raise ValueError("Unknown registry kind")
        identity = entity.get("ticker" if kind == "Stock" else "id")
        if identity != event.entity_id:
            raise ValueError("Registry identity does not match committed event identity")
        existing = self._repo.get_entity(kind, event.entity_id)
        if existing and (
            existing.get("revision", 0) > event.revision
            or existing.get("inference_revision", 0) >= event.revision
        ):
            return
        self._repo.project_entity(
            kind, event.entity_id, entity, event.revision, int(event.occurred_at.timestamp())
        )
        self._require_inference()
        resolver = CanonicalEntityResolver.from_catalog(self._repo.catalog())
        chat = CheckedChat(self._chat)
        profiles = StockProfileProvider(self._repo)
        # New market entities can affect any existing stock, not just newly added stocks.
        tickers = [event.entity_id] if kind == "Stock" else resolver.list_stocks()
        builder = DynamicOntologyBuilder(chat, resolver, model=settings.llm_ontology_model)
        for ticker in tickers:
            card = profiles.build_context_card(ticker)
            self._repo.merge_stock_profile_embedding(
                ticker, self._embedder.embed_one(card.model_dump_json())
            )
            edges = builder.infer_edges(card, now_ts=int(event.occurred_at.timestamp()))
            chat.require_success()
            self._repo.rotate_dynamic_ontology_edges(
                ticker, edges, int(event.occurred_at.timestamp())
            )
            builder.persist(
                self._repo, [edge for edge in edges if edge.relation.value == "RELATED_TO"]
            )
        # Replay canonical graph news without L1/L2 or refetching metered providers.
        offset, cutoff = 0, int(time.time()) - 365 * 86400
        while True:
            rows = self._repo.historical_news(cutoff, offset=offset, limit=100)
            for news in rows:
                self._route(news, resolver, chat, only_tickers=tickers)
            if len(rows) < 100:
                break
            offset += len(rows)
        chat.require_success()
        self._repo.mark_entity_processed(kind, event.entity_id, event.revision)

    def _news(self, event: CommittedEvent) -> None:
        revision_key = f"stockgraph:news-source:{event.entity_id}"
        observed = self._redis.hget(revision_key, "revision")
        if observed is not None and int(observed) > event.revision:
            return
        completed = self._redis.hget(revision_key, "completed_revision")
        if completed is not None and int(completed) >= event.revision:
            return
        raw = dict(event.payload)
        # The event contract is an additional boundary, not a substitute for
        # source-side filtering. A malformed or old stream entry must never
        # create a :NewsEvent just because it reached Redis.
        if hard_rejection_reason(str(raw.get("headline") or ""), str(raw.get("summary") or "")):
            self._mark_news_skipped(revision_key, event, "hard_reject")
            return
        if not is_approved_event(raw):
            try:
                preliminary = NewsCategory(str(raw.get("category") or "OTHER"))
            except ValueError:
                preliminary = NewsCategory.OTHER
            verdict = GraphNewsEligibilityReviewer(self._chat).review(
                NewsEligibilityRequest(
                    headline=str(raw.get("headline") or ""),
                    summary=str(raw.get("summary") or ""),
                    candidate_tickers=list(raw.get("tickers") or ()),
                    preliminary_category=preliminary,
                )
            )
            if not verdict.eligible or verdict.category is None:
                self._mark_news_skipped(revision_key, event, "legacy_reject")
                return
            raw["category"] = verdict.category.value
        self._require_inference()
        raw["published_at"] = datetime.fromisoformat(raw["published_at"].replace("Z", "+00:00"))
        raw["category"] = NewsCategory(raw.get("category", "OTHER"))
        raw["tickers"] = tuple(raw.get("tickers", []))
        article = NewsArticle(
            **{k: v for k, v in raw.items() if k in NewsArticle.__dataclass_fields__}
        )
        self._redis.hset(revision_key, mapping={"revision": str(event.revision)})
        resolver = CanonicalEntityResolver.from_catalog(self._repo.catalog())
        props = build_news_props(article, NewsCandidateResolver(resolver).primary_entity(article))
        # A retry owns its L1 reservation; it must continue routing after a partial write.
        if article.source_url:
            key = url_seen_key(canonicalize_url(article.source_url))
            owner = self._redis.get(key)
            if isinstance(owner, bytes):
                owner = owner.decode()
            source_owner = f"source:{event.entity_id}"
            if owner and owner != source_owner:
                return
            self._redis.set(key, source_owner, nx=True, ex=settings.dedup_window_hours * 3600)
        dedup = NewsDeduper(self._repo)
        existing = self._repo.find_news(props["id"])
        if existing is None:
            l2 = dedup.check_l2_text_dup(props["norm_headline"], props["ticker"], article.event_ts)
            if l2 and l2.get("canon_id"):
                self._repo.merge_news_event(props)
                dedup.link_duplicate(props["id"], l2["canon_id"])
                canonical = self._repo.find_news(l2["canon_id"])
                dedup._maybe_upgrade_canonical(
                    l2["canon_id"], props, canonical.get("source") if canonical else None
                )
                return
            embedding = self._embedder.embed_one(f"{article.headline}\n{article.summary}")
            outcome = dedup.semantic_link_or_create(props, embedding, article.event_ts)
            if outcome.action != "created":
                self._repo.merge_news_event(props)
                dedup.link_duplicate(props["id"], outcome.canonical_id)
                return
        chat = CheckedChat(self._chat)
        self._route(
            props,
            resolver,
            chat,
            sentiment_by_ticker=article.ticker_sentiment,
            article_sentiment=article.sentiment,
        )
        news = self._repo.find_news(props["id"])
        NewsCorrelator(chat).correlate(
            self._repo,
            props["id"],
            article.headline,
            article.summary,
            article.event_ts,
            article.event_ts,
            embedding=news.get("embedding") if news else None,
        )
        chat.require_success()
        self._redis.hset(revision_key, mapping={"completed_revision": str(event.revision)})

    def _mark_news_skipped(self, revision_key: str, event: CommittedEvent, reason: str) -> None:
        """Mark intentionally ineligible events complete so Redis can ACK them."""
        self._redis.hset(
            revision_key,
            mapping={
                "revision": str(event.revision),
                "completed_revision": str(event.revision),
                "eligibility": reason,
            },
        )

    def _route(
        self,
        news: dict,
        resolver: Any,
        chat: CheckedChat,
        only_tickers: list[str] | None = None,
        sentiment_by_ticker: Any = None,
        article_sentiment: float | None = None,
    ) -> None:
        extractor = NewsGraphExtractor(chat, resolver)
        profiles = StockProfileProvider(self._repo)
        cards = (
            profiles.build_context_card(ticker)
            for ticker in (only_tickers if only_tickers is not None else resolver.list_stocks())
        )
        for batch in card_batches(
            cards, news["headline"], news.get("summary", ""), resolver.registry_catalog()
        ):
            impacts = extractor.infer(news["id"], news["headline"], news.get("summary", ""), batch)
            chat.require_success()
            offered = {card.ticker for card in batch}
            impacts = [impact for impact in impacts if impact.ticker in offered]
            extractor.persist(self._repo, impacts, sentiment_by_ticker, article_sentiment)
        market = extractor.infer_market_impacts(
            news["id"], news["headline"], news.get("summary", "")
        )
        chat.require_success()
        extractor.persist_market_impacts(self._repo, market, article_sentiment)
