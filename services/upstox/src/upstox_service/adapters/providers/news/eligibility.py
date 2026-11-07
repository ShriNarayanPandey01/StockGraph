"""HTTP adapter for StockGraph news eligibility review."""

import logging

import httpx

from upstox_service.application.ingestion.news_eligibility import (
    APPROVED_CATEGORIES,
    EligibilityDecision,
)
from upstox_service.config.settings import settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory

logger = logging.getLogger(__name__)


class StockGraphEligibilityReviewer:
    """Thin HTTP client; LLM credentials never enter the data service."""

    def __init__(
        self, url: str | None = None, timeout_seconds: float | None = None, *, config=None
    ) -> None:
        config = config or settings
        self._internal_key = config.internal_service_key.get_secret_value()
        self._url = (url if url is not None else config.news_eligibility_url).strip()
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else config.news_eligibility_timeout_seconds
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
                response = await client.post(
                    self._url, json=payload, headers={"X-Internal-Service-Key": self._internal_key}
                )
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
