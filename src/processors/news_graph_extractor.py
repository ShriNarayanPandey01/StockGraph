"""Context-aware LLM router: News + StockContextCards -> impact edges (Rule 4).

The prompt MUST inject StockContextCards (business summary, raw materials,
segments, latest snapshot/guidance, active exposures). Every entity the LLM
emits passes through CanonicalEntityResolver - unknown strings are dropped,
never invented (forex -> USD_INR_FX macro, no :Currency nodes). Only edges
with confidence >= ontology_min_confidence persist.

LLM I/O via ChatProvider.complete_json (structured output only); raw text
responses are rejected, never regex-parsed. Uses llm_chat_model (high-volume
30m news path).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.domain.schemas import InferredNewsStockImpact, StockContextCard
from src.llm.tokens import truncate_to_tokens

logger = logging.getLogger(__name__)

IMPACT_TYPES = ("DIRECTLY_IMPACTS", "INDIRECTLY_IMPACTS")
MAX_CARDS_PER_PROMPT = 8


class NewsImpactBatch(BaseModel):
    """Structured LLM envelope: one batch of routing decisions per article."""

    impacts: list[InferredNewsStockImpact] = Field(default_factory=list)


def render_card(card: StockContextCard) -> str:
    """Render one StockContextCard into prompt text."""
    lines = [
        f"TICKER: {card.ticker}",
        f"Business: {card.business_summary or 'n/a'}",
        f"Revenue segments: {', '.join(card.revenue_segments) or 'n/a'}",
        f"Raw materials: {', '.join(card.raw_material_inputs) or 'n/a'}",
        f"Geography: {card.geographic_exposure or 'n/a'}",
        f"Latest quarter: {card.latest_quarter_summary or 'n/a'}",
        f"Guidance: {'; '.join(card.latest_guidance_highlights) or 'n/a'}",
        f"Active exposures: {', '.join(card.active_exposures) or 'n/a'}",
    ]
    return "\n".join(lines)


def build_routing_prompt(headline: str, summary: str, cards: list[StockContextCard]) -> str:
    """Assemble the extractor prompt with mandatory card injection."""
    cards = cards[:MAX_CARDS_PER_PROMPT]
    cards_text = "\n\n".join(render_card(c) for c in cards)
    tickers = ", ".join(c.ticker for c in cards)
    prompt = (
        "You route ONE financial news article to impacted Indian stocks.\n"
        f"HEADLINE: {headline}\nSUMMARY: {summary}\n\n"
        "CANDIDATE STOCKS (use ONLY these tickers; emit nothing else):\n"
        f"{tickers}\n\n{cards_text}\n\n"
        "RULES:\n"
        "- DIRECTLY_IMPACTS: article names the company/event on it.\n"
        "- INDIRECTLY_IMPACTS: shock via a commodity/macro/sector exposure "
        "(set shocked_entity_id to the CANONICAL registry ID, e.g. "
        "BRENT_CRUDE, USD_INR_FX). Forex is the USD_INR_FX macro.\n"
        "- Omit stocks with no causal link. confidence 0.0-1.0 with a causal "
        "rationale citing the business profile or exposure.\n"
        'Return JSON: {"impacts": [{"news_id": ..., "ticker": ..., '
        '"impact_type": "DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS", "confidence": '
        '..., "rationale": ..., "shocked_entity_id": ...}]}'
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

    def infer(
        self, news_id: str, headline: str, summary: str, cards: list[StockContextCard]
    ) -> list[InferredNewsStockImpact]:
        """Prompt the LLM and return validated, resolver-gated impacts."""
        if not cards:
            return []
        prompt = build_routing_prompt(headline, summary, cards)
        try:
            batch = self._chat.complete_json(prompt, NewsImpactBatch)
        except Exception as exc:
            logger.warning("Extractor LLM call failed for %s: %s", news_id, exc)
            return []
        if isinstance(batch, dict):
            try:
                batch = NewsImpactBatch.model_validate(batch)
            except Exception as exc:
                logger.warning("Extractor output invalid for %s: %s", news_id, exc)
                return []
        if not isinstance(batch, NewsImpactBatch):
            logger.warning("Extractor rejected non-structured output for %s", news_id)
            return []
        return self.filter_impacts(news_id, batch.impacts)

    def filter_impacts(
        self, news_id: str, impacts: list[InferredNewsStockImpact]
    ) -> list[InferredNewsStockImpact]:
        """Gate: confidence floor, known impact type, resolvable entities."""
        kept: list[InferredNewsStockImpact] = []
        for imp in impacts:
            if imp.impact_type not in IMPACT_TYPES:
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
                    logger.debug("Dropping unresolvable shock %r", imp.shocked_entity_id)
                    continue
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

    def persist(self, repo: Any, impacts: list[InferredNewsStockImpact]) -> int:
        """Write gated impacts + shock edges. Returns edge count."""
        count = 0
        for imp in impacts:
            repo.merge_stock_impact(
                imp.news_id, imp.ticker, imp.impact_type, imp.confidence, imp.rationale
            )
            count += 1
            if imp.shocked_entity_id:
                kind = self._shock_kind(imp.shocked_entity_id)
                if kind is not None:
                    repo.merge_news_shock(
                        imp.news_id, kind, imp.shocked_entity_id, imp.confidence, imp.rationale
                    )
                    count += 1
        return count

    def _shock_kind(self, shocked_id: str) -> str | None:
        hit = self._resolver.resolve_registry(shocked_id)
        return hit.kind if hit is not None else None
