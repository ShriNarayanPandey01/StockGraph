"""Submit manually supplied news through the normal durable outbox flow."""

from dataclasses import replace
from hashlib import sha256

from upstox_service.application.ingestion.news_eligibility import NewsEligibilityGate
from upstox_service.application.ports import ManualNewsStorePort
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.models import EntityKind, ManualNewsInput
from upstox_service.domain.news import ProviderFetchResult, ProviderStatus, StagedNewsItem


class ManualNewsSubmissionService:
    def __init__(self, repository: ManualNewsStorePort, eligibility: NewsEligibilityGate) -> None:
        self._repository = repository
        self._eligibility = eligibility

    async def submit(self, request: ManualNewsInput) -> dict:
        mentioned = list(dict.fromkeys([*request.tickers, *request.ticker_sentiment]))
        unknown = [
            ticker
            for ticker in mentioned
            if await self._repository.get_entity(EntityKind.STOCK.value, ticker) is None
        ]
        if unknown:
            raise ValueError(f"Unknown registered ticker(s): {', '.join(unknown)}")
        if set(request.ticker_sentiment) - set(request.tickers):
            raise ValueError("ticker_sentiment keys must also be present in tickers")

        external_id = (
            request.external_id
            or "manual-" + sha256(request.source_url.encode("utf-8")).hexdigest()[:40]
        )
        article = NewsArticle(
            external_id=external_id,
            headline=request.headline,
            summary=request.summary,
            source_url=request.source_url,
            source=request.source,
            published_at=request.published_at,
            category=request.category,
            sentiment=request.sentiment,
            tickers=tuple(request.tickers),
            ticker_sentiment=request.ticker_sentiment,
        )
        decision = await self._eligibility.decide(article)
        if not decision.approved or decision.category is None:
            raise ValueError(f"Manual news rejected: {decision.reason}")
        raw_payload = request.model_dump(mode="json", exclude_none=True)
        raw_payload["external_id"] = external_id
        result = ProviderFetchResult(
            provider_id="MANUAL",
            status=ProviderStatus.AVAILABLE,
            articles=(replace(article, category=decision.category),),
            staged=(
                StagedNewsItem(external_id, request.published_at, request.source_url, raw_payload),
            ),
            approvals={external_id: (decision.source, decision.reason)},
        )
        changed = await self._repository.commit_news(result)
        return {
            "external_id": external_id,
            "state": "queued" if changed else "unchanged",
            "eligibility": {"source": decision.source, "reason": decision.reason},
        }
