from __future__ import annotations

from stockgraph.application.processors.news_correlator import MARKET_CATEGORIES
from stockgraph.application.processors.news_eligibility import (
    GraphNewsEligibilityReviewer,
    NewsEligibilityRequest,
    is_approved_event,
)
from stockgraph.domain.enums import NewsCategory


class Chat:
    def complete_json(self, _prompt, schema, **_kwargs):
        return schema.model_validate(
            {
                "eligible": True,
                "category": "TRADE",
                "reason": "Tariffs affect Indian imports.",
            }
        )


def test_graph_reviewer_rejects_cricket_without_an_llm_call():
    class NoCall:
        def complete_json(self, *_args, **_kwargs):
            raise AssertionError("hard-rejected article must not call LLM")

    verdict = GraphNewsEligibilityReviewer(NoCall()).review(
        NewsEligibilityRequest(
            headline="Cricket team wins ODI match",
            preliminary_category=NewsCategory.SECTOR_UPDATE,
        )
    )
    assert not verdict.eligible
    assert verdict.reason == "SPORTS"


def test_graph_reviewer_allows_structured_trade_verdict():
    verdict = GraphNewsEligibilityReviewer(Chat()).review(
        NewsEligibilityRequest(headline="India changes import tariff", preliminary_category=NewsCategory.OTHER)
    )
    assert verdict.eligible
    assert verdict.category is NewsCategory.TRADE


def test_graph_reviewer_accepts_clear_market_event_without_an_llm_call():
    class NoCall:
        def complete_json(self, *_args, **_kwargs):
            raise AssertionError("clear market event must not call LLM")

    verdict = GraphNewsEligibilityReviewer(NoCall()).review(
        NewsEligibilityRequest(
            headline="Nifty recovers, but 432 stocks hit 52-week lows",
            preliminary_category=NewsCategory.OTHER,
        )
    )
    assert verdict.eligible
    assert verdict.category is NewsCategory.SECTOR_UPDATE


def test_unavailable_reviewer_fails_closed():
    class BrokenChat:
        def complete_json(self, *_args, **_kwargs):
            raise RuntimeError("budget exhausted")

    verdict = GraphNewsEligibilityReviewer(BrokenChat()).review(
        NewsEligibilityRequest(headline="Unclear event", preliminary_category=NewsCategory.OTHER)
    )
    assert not verdict.eligible
    assert verdict.reason == "REVIEW_UNAVAILABLE"


def test_trade_and_geopolitics_are_market_correlation_categories():
    assert NewsCategory.TRADE.value in MARKET_CATEGORIES
    assert NewsCategory.GEOPOLITICAL.value in MARKET_CATEGORIES


def test_approved_event_marker_is_required_and_recognized():
    assert not is_approved_event({"category": "TRADE"})
    assert is_approved_event(
        {
            "category": "TRADE",
            "eligibility": {"version": 1, "decision": "APPROVED", "source": "LLM"},
        }
    )
