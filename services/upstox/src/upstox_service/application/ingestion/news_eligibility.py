"""Pre-persistence eligibility policy for news ingestion.

Provider categories are useful hints but are not trustworthy enough to decide
whether an article belongs in a financial graph.  This module keeps the
deterministic, fail-closed part of that policy in the data service.  Only
ambiguous items are sent to StockGraph's internal LLM reviewer; rejected
articles never reach a repository method or the event outbox.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from upstox_service.config.settings import settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory

logger = logging.getLogger(__name__)

APPROVED_CATEGORIES = frozenset(
    {
        NewsCategory.EARNINGS,
        NewsCategory.SECTOR_UPDATE,
        NewsCategory.MACRO,
        NewsCategory.TRADE,
        NewsCategory.GEOPOLITICAL,
        NewsCategory.REG30,
        NewsCategory.COMMODITY,
        NewsCategory.CORPORATE_ACTION,
    }
)

# These are intentionally broad and take precedence over all provider labels.
# A publisher can put a cricket story on a business desk; that does not make it
# financial market news.
# Financial materiality takes precedence over incidental sector vocabulary.
MATERIAL_FINANCIAL_EVENT = re.compile(
    r"\b(?:quarterly|earnings|profits?|revenues?|ebitda|dividends?|buybacks?|"
    r"shareholders?|acquisitions?|mergers?|ipo|debt|default|insolvency|"
    r"regulatory filing|reg[ -]?30|financial results)\b",
    re.IGNORECASE,
)

HARD_REJECTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "SPORTS",
        (
            r"\bcricket(?:er|ing)?\b",
            r"\bfootball\b",
            r"\btennis\b",
            r"\bipl\b",
            r"\bodi\b",
            r"\bworld cup\b",
            r"\bmatch(?:es)?\b",
            r"\btournament\b",
            r"\binnings\b",
        ),
    ),
    (
        "ENTERTAINMENT",
        (
            r"\bcelebrity\b",
            r"\bbollywood\b",
            r"\bfilm(?:s)?\b",
            r"\bmovie\b",
            r"\bactor\b",
            r"\bactress\b",
            r"\breality show\b",
        ),
    ),
    (
        "LIFESTYLE",
        (r"\bfashion\b", r"\brecipe\b", r"\bhoroscope\b", r"\btravel tips\b"),
    ),
)

MARKET_MATERIAL_GEO_PATTERNS = (
    r"\bsanction(?:s)?\b",
    r"\btariff(?:s)?\b",
    r"\btrade\b",
    r"\bimport(?:s| duty| duties)?\b",
    r"\bexport(?:s| duty| duties)?\b",
    r"supply chain",
    r"shipping|freight|red sea|strait",
    r"\bcrude\b|\boil\b|\benergy\b|\bgas\b",
    r"\bcommodity|commodities\b",
    r"\brupee\b|\bfx\b|\bcurrency\b|\busd/inr\b",
    r"\binflation\b|\brates?\b|\bbond yield\b|\bmarkets?\b|\bequities?\b",
    r"\bindia(?:n)? economy\b|\bnse\b|\bbse\b",
)

# These are article-text signals, not publisher-desk labels. They capture
# plainly financial market reporting that a provider may otherwise label as
# ``general`` (for example, a Nifty move or a 52-week stock low).
CLEAR_MARKET_EVENT_PATTERNS = (
    r"\bnifty\b|\bsensex\b|\bnse\b|\bbse\b",
    r"\bshares?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
    r"\bstock(?:s)?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
    r"\b(?:52[ -]?week|all[ -]?time)\s+(?:high|low)\b",
    r"\b(?:trading|trade)\s+volume\b",
)


@dataclass(frozen=True)
class EligibilityDecision:
    approved: bool
    category: NewsCategory | None
    source: str
    reason: str


class EligibilityReviewer(Protocol):
    async def review(self, article: NewsArticle) -> EligibilityDecision | None: ...


class StockGraphEligibilityReviewer:
    """Thin HTTP client; LLM credentials never enter the data service."""

    def __init__(self, url: str | None = None, timeout_seconds: float | None = None) -> None:
        self._url = (url if url is not None else settings.news_eligibility_url).strip()
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.news_eligibility_timeout_seconds
        )

    async def review(self, article: NewsArticle) -> EligibilityDecision | None:
        if not self._url:
            return None
        payload = {
            "headline": article.headline,
            "summary": article.summary,
            "candidate_tickers": list(article.tickers),
            "preliminary_category": article.category.value,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload)
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict):
                return None
            if body.get("reason") == "REVIEW_UNAVAILABLE":
                return None
            if not bool(body.get("eligible")):
                return EligibilityDecision(
                    False, None, "LLM", str(body.get("reason") or "LLM_REJECTED")
                )
            category = NewsCategory(str(body.get("category") or ""))
            if category not in APPROVED_CATEGORIES:
                return None
            return EligibilityDecision(
                True, category, "LLM", str(body.get("reason") or "LLM_APPROVED")
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning(
                "News eligibility review unavailable; article review remains pending (%s)",
                type(exc).__name__,
            )
            return None


class NewsEligibilityGate:
    """Deterministic allow/deny policy with an injected ambiguity reviewer."""

    def __init__(self, reviewer: EligibilityReviewer | None = None) -> None:
        self._reviewer = reviewer or StockGraphEligibilityReviewer()

    async def decide(self, article: NewsArticle) -> EligibilityDecision:
        text = f"{article.headline}\n{article.summary}".lower()
        hard_reason = self.hard_rejection_reason(text)
        if hard_reason and article.category is not NewsCategory.REG30:
            return EligibilityDecision(False, None, "RULES", hard_reason)

        category = article.category
        if category is NewsCategory.OTHER and self._matches_clear_market_event(text):
            return EligibilityDecision(
                True,
                NewsCategory.SECTOR_UPDATE,
                "RULES",
                "CLEAR_MARKET_EVENT",
            )
        if category is NewsCategory.REG30:
            return EligibilityDecision(True, category, "RULES", "REG30_DISCLOSURE")
        if category is NewsCategory.GEOPOLITICAL:
            if self._matches_market_geopolitics(text):
                return EligibilityDecision(True, category, "RULES", "MARKET_MATERIAL_GEOPOLITICS")
            return await self._review_or_reject(article)
        if category in APPROVED_CATEGORIES:
            return EligibilityDecision(True, category, "RULES", f"CLEAR_{category.value}")
        return await self._review_or_reject(article)

    async def _review_or_reject(self, article: NewsArticle) -> EligibilityDecision:
        verdict = await self._reviewer.review(article)
        if verdict is None:
            return EligibilityDecision(False, None, "LLM", "REVIEW_UNAVAILABLE")
        if not verdict.approved or verdict.category not in APPROVED_CATEGORIES:
            return EligibilityDecision(False, None, "LLM", verdict.reason or "LLM_REJECTED")
        return verdict

    @staticmethod
    def hard_rejection_reason(text: str) -> str | None:
        if MATERIAL_FINANCIAL_EVENT.search(text):
            return None
        for reason, patterns in HARD_REJECTION_PATTERNS:
            if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
                return reason
        return None

    @staticmethod
    def _matches_market_geopolitics(text: str) -> bool:
        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in MARKET_MATERIAL_GEO_PATTERNS
        )

    @staticmethod
    def _matches_clear_market_event(text: str) -> bool:
        return any(
            re.search(pattern, text, flags=re.IGNORECASE) for pattern in CLEAR_MARKET_EVENT_PATTERNS
        )
