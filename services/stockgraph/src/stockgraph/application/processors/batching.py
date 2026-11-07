"""Token-aware batches that cover every registered stock; never a shortlist cap."""

from collections.abc import Iterable

from stockgraph.application.processors.news_graph_extractor import render_card, render_registry
from stockgraph.domain.schemas import StockContextCard
from stockgraph.runtime.settings import settings
from stockgraph.shared.tokens import count_tokens, truncate_to_tokens


def compact_card(card: StockContextCard) -> StockContextCard:
    """Bound each narrative while preserving the stock's identity in every batch."""
    return card.model_copy(
        update={
            "business_summary": truncate_to_tokens(card.business_summary or "", 250),
            "latest_quarter_summary": truncate_to_tokens(card.latest_quarter_summary or "", 150),
            "latest_guidance_highlights": [
                truncate_to_tokens("; ".join(card.latest_guidance_highlights), 120)
            ],
        }
    )


def card_batches(
    cards: Iterable[StockContextCard], headline: str, summary: str, catalog: list[dict]
) -> Iterable[list[StockContextCard]]:
    overhead = count_tokens(headline + summary + render_registry(catalog)) + 850
    budget = settings.llm_max_tokens_per_call - overhead
    batch: list[StockContextCard] = []
    size = 0
    for original in cards:
        card = compact_card(original)
        tokens = count_tokens(render_card(card)) + 15
        if tokens > budget:
            raise ValueError(
                f"Stock {card.ticker} context exceeds prompt budget; increase LLM_MAX_TOKENS_PER_CALL"
            )
        if batch and size + tokens > budget:
            yield batch
            batch, size = [], 0
        batch.append(card)
        size += tokens
    if batch:
        yield batch
