"""Committed-event graph processing: no provider calls and no relational repository."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from stockgraph.application.errors import BudgetExceeded, InferenceError, LLMDisabled
from stockgraph.application.ports import (
    ChatModel,
    EmbeddingModel,
    EventStateStore,
    NewsRoutingHandler,
    NewsStore,
    RegistryStore,
    StockContextBuilder,
)
from stockgraph.application.processors.batching import card_batches
from stockgraph.application.processors.dynamic_ontology_builder import DynamicOntologyBuilder
from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver
from stockgraph.application.processors.news_candidate_resolver import NewsCandidateResolver
from stockgraph.application.processors.news_correlator import NewsCorrelator
from stockgraph.application.processors.news_dedup import (
    NewsDeduper,
    build_news_props,
    canonicalize_url,
    higher_priority,
    url_seen_key,
)
from stockgraph.application.processors.news_eligibility import (
    GraphNewsEligibilityReviewer,
    NewsEligibilityRequest,
    hard_rejection_reason,
    is_approved_event,
)
from stockgraph.application.processors.news_graph_extractor import NewsGraphExtractor
from stockgraph.domain.entities import NewsArticle
from stockgraph.domain.enums import NewsCategory
from stockgraph.domain.events import CommittedEvent
from stockgraph.runtime.settings import settings


class ValidatingChat:
    """Validate the model contract and surface errors as retryable failures."""

    def __init__(self, provider: ChatModel) -> None:
        self._provider = provider

    def complete_json(self, prompt: str, schema: Any, **kwargs: Any) -> Any:
        try:
            result = self._provider.complete_json(prompt, schema, **kwargs)
            if isinstance(result, dict):
                result = schema.model_validate(result)
            if not isinstance(result, schema):
                raise ValueError("LLM provider did not return the requested structured schema")
            return result
        except (BudgetExceeded, LLMDisabled):
            raise
        except Exception as exc:
            raise InferenceError("LLM inference failed; event remains retryable") from exc


class _InferenceGuard:
    def _require_inference(self) -> None:
        if not settings.llm_enabled:
            raise LLMDisabled(
                "LLM_ENABLED=false: projection is pending semantic inference, not completed"
            )


class RegistryEventHandler(_InferenceGuard):
    def __init__(self, repo: RegistryStore, chat: ChatModel, embedder: EmbeddingModel,
                 news_handler: NewsRoutingHandler, profiles: StockContextBuilder,
                 ontology_factory=DynamicOntologyBuilder) -> None:
        self._repo, self._chat, self._embedder = repo, chat, embedder
        self._news_handler, self._profiles = news_handler, profiles
        self._ontology_factory = ontology_factory

    def handle(self, event: CommittedEvent) -> None:
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
        chat = ValidatingChat(self._chat)
        # New market entities can affect any existing stock, not just newly added stocks.
        tickers = [event.entity_id] if kind == "Stock" else resolver.list_stocks()
        builder = self._ontology_factory(chat, resolver, model=settings.llm_ontology_model)
        for ticker in tickers:
            card = self._profiles.build_context_card(ticker)
            self._repo.merge_stock_profile_embedding(
                ticker, self._embedder.embed_one(card.model_dump_json())
            )
            edges = builder.infer_edges(card, now_ts=int(event.occurred_at.timestamp()))
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
                self._news_handler.route(news, resolver, chat, only_tickers=tickers)
            if len(rows) < 100:
                break
            offset += len(rows)
        self._repo.mark_entity_processed(kind, event.entity_id, event.revision)


class NewsEventHandler(_InferenceGuard):
    def __init__(self, repo: NewsStore, redis: EventStateStore, chat: ChatModel,
                 embedder: EmbeddingModel, profiles: StockContextBuilder, deduper: NewsDeduper,
                 extractor_factory=NewsGraphExtractor, correlator_factory=NewsCorrelator) -> None:
        self._repo, self._redis, self._chat, self._embedder = repo, redis, chat, embedder
        self._profiles, self._deduper = profiles, deduper
        self._extractor_factory, self._correlator_factory = extractor_factory, correlator_factory

    def handle(self, event: CommittedEvent) -> None:
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
        if raw.get("category") != "REG30" and hard_rejection_reason(
            str(raw.get("headline") or ""), str(raw.get("summary") or "")
        ):
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
            if verdict.reason == "REVIEW_UNAVAILABLE":
                raise RuntimeError("News eligibility review unavailable; retry staged event")
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
        source_canonical = self._redis.hget(revision_key, "canonical_news_id")
        if isinstance(source_canonical, bytes):
            source_canonical = source_canonical.decode()
        if source_canonical:
            # A provider's stable external ID identifies revisions of the same
            # event, even when corrected headline/entity text changes the hash.
            props["id"] = source_canonical
        existing = self._repo.find_news(props["id"])
        # A retry owns its L1 reservation. Higher-priority evidence sharing the
        # same URL must still be considered by canonical source selection.
        if article.source_url:
            key = url_seen_key(canonicalize_url(article.source_url))
            owner = self._redis.get(key)
            if isinstance(owner, bytes):
                owner = owner.decode()
            source_owner = f"source:{event.entity_id}"
            if (
                owner
                and owner != source_owner
                and not (existing and higher_priority(props["source"], existing.get("source")))
            ):
                self._mark_news_skipped(revision_key, event, "duplicate_url")
                return
            self._redis.set(key, source_owner, nx=True, ex=settings.dedup_window_hours * 3600)
        incoming = props
        if existing is None:
            dedup = self._deduper
            l2 = dedup.check_l2_text_dup(props["norm_headline"], props["ticker"], article.event_ts)
            canon_id = l2.get("canon_id") if l2 else None
            embedding = None
            if not canon_id:
                embedding = self._embedder.embed_one(f"{article.headline}\n{article.summary}")
                hit = dedup.find_semantic_duplicate(embedding, props["ticker"], article.event_ts)
                if hit is not None:
                    canon_id = hit["id"]
            if canon_id and canon_id != props["id"]:
                self._repo.merge_news_event(props)
                dedup.link_duplicate(props["id"], canon_id)
                existing = self._repo.find_news(canon_id)
                incoming = {**props, "id": canon_id}
            elif existing is None:
                incoming = {
                    **props,
                    "source_entity_id": event.entity_id,
                    "source_revision": event.revision,
                }
                self._repo.merge_news_event(incoming, embedding=embedding)
                existing = self._repo.find_news(props["id"])
        props = self._accepted_news(existing, incoming, event)
        self._redis.hset(revision_key, mapping={"canonical_news_id": props["id"]})
        # Inference and citation always use the same accepted canonical content.
        accepted_incoming = props.get("source_entity_id") == event.entity_id
        chat = ValidatingChat(self._chat)
        self.route(
            props,
            resolver,
            chat,
            sentiment_by_ticker=article.ticker_sentiment if accepted_incoming else None,
            article_sentiment=props.get("sentiment"),
        )
        news = self._repo.find_news(props["id"])
        self._correlator_factory(chat).correlate(
            self._repo,
            props["id"],
            props["headline"],
            props.get("summary", ""),
            props["event_ts"],
            props["event_ts"],
            embedding=news.get("embedding") if news else None,
        )
        self._redis.hset(revision_key, mapping={"completed_revision": str(event.revision)})

    def _accepted_news(self, existing: dict | None, incoming: dict, event: CommittedEvent) -> dict:
        old = dict(existing or {})
        same_origin = old.get("source_entity_id") == event.entity_id or (
            not old.get("source_entity_id")
            and old.get("source") == incoming.get("source")
            and old.get("source_url") == incoming.get("source_url")
        )
        accept = (
            not old or higher_priority(incoming.get("source"), old.get("source")) or same_origin
        )
        accepted = dict(old)
        if accept:
            accepted.update(incoming)
            accepted.update(source_entity_id=event.entity_id, source_revision=event.revision)
            # The earliest event remains canonical even when a later filing is richer.
            if old.get("event_ts") and old["event_ts"] < accepted["event_ts"]:
                accepted["event_ts"], accepted["event_date"] = old["event_ts"], old["event_date"]
        content_changed = any(old.get(key) != accepted.get(key) for key in ("headline", "summary"))
        if content_changed or not old.get("embedding"):
            embedding = self._embedder.embed_one(
                f"{accepted['headline']}\n{accepted.get('summary', '')}"
            )
            self._repo.merge_news_event(accepted, embedding=embedding)
            accepted["embedding"] = embedding
        elif accept:
            self._repo.merge_news_event(accepted)
        return accepted

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

    def route(
        self,
        news: dict,
        resolver: Any,
        chat: ValidatingChat,
        only_tickers: list[str] | None = None,
        sentiment_by_ticker: Any = None,
        article_sentiment: float | None = None,
    ) -> None:
        extractor = self._extractor_factory(chat, resolver)
        cards = (
            self._profiles.build_context_card(ticker)
            for ticker in (only_tickers if only_tickers is not None else resolver.list_stocks())
        )
        scope_tickers = []
        stock_impacts = []
        for batch in card_batches(
            cards, news["headline"], news.get("summary", ""), resolver.registry_catalog()
        ):
            impacts = extractor.infer(news["id"], news["headline"], news.get("summary", ""), batch)
            offered = {card.ticker for card in batch}
            scope_tickers.extend(offered)
            stock_impacts.extend(impact for impact in impacts if impact.ticker in offered)
        market = extractor.infer_market_impacts(
            news["id"], news["headline"], news.get("summary", "")
        )
        # Finish every model batch before replacing accepted relationships.
        stock_rows = [
            {
                "ticker": imp.ticker,
                "impact_type": imp.impact_type,
                "confidence": imp.confidence,
                "rationale": imp.rationale,
                "sentiment": (sentiment_by_ticker or {}).get(imp.ticker),
            }
            for imp in stock_impacts
        ]
        market_rows = [
            {
                "entity_id": imp.entity_id,
                "kind": extractor.shock_kind(imp.entity_id),
                "confidence": imp.confidence,
                "rationale": imp.rationale,
                "sentiment": article_sentiment,
            }
            for imp in market
        ]
        market_rows.extend(
            {
                "entity_id": imp.shocked_entity_id,
                "kind": extractor.shock_kind(imp.shocked_entity_id),
                "confidence": imp.confidence,
                "rationale": imp.rationale,
                "sentiment": article_sentiment,
            }
            for imp in stock_impacts
            if imp.shocked_entity_id
        )
        self._repo.reconcile_news_impacts(news["id"], scope_tickers, stock_rows, market_rows)
