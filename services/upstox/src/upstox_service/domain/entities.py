"""Internal domain objects (AGENTS.md Â§4 "Internal domain objects").

These are value objects shared across layer boundaries. They are deliberately
*not* Pydantic API models (the adapter schemas own those) - the API
surface and the internal model have different lifetimes and different
audiences.

`NewsArticle` is THE article contract for the whole news slice:

    provider adapter  ->  NewsArticle  ->  fetch service  ->  stream ingestor
                                                        ->  graph (:NewsEvent)

Because every layer speaks `NewsArticle`, a mistyped dict key can no longer
silently become `category="OTHER"`, and `event_ts` / `event_date` are derived
in exactly one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

from upstox_service.domain.enums import NewsCategory

APP_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class NewsArticle:
    """One normalized news article from a provider.

    Immutable value object: a news article is a fact about the past, so it
    must not be mutable once constructed.

    `tickers` holds CANONICAL NSE tickers (never provider symbols) in
    provider-preference order - the provider's own entity ranking is more
    precise than text matching. `ticker_sentiment` holds the provider's
    per-entity sentiment score (-1..+1) for those tickers, which is what
    lands on the `:DIRECTLY_IMPACTS` edge.

    `published_at` is the authoritative event instant. `event_ts` and
    `event_date` are DERIVED, never stored independently, so they can never
    disagree with each other or with the publication time:

    - `event_ts`  - UTC epoch seconds (graph `event_ts: int`).
    - `event_date` - IST calendar date (Rule 3 windows are IST-aware, so an
      article published 23:30 UTC belongs to the next Indian trading day).
    """

    external_id: str
    headline: str
    summary: str
    source_url: str
    source: str
    published_at: datetime
    category: NewsCategory
    sentiment: float | None = None
    tickers: tuple[str, ...] = ()
    ticker_sentiment: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and freeze the article (defensive copy of the mapping)."""
        if not self.headline.strip():
            raise ValueError("NewsArticle requires a non-empty headline")
        if self.published_at.tzinfo is None:
            # Providers occasionally omit the offset. Assume UTC rather than
            # crash ingestion (ingestion must never crash - see chunking.py).
            object.__setattr__(self, "published_at", self.published_at.replace(tzinfo=UTC))
        object.__setattr__(self, "ticker_sentiment", MappingProxyType(dict(self.ticker_sentiment)))

    @property
    def event_ts(self) -> int:
        """UTC epoch seconds - the graph's `event_ts` (point-in-time filter)."""
        return int(self.published_at.timestamp())

    @property
    def event_date(self) -> str:
        """IST calendar date (`YYYY-MM-DD`) - the graph's `event_date`."""
        return self.published_at.astimezone(APP_TZ).date().isoformat()

    @property
    def sentiment_for(self, ticker: str) -> float | None:
        """Provider sentiment for one canonical ticker, if the provider gave it."""
        return self.ticker_sentiment.get(ticker.upper())
