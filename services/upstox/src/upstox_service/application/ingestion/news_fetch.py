"""News fetch orchestration: quota, watermark, raw staging, provider fan-out.

`NewsFetchService.fetch_cycle()` is the only thing the scheduler needs to
call to pull news. It owns four policies that must not leak into the
adapters or the graph layer:

1. **Daily request budget.** Providers meter requests, not articles. The
   budget is enforced per provider per UTC day, so a run that would
   exceed the plan's ceiling skips that provider (reported as
   `QUOTA_EXHAUSTED`) instead of silently burning quota and getting
   throttled.
2. **Incremental fetch window.** The watermark says how far we have got.
   The window is `watermark - lookback` (the lookback covers the measured
   60-90 minute provider index lag) bounded by a hard maximum, so a long
   outage cannot trigger an unbounded backfill.
3. **Raw staging before graph writes.** Every provider payload is staged
   immutably in `news_raw` BEFORE it can reach the graph, so LLM routing
   and embedding can be replayed without re-spending metered quota
   (Rule 7).
4. **Provider priority.** Adapters are ordered by priority: the provider
   that gives the richest record (ticker + sentiment) fetches first, so it
   claims the L1 URL slot and becomes the canonical NewsEvent.

The runtime composes concrete providers; this service consumes application ports.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from upstox_service.application.ingestion.news_eligibility import (
    EligibilityReviewer,
    NewsEligibilityGate,
)
from upstox_service.application.ports import (
    NewsCommitPort,
    NewsPersistencePort,
    NewsProviderPort,
    NewsReviewStorePort,
    NewsStagingPort,
    RequestQuotaPort,
)
from upstox_service.config.settings import Settings, settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.news import ProviderFetchResult, ProviderStatus

logger = logging.getLogger(__name__)


class UnlimitedQuota:
    def try_consume(self, provider_id: str, provider_cap: int) -> bool:
        return True

    def consumed(self, provider_id: str) -> int:
        return 0


@dataclass(frozen=True)
class FetchCycleResult:
    """Outcome of one fetch cycle across all enabled providers."""

    articles: tuple[NewsArticle, ...] = ()
    results: tuple[ProviderFetchResult, ...] = ()

    @property
    def by_provider(self) -> dict[str, ProviderFetchResult]:
        return {r.provider_id: r for r in self.results}

    @property
    def degraded(self) -> tuple[ProviderFetchResult, ...]:
        """Providers that did not contribute articles this cycle."""
        return tuple(r for r in self.results if not r.articles)

    @property
    def eligibility_metrics(self) -> dict[str, int]:
        """Aggregate counts only; rejected article content is never retained."""
        totals: dict[str, int] = {}
        for result in self.results:
            for key, value in result.eligibility_counts.items():
                totals[key] = totals.get(key, 0) + value
        return totals


class NewsFetchService:
    """Run one bounded fetch cycle across the configured news providers."""

    def __init__(
        self,
        adapters: list[NewsProviderPort],
        timescale_repo: NewsStagingPort | None = None,
        quota: RequestQuotaPort | None = None,
        eligibility_reviewer: EligibilityReviewer | None = None,
        *,
        persistence: NewsPersistencePort | None = None,
        config: Settings | None = None,
    ) -> None:
        self._adapters = sorted(adapters, key=lambda a: a.priority)
        self._timescale = timescale_repo
        self._quota = quota if quota is not None else UnlimitedQuota()
        self._persistence = persistence
        self._config = config or settings
        self._eligibility = NewsEligibilityGate(eligibility_reviewer)
        # Providers whose plan does not include the endpoint we need. Re-probing
        # them every cycle would burn daily quota on a request that can never
        # succeed, so the verdict is remembered for this process's lifetime.
        self._paywalled: set[str] = set()

    async def fetch_cycle(self, since: datetime | None = None) -> FetchCycleResult:
        """Fetch from every enabled provider and return the combined result.

        `since` overrides the per-provider watermark window (used by tests
        and by a manual backfill run).
        """
        results: list[ProviderFetchResult] = []
        articles: list[NewsArticle] = []

        for adapter in self._adapters:
            provider_id = adapter.provider_id
            if not adapter.is_configured:
                results.append(
                    ProviderFetchResult(
                        provider_id=provider_id,
                        status=ProviderStatus.NOT_CONFIGURED,
                        error="No API key configured",
                    )
                )
                continue

            if provider_id in self._paywalled:
                results.append(
                    ProviderFetchResult(
                        provider_id=provider_id,
                        status=ProviderStatus.DEGRADED_PAYWALL,
                        error="Endpoint not included in this plan; not retried",
                    )
                )
                continue

            if not self._quota.try_consume(provider_id, adapter.plan_daily_cap):
                logger.info(
                    "%s: daily request budget exhausted (%s used)",
                    provider_id,
                    self._quota.consumed(provider_id),
                )
                results.append(
                    ProviderFetchResult(
                        provider_id=provider_id,
                        status=ProviderStatus.QUOTA_EXHAUSTED,
                        error="Daily request budget exhausted",
                    )
                )
                continue

            window = since if since is not None else await self._window_for(provider_id)
            result = await asyncio.to_thread(
                adapter.fetch, window, limit=self._config.news_max_articles_per_run
            )
            if result.status is ProviderStatus.DEGRADED_PAYWALL:
                self._paywalled.add(provider_id)
            if result.status is ProviderStatus.AVAILABLE:
                result = await self._filter_eligible(result)
            if result.status is ProviderStatus.AVAILABLE and result.watermark_at is not None:
                await self._stage(result)
                await self._advance_watermark(provider_id, result)
            results.append(result)
            articles.extend(result.articles)

        return FetchCycleResult(articles=tuple(articles), results=tuple(results))

    async def replay_staged(self, limit: int = 500) -> FetchCycleResult:
        """Rebuild the article set from the STAGED payloads.

        A replay re-runs dedup, LLM routing and correlation over an
        already-fetched corpus: no provider request is made, so no metered
        quota is spent. This is how a routing change is applied to the
        existing corpus (and how a routing bug is repaired) without
        waiting for the next fetch and without burning provider limits.
        """
        if self._timescale is None:
            return FetchCycleResult()
        try:
            rows = await self._timescale.get_staged_news(limit=limit)
        except Exception as exc:  # noqa: BLE001 - never block ingestion
            logger.warning("Staged replay read failed: %s", exc)
            return FetchCycleResult()

        by_provider = {a.provider_id: a for a in self._adapters}
        articles: list[NewsArticle] = []
        results: list[ProviderFetchResult] = []
        per_provider: dict[str, list[NewsArticle]] = {}

        for row in rows:
            adapter = by_provider.get(row["provider_id"])
            if adapter is None:
                continue
            try:
                try:
                    pairs = adapter.normalize_staged(row["payload"])
                except (ValueError, TypeError, KeyError):
                    logger.warning(
                        "Pending review cannot normalize provider=%s", row["provider_id"]
                    )
                    await self._timescale.defer_news_review(
                        row["provider_id"], row["external_id"]
                    )
                    continue
            except Exception as exc:  # noqa: BLE001 - one bad payload is skipped
                logger.warning("Replay failed for %s: %s", row["external_id"], exc)
                continue
            for article, _staged in pairs:
                decision = await self._eligibility.decide(article)
                if not decision.approved or decision.category is None:
                    continue
                approved = replace(article, category=decision.category)
                articles.append(approved)
                per_provider.setdefault(row["provider_id"], []).append(approved)

        for provider_id, provider_articles in per_provider.items():
            results.append(
                ProviderFetchResult(
                    provider_id=provider_id,
                    status=ProviderStatus.AVAILABLE,
                    articles=tuple(provider_articles),
                    requests_used=0,
                )
            )
        logger.info(
            "Replayed %d staged article(s) across %d provider(s)",
            len(articles),
            len(per_provider),
        )
        return FetchCycleResult(articles=tuple(articles), results=tuple(results))

    async def _window_for(self, provider_id: str) -> datetime:
        """The `since` instant for a provider: watermark minus the lookback,
        bounded by the hard maximum window."""
        now = datetime.now(UTC)
        floor = now - timedelta(minutes=self._config.news_lookback_minutes)
        if self._timescale is None:
            return floor
        try:
            watermark = await self._timescale.get_news_watermark(provider_id)
        except Exception as exc:  # noqa: BLE001 - never block ingestion
            logger.warning("Watermark read failed for %s: %s", provider_id, exc)
            return floor
        if watermark is None:
            return floor
        bounded = now - timedelta(minutes=self._config.news_max_window_minutes)
        return max(bounded, watermark - timedelta(minutes=self._config.news_lookback_minutes))

    async def _stage(self, result: ProviderFetchResult) -> None:
        """Stage raw provider payloads immutably BEFORE any graph write."""
        if self._persistence is not None:
            await self._persistence.stage(result)
            return
        if self._timescale is None:
            return
        for item in result.staged:
            try:
                await self._timescale.stage_news_raw(
                    provider_id=result.provider_id,
                    external_id=item.external_id,
                    payload=item.payload,
                    published_at=item.published_at,
                    source_url=item.source_url,
                )
            except Exception as exc:  # noqa: BLE001 - staging must not break ingestion
                logger.warning(
                    "Staging failed for %s/%s: %s", result.provider_id, item.external_id, exc
                )

    async def _advance_watermark(self, provider_id: str, result: ProviderFetchResult) -> None:
        """Advance the watermark to the newest article seen. Never moves back."""
        if self._persistence is not None:
            await self._persistence.advance(provider_id, result)
            return
        if self._timescale is None or result.watermark_at is None:
            return
        try:
            await self._timescale.advance_news_watermark(provider_id, result.watermark_at)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Watermark advance failed for %s: %s", provider_id, exc)

    async def _filter_eligible(self, result: ProviderFetchResult) -> ProviderFetchResult:
        """Keep SQL/outbox input one-to-one with approved raw staging only."""
        staged_by_id = {item.external_id: item for item in result.staged}
        approved_articles: list[NewsArticle] = []
        approved_staged = []
        approvals: dict[str, tuple[str, str]] = {}
        counts: dict[str, int] = {"fetched": len(result.articles)}
        for article in result.articles:
            stageable = staged_by_id.get(article.external_id)
            if stageable is None:
                counts["rejected:MALFORMED"] = counts.get("rejected:MALFORMED", 0) + 1
                continue
            decision = await self._eligibility.decide(article)
            if not decision.approved or decision.category is None:
                if decision.reason == "REVIEW_UNAVAILABLE":
                    approved_staged.append(stageable)
                key = f"{'deferred' if decision.reason == 'REVIEW_UNAVAILABLE' else 'rejected'}:{decision.reason or 'UNKNOWN'}"
                counts[key] = counts.get(key, 0) + 1
                continue
            approved = replace(article, category=decision.category)
            approved_articles.append(approved)
            approved_staged.append(stageable)
            approvals[approved.external_id] = (decision.source, decision.reason)
            key = f"approved:{decision.source.lower()}"
            counts[key] = counts.get(key, 0) + 1
        return replace(
            result,
            articles=tuple(approved_articles),
            staged=tuple(approved_staged),
            approvals=approvals,
            eligibility_counts=counts,
        )


class CommittedNewsPersistence:
    """Commit raw news, watermark and outbox in the repository transaction."""

    def __init__(self, repository: NewsCommitPort) -> None:
        self._repository = repository

    async def stage(self, result: ProviderFetchResult) -> None:
        await self._repository.commit_news(result)

    async def advance(self, provider_id: str, result: ProviderFetchResult) -> None:
        # commit_news advanced the watermark atomically.
        return None


class PendingNewsReviewService:
    def __init__(self, repository: NewsReviewStorePort, providers: list[NewsProviderPort],
                 eligibility: NewsEligibilityGate, *, limit: int) -> None:
        self._repository = repository
        self._providers = {provider.provider_id: provider for provider in providers}
        self._eligibility = eligibility
        self._limit = limit

    async def replay_pending(self) -> None:
        for row in await self._repository.pending_news_reviews(limit=self._limit):
            adapter = self._providers.get(row["provider_id"])
            if adapter is None:
                continue
            pairs = adapter.normalize_staged(row["payload"])
            if not pairs:
                await self._repository.finish_news_review(row["provider_id"], row["external_id"])
                continue
            article, staged = pairs[0]
            decision = await self._eligibility.decide(article)
            if decision.reason == "REVIEW_UNAVAILABLE":
                await self._repository.defer_news_review(row["provider_id"], row["external_id"])
                continue
            if decision.approved and decision.category is not None:
                await self._repository.commit_news(ProviderFetchResult(
                    provider_id=row["provider_id"], status=ProviderStatus.AVAILABLE,
                    articles=(replace(article, category=decision.category),), staged=(staged,),
                    approvals={article.external_id: (decision.source, decision.reason)},
                ))
            await self._repository.finish_news_review(row["provider_id"], row["external_id"])


class NewsIngestionCoordinator:
    def __init__(self, fetch: NewsFetchService, reviews: PendingNewsReviewService) -> None:
        self._fetch = fetch
        self._reviews = reviews

    async def fetch_cycle(self, **kwargs) -> FetchCycleResult:
        await self._reviews.replay_pending()
        return await self._fetch.fetch_cycle(**kwargs)
