"""Internal LLM eligibility review and graph-side news safety checks."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from stockgraph.domain.enums import NewsCategory

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

CLEAR_MARKET_EVENT_PATTERNS = (
    r"\bnifty\b|\bsensex\b|\bnse\b|\bbse\b",
    r"\bshares?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
    r"\bstock(?:s)?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
    r"\b(?:52[ -]?week|all[ -]?time)\s+(?:high|low)\b",
    r"\b(?:trading|trade)\s+volume\b",
)

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


class NewsEligibilityRequest(BaseModel):
    headline: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=4000)
    candidate_tickers: list[str] = Field(default_factory=list, max_length=100)
    preliminary_category: NewsCategory = NewsCategory.OTHER


class NewsEligibilityVerdict(BaseModel):
    eligible: bool
    category: NewsCategory | None = None
    reason: str = Field(min_length=1, max_length=500)


def hard_rejection_reason(headline: str, summary: str = "") -> str | None:
    text = f"{headline}\n{summary}"
    if MATERIAL_FINANCIAL_EVENT.search(text):
        return None
    for reason, patterns in HARD_REJECTION_PATTERNS:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return reason
    return None


def is_approved_event(payload: dict[str, Any]) -> bool:
    approval = payload.get("eligibility")
    if not isinstance(approval, dict) or approval.get("decision") != "APPROVED":
        return False
    try:
        return NewsCategory(str(payload.get("category") or "")) in APPROVED_CATEGORIES
    except ValueError:
        return False


def build_eligibility_prompt(request: NewsEligibilityRequest) -> str:
    return (
        "Classify ONE candidate article for an Indian equity market intelligence system.\n"
        f"HEADLINE: {request.headline}\nSUMMARY: {request.summary}\n"
        f"CANDIDATE NSE TICKERS: {', '.join(request.candidate_tickers) or 'none'}\n"
        f"PRELIMINARY CATEGORY: {request.preliminary_category.value}\n\n"
        "Approve only market-material company/stock, earnings, corporate-action, Reg-30, "
        "sector, commodity, macro, trade, or geopolitical news. Geopolitics must plausibly "
        "affect Indian markets, trade, commodities, supply chains, FX, rates, or a named "
        "company. Reject sport, cricket, celebrity, entertainment, lifestyle, unrelated crime, "
        "weather, and general politics. Return a category only when eligible.\n"
        'Return JSON: {"eligible": bool, "category": "EARNINGS|SECTOR_UPDATE|MACRO|'
        'TRADE|GEOPOLITICAL|REG30|COMMODITY|CORPORATE_ACTION|null, "reason": string}.'
    )


class GraphNewsEligibilityReviewer:
    """LLM reviewer owned by StockGraph; it performs no graph mutation."""

    def __init__(self, chat: Any) -> None:
        self._chat = chat

    def review(self, request: NewsEligibilityRequest) -> NewsEligibilityVerdict:
        hard_reason = hard_rejection_reason(request.headline, request.summary)
        if hard_reason and request.preliminary_category is not NewsCategory.REG30:
            return NewsEligibilityVerdict(eligible=False, reason=hard_reason)
        if request.preliminary_category is NewsCategory.REG30:
            return NewsEligibilityVerdict(
                eligible=True, category=NewsCategory.REG30, reason="REG30_DISCLOSURE"
            )
        text = f"{request.headline}\n{request.summary}"
        if any(
            re.search(pattern, text, flags=re.IGNORECASE) for pattern in CLEAR_MARKET_EVENT_PATTERNS
        ):
            return NewsEligibilityVerdict(
                eligible=True,
                category=NewsCategory.SECTOR_UPDATE,
                reason="CLEAR_MARKET_EVENT",
            )
        try:
            verdict = self._chat.complete_json(
                build_eligibility_prompt(request), NewsEligibilityVerdict
            )
            if isinstance(verdict, dict):
                verdict = NewsEligibilityVerdict.model_validate(verdict)
            if not isinstance(verdict, NewsEligibilityVerdict):
                raise ValueError("LLM did not return an eligibility verdict")
            if not verdict.eligible or verdict.category not in APPROVED_CATEGORIES:
                return NewsEligibilityVerdict(
                    eligible=False, reason=verdict.reason or "LLM_REJECTED"
                )
            return verdict
        except Exception:
            # The upstream gate must never mistake an unavailable reviewer for
            # approval. Do not expose provider/internal details to a caller.
            return NewsEligibilityVerdict(eligible=False, reason="REVIEW_UNAVAILABLE")
