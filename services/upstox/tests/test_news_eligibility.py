from __future__ import annotations

from datetime import UTC, datetime

import pytest
from upstox_service.adapters.providers.news.adapters import (
    ProviderFetchResult,
    ProviderStatus,
    StagedNewsItem,
)
from upstox_service.application.ingestion.news_eligibility import (
    EligibilityDecision,
    NewsEligibilityGate,
)
from upstox_service.application.ingestion.news_fetch import NewsFetchService
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory


def article(headline: str, category: NewsCategory, summary: str = "") -> NewsArticle:
    return NewsArticle(
        external_id=headline[:40],
        headline=headline,
        summary=summary,
        source_url="https://example.com/news",
        source="TEST",
        published_at=datetime.now(UTC),
        category=category,
    )


class Reviewer:
    def __init__(self, decision: EligibilityDecision | None) -> None:
        self.decision = decision
        self.calls = 0

    async def review(self, _article: NewsArticle) -> EligibilityDecision | None:
        self.calls += 1
        return self.decision


@pytest.mark.asyncio
async def test_cricket_is_rejected_even_when_provider_mislabels_it_as_sector_update():
    reviewer = Reviewer(EligibilityDecision(True, NewsCategory.MACRO, "LLM", "wrong"))
    decision = await NewsEligibilityGate(reviewer).decide(
        article("Cricket team wins a record ODI chase", NewsCategory.SECTOR_UPDATE)
    )
    assert not decision.approved
    assert decision.reason == "SPORTS"
    assert reviewer.calls == 0


@pytest.mark.asyncio
async def test_ambiguous_article_is_approved_only_by_structured_llm_verdict():
    reviewer = Reviewer(EligibilityDecision(True, NewsCategory.TRADE, "LLM", "export restriction"))
    decision = await NewsEligibilityGate(reviewer).decide(
        article("New export restriction announced", NewsCategory.OTHER)
    )
    assert decision.approved
    assert decision.category is NewsCategory.TRADE
    assert decision.source == "LLM"
    assert reviewer.calls == 1


@pytest.mark.asyncio
async def test_ambiguous_article_fails_closed_when_reviewer_is_unavailable():
    decision = await NewsEligibilityGate(Reviewer(None)).decide(
        article("A general local update", NewsCategory.OTHER)
    )
    assert not decision.approved
    assert decision.reason == "REVIEW_UNAVAILABLE"


@pytest.mark.asyncio
async def test_clear_market_event_is_accepted_without_a_weak_provider_label():
    reviewer = Reviewer(None)
    decision = await NewsEligibilityGate(reviewer).decide(
        article("Nifty recovers, but 432 stocks hit 52-week lows", NewsCategory.OTHER)
    )
    assert decision.approved
    assert decision.category is NewsCategory.SECTOR_UPDATE
    assert decision.reason == "CLEAR_MARKET_EVENT"
    assert reviewer.calls == 0


@pytest.mark.asyncio
async def test_filter_keeps_only_approved_raw_pair_and_advances_watermark_for_rejection():
    cricket = article("Cricket team wins a record ODI chase", NewsCategory.SECTOR_UPDATE)
    market = article("RBI holds repo rate steady", NewsCategory.MACRO)
    result = ProviderFetchResult(
        provider_id="TEST",
        status=ProviderStatus.AVAILABLE,
        articles=(cricket, market),
        staged=(
            StagedNewsItem(cricket.external_id, cricket.published_at, cricket.source_url, {"id": "cricket"}),
            StagedNewsItem(market.external_id, market.published_at, market.source_url, {"id": "market"}),
        ),
        watermark_at=market.published_at,
    )
    filtered = await NewsFetchService([], eligibility_reviewer=Reviewer(None))._filter_eligible(result)
    assert [item.headline for item in filtered.articles] == [market.headline]
    assert [item.external_id for item in filtered.staged] == [market.external_id]
    assert filtered.approvals[market.external_id] == ("RULES", "CLEAR_MACRO")
    assert filtered.watermark_at == market.published_at
    assert filtered.eligibility_counts["rejected:SPORTS"] == 1
