"""Context-aware LLM router: News + StockContextCards -> impact edges (Rule 4).

The prompt MUST inject StockContextCards (business summary, raw materials,
segments, latest snapshot/guidance, active exposures). Every entity the LLM
emits passes through CanonicalEntityResolver - unknown strings are dropped,
never invented (forex -> USD_INR_FX macro, no :Currency nodes). Only edges
with confidence >= ontology_min_confidence persist.

Two routing paths, because two kinds of news exist:

* **stock routing** - the article names a tracked company (or a tracked
  company's sector/exposure is hit). Produces `DIRECTLY_IMPACTS` /
  `INDIRECTLY_IMPACTS` and, when the model names a registry entity, the
  matching `SHOCKS` / `ALTERS_MACRO` / `IMPACTS_SECTOR` edge.
* **market routing** - the article names no tracked company at all (crude,
  the rupee, bond yields, a policy decision, a sector-wide move). Without
  this path those articles sit in the graph as isolated `BROAD_MARKET`
  nodes and the registry half of the ontology never touches news.

Both paths get the explicit registry catalog: a model asked for "the
canonical registry ID" without seeing the catalog invents plausible ids
(`OIL_PRICE`, `SECTOR:BANKING`), and an invented id is dropped downstream -
silently losing the edge.

LLM I/O via ChatProvider.complete_json (structured output only); raw text
responses are rejected, never regex-parsed. Uses llm_chat_model (high-volume
30m news path).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field
from stockgraph.application.errors import InferenceError
from stockgraph.domain.schemas import (
    InferredNewsMarketImpact,
    InferredNewsStockImpact,
    StockContextCard,
)
from stockgraph.runtime.settings import settings
from stockgraph.shared.tokens import truncate_to_tokens

logger = logging.getLogger(__name__)

IMPACT_TYPES = ("DIRECTLY_IMPACTS", "INDIRECTLY_IMPACTS")
MARKET_IMPACT_TYPES = ("SHOCKS", "ALTERS_MACRO", "IMPACTS_SECTOR")


class NewsImpactBatch(BaseModel):
    """Structured LLM envelope: one batch of routing decisions per article."""

    impacts: list[InferredNewsStockImpact] = Field(default_factory=list)


class NewsMarketImpactBatch(BaseModel):
    """Structured LLM envelope: registry-level routing for one article."""

    impacts: list[InferredNewsMarketImpact] = Field(default_factory=list)


def render_card(card: StockContextCard) -> str:
    """Render one StockContextCard into prompt text."""
    lines = [
        f"TICKER: {card.ticker}",
        f"Business: {card.business_summary or 'n/a'}",
        f"Strengths: {', '.join(card.strengths) or 'n/a'}",
        f"Business exclusions: {', '.join(card.business_exclusions) or 'n/a'}",
        f"Revenue segments: {', '.join(card.revenue_segments) or 'n/a'}",
        f"Raw materials: {', '.join(card.raw_material_inputs) or 'n/a'}",
        f"Geography: {card.geographic_exposure or 'n/a'}",
        f"Latest quarter: {card.latest_quarter_summary or 'n/a'}",
        f"Guidance: {'; '.join(card.latest_guidance_highlights) or 'n/a'}",
        f"Sector: {card.sector or 'n/a'}",
        f"Active exposures: {', '.join(card.active_exposures) or 'n/a'}",
    ]
    return "\n".join(lines)


def render_registry(catalog: list[dict[str, str]]) -> str:
    """Render the canonical registry the model is allowed to name."""
    if not catalog:
        return "(registry unavailable)"
    lines = []
    for kind in ("commodity", "macro", "sector"):
        rows = [c for c in catalog if c.get("kind") == kind]
        if not rows:
            continue
        lines.append(f"{kind.upper()}S:")
        for row in rows:
            lines.append(f"  {row['id']} - {row.get('label', row['id'])}")
    return "\n".join(lines)


def build_routing_prompt(
    headline: str,
    summary: str,
    cards: list[StockContextCard],
    registry: list[dict[str, str]] | None = None,
) -> str:
    """Assemble the extractor prompt with mandatory card injection."""
    cards_text = "\n\n".join(render_card(c) for c in cards)
    tickers = ", ".join(c.ticker for c in cards)
    prompt = (
        "You route ONE financial news article to impacted Indian stocks.\n"
        f"HEADLINE: {headline}\nSUMMARY: {summary}\n\n"
        "CANDIDATE STOCKS (use ONLY these tickers; emit nothing else):\n"
        f"{tickers}\n\n{cards_text}\n\n"
        "CANONICAL REGISTRY (use ONLY these ids for shocked_entity_id):\n"
        f"{render_registry(registry or [])}\n\n"
        "RULES:\n"
        "- DIRECTLY_IMPACTS: article names the company/event on it.\n"
        "- INDIRECTLY_IMPACTS: shock via a commodity/macro/sector exposure "
        "(set shocked_entity_id to a CANONICAL registry ID from the list "
        "above, e.g. BRENT_CRUDE, USD_INR_FX, BANKING). Forex is the "
        "USD_INR_FX macro.\n"
        "- MATERIALITY: route ONLY articles that report a market-relevant "
        "event for that company (results, guidance, orders, deals, stake "
        "changes, ratings, regulatory action, capacity/pricing, macro "
        "shock). If the company is only mentioned incidentally - a "
        "person's career or background, a brand/advertisement, a card or "
        "coupon discount, a passing mention in a list - emit NOTHING for "
        "it.\n"
        "- Omit stocks with no causal link. confidence 0.0-1.0 with a causal "
        "rationale citing the business profile or exposure.\n"
        'Return JSON: {"impacts": [{"ticker": ..., "impact_type": '
        '"DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS", "confidence": ..., '
        '"rationale": ..., "shocked_entity_id": ...}]}'
    )
    return truncate_to_tokens(prompt)


def build_market_prompt(
    headline: str,
    summary: str,
    registry: list[dict[str, str]] | None = None,
) -> str:
    """Assemble the market-level routing prompt (no stock named)."""
    prompt = (
        "You route ONE market news article to the entities it moves.\n"
        f"HEADLINE: {headline}\nSUMMARY: {summary}\n\n"
        "CANONICAL REGISTRY (use ONLY these ids):\n"
        f"{render_registry(registry or [])}\n\n"
        "RULES:\n"
        "- SHOCKS: the article moves a commodity (price, supply, demand, "
        "policy on that commodity).\n"
        "- ALTERS_MACRO: the article moves a macro factor (rates, "
        "inflation, growth, currency, bond yields, capex, US policy).\n"
        "- IMPACTS_SECTOR: the article is a sector-wide event (sector "
        "policy, sector demand/price move, sector-wide results).\n"
        "- Only report an entity the article ACTUALLY mentions or clearly "
        "implies. Emit nothing when the article is not about markets "
        "(sport, crime, culture, weather, celebrity).\n"
        "- confidence 0.0-1.0 with a rationale quoting the article.\n"
        'Return JSON: {"impacts": [{"entity_id": ..., "impact_type": '
        '"SHOCKS|ALTERS_MACRO|IMPACTS_SECTOR", "confidence": ..., '
        '"rationale": ...}]}'
    )
    return truncate_to_tokens(prompt)


class NewsGraphExtractor:
    """LLM router with resolver gating + confidence filtering."""

    def __init__(self, chat: Any, resolver: Any) -> None:
        self._chat = chat
        self._resolver = resolver

    @property
    def min_confidence(self) -> float:
        return settings.ontology_min_confidence

    def registry_catalog(self) -> list[dict[str, str]]:
        """The registry catalog the model is allowed to name."""
        catalog = getattr(self._resolver, "registry_catalog", None)
        if callable(catalog):
            return catalog()
        return []

    def infer(
        self, news_id: str, headline: str, summary: str, cards: list[StockContextCard]
    ) -> list[InferredNewsStockImpact]:
        """Prompt the LLM and return validated, resolver-gated impacts."""
        if not cards:
            return []
        prompt = build_routing_prompt(headline, summary, cards, self.registry_catalog())
        try:
            batch = self._chat.complete_json(prompt, NewsImpactBatch)
        except Exception as exc:
            raise InferenceError("LLM inference failed; event remains retryable") from exc
        if isinstance(batch, dict):
            try:
                batch = NewsImpactBatch.model_validate(batch)
            except Exception as exc:
                raise InferenceError("LLM inference failed; event remains retryable") from exc
        if not isinstance(batch, NewsImpactBatch):
            raise InferenceError("LLM inference failed; event remains retryable")
        return self.filter_impacts(news_id, batch.impacts)

    def infer_market_impacts(
        self, news_id: str, headline: str, summary: str
    ) -> list[InferredNewsMarketImpact]:
        """Route an article to registry entities (commodity / macro / sector).

        This is the path that connects `:NewsEvent` to the non-stock half
        of the ontology. It is deliberately independent of the candidate
        stock shortlist: the articles that move a commodity or a macro
        factor are usually the ones that name no tracked company.
        """
        prompt = build_market_prompt(headline, summary, self.registry_catalog())
        try:
            batch = self._chat.complete_json(prompt, NewsMarketImpactBatch)
        except Exception as exc:
            raise InferenceError("LLM inference failed; event remains retryable") from exc
        if isinstance(batch, dict):
            try:
                batch = NewsMarketImpactBatch.model_validate(batch)
            except Exception as exc:
                raise InferenceError("LLM inference failed; event remains retryable") from exc
        if not isinstance(batch, NewsMarketImpactBatch):
            raise InferenceError("LLM inference failed; event remains retryable")
        return self.filter_market_impacts(news_id, batch.impacts)

    def filter_impacts(
        self, news_id: str, impacts: list[InferredNewsStockImpact]
    ) -> list[InferredNewsStockImpact]:
        """Gate: confidence floor, known impact type, resolvable entities.

        `news_id` is set from the caller's value, never from the model's:
        the article being routed is already known, and a mangled echo of an
        opaque id must not be able to attach an edge to the wrong article.

        The real rules live here, not in the output schema, so a single
        malformed verdict is dropped instead of discarding the whole
        article's routing.
        """
        kept: list[InferredNewsStockImpact] = []
        for imp in impacts:
            if imp.impact_type not in IMPACT_TYPES:
                continue
            if not imp.rationale.strip():
                continue
            if not 0.0 <= imp.confidence <= 1.0:
                continue
            if imp.confidence < self.min_confidence:
                continue
            ticker = self._resolver.resolve_stock(imp.ticker)
            if ticker is None:
                logger.debug("Dropping unresolvable ticker %r", imp.ticker)
                continue
            shocked = None
            if imp.shocked_entity_id:
                hit = self._resolver.resolve_registry(imp.shocked_entity_id)
                if hit is None:
                    # The shock id is wrong, but the STOCK impact may still be
                    # sound. Dropping the whole verdict here silently lost
                    # valid stock edges whenever the model guessed an id that
                    # was not in the registry.
                    logger.debug("Dropping unresolvable shock %r", imp.shocked_entity_id)
                else:
                    shocked = hit.id
            kept.append(
                InferredNewsStockImpact(
                    news_id=news_id,
                    ticker=ticker,
                    impact_type=imp.impact_type,
                    confidence=imp.confidence,
                    rationale=imp.rationale,
                    shocked_entity_id=shocked,
                )
            )
        return kept

    def filter_market_impacts(
        self, news_id: str, impacts: list[InferredNewsMarketImpact]
    ) -> list[InferredNewsMarketImpact]:
        """Gate market impacts: known type, resolvable registry id, confidence.

        The impact type is CROSS-CHECKED against the resolved entity kind,
        so a model cannot claim `ALTERS_MACRO` for a sector id (or vice
        versa) and create an edge the dossier would then traverse through
        the wrong bridge.
        """
        kept: list[InferredNewsMarketImpact] = []
        for imp in impacts:
            if imp.impact_type not in MARKET_IMPACT_TYPES:
                continue
            if not imp.rationale.strip():
                continue
            if not 0.0 <= imp.confidence <= 1.0:
                continue
            if imp.confidence < self.min_confidence:
                continue
            hit = self._resolver.resolve_registry(imp.entity_id)
            if hit is None:
                logger.debug("Dropping unresolvable registry entity %r", imp.entity_id)
                continue
            expected = {"commodity": "SHOCKS", "macro": "ALTERS_MACRO", "sector": "IMPACTS_SECTOR"}[
                hit.kind
            ]
            if imp.impact_type != expected:
                logger.debug("Dropping %s for %s (%s entity)", imp.impact_type, hit.id, hit.kind)
                continue
            kept.append(
                InferredNewsMarketImpact(
                    news_id=news_id,
                    entity_id=hit.id,
                    impact_type=expected,
                    confidence=imp.confidence,
                    rationale=imp.rationale,
                )
            )
            if len(kept) >= settings.news_market_impact_max:
                break
        return kept

    def persist(
        self,
        repo: Any,
        impacts: list[InferredNewsStockImpact],
        sentiment_by_ticker: Mapping[str, float] | None = None,
        article_sentiment: float | None = None,
    ) -> int:
        """Write gated impacts + shock edges. Returns edge count.

        `sentiment_by_ticker` is the PROVIDER's per-entity sentiment for
        each impacted ticker, and `article_sentiment` the article-level
        score used on the (non stock-specific) shock edges. Both arrive
        from outside the LLM schema, so the LLM can never fabricate them.
        """
        per_ticker = sentiment_by_ticker or {}
        count = 0
        for imp in impacts:
            sentiment = per_ticker.get(imp.ticker)
            repo.merge_stock_impact(
                imp.news_id,
                imp.ticker,
                imp.impact_type,
                imp.confidence,
                imp.rationale,
                sentiment=sentiment,
            )
            count += 1
            if imp.shocked_entity_id:
                kind = self.shock_kind(imp.shocked_entity_id)
                if kind is not None:
                    repo.merge_news_shock(
                        imp.news_id,
                        kind,
                        imp.shocked_entity_id,
                        imp.confidence,
                        imp.rationale,
                        sentiment=article_sentiment,
                    )
                    count += 1
        return count

    def persist_market_impacts(
        self,
        repo: Any,
        impacts: list[InferredNewsMarketImpact],
        article_sentiment: float | None = None,
    ) -> int:
        """Write market-level edges (SHOCKS / ALTERS_MACRO / IMPACTS_SECTOR)."""
        count = 0
        for imp in impacts:
            kind = self.shock_kind(imp.entity_id)
            if kind is None:
                continue
            repo.merge_news_shock(
                imp.news_id,
                kind,
                imp.entity_id,
                imp.confidence,
                imp.rationale,
                sentiment=article_sentiment,
            )
            count += 1
        return count

    def shock_kind(self, shocked_id: str) -> str | None:
        hit = self._resolver.resolve_registry(shocked_id)
        return hit.kind if hit is not None else None
