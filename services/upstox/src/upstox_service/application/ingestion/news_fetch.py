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

`NewsProviderFactory` is the composition root: the only place that names
concrete provider classes. Everything else depends on the
`NewsProviderAdapter` abstraction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from upstox_service.adapters.providers.http_client import ResilientHttpClient
from upstox_service.adapters.providers.news.adapters import (
    AlphaVantageNewsAdapter,
    CurrentsNewsAdapter,
    FmpNewsAdapter,
    MarketauxNewsAdapter,
    NewsProviderAdapter,
    ProviderFetchResult,
    ProviderStatus,
)
from upstox_service.application.ingestion.news_eligibility import (
    EligibilityReviewer,
    NewsEligibilityGate,
)
from upstox_service.config.settings import settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.resolver import CanonicalEntityResolver

logger = logging.getLogger(__name__)

# Provider id -> (adapter class, settings attribute holding the API key).
_PROVIDER_REGISTRY: dict[str, tuple[type[NewsProviderAdapter], str]] = {
    "marketaux": (MarketauxNewsAdapter, "marketaux_api_key"),
    "currents": (CurrentsNewsAdapter, "currents_api_key"),
    "alphavantage": (AlphaVantageNewsAdapter, "alpha_vantage_api_key"),
    "fmp": (FmpNewsAdapter, "fmp_api_key"),
}


class RequestQuotaBudget:
    """Per-provider daily request budget, backed by Redis counters.

    The counter key format is an implementation detail and stays private;
    callers only ask `try_consume()`.
    """

    def __init__(self, redis_client: Any | None, daily_cap_override: int | None = None) -> None:
        self._redis = redis_client
        self._override = daily_cap_override

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def _key(self, provider_id: str) -> str:
        return f"newsquota:{provider_id}:{datetime.now(UTC):%Y%m%d}"

    def effective_cap(self, provider_cap: int) -> int:
        """The cap that applies to a provider: the operator override, else
        the provider's own declared plan limit."""
        if self._override is not None:
            return self._override
        return provider_cap

    def try_consume(self, provider_id: str, provider_cap: int) -> bool:
        """Consume one request from today's budget. False when exhausted.

        With no Redis the budget cannot be enforced, so the request is
        allowed through: an unavailable cache must not silently stop
        ingestion.
        """
        if self._redis is None:
            return True
        cap = self.effective_cap(provider_cap)
        key = self._key(provider_id)
        try:
            used = int(self._redis.incr(key))
            if used == 1:
                self._redis.expire(key, self._seconds_until_utc_midnight())
            if used > cap:
                # Give the slot back so the counter reflects real usage.
                self._redis.decr(key)
                return False
        except Exception:  # noqa: BLE001 - fail open, never stop ingestion
            logger.warning("Quota counter unavailable for %s", provider_id)
            return False
        return True

    def consumed(self, provider_id: str) -> int:
        """Requests already consumed today for a provider."""
        if self._redis is None:
            return 0
        try:
            raw = self._redis.get(self._key(provider_id))
        except Exception:  # noqa: BLE001
            return 0
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _seconds_until_utc_midnight() -> int:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((tomorrow - now).total_seconds()))


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
        adapters: list[NewsProviderAdapter],
        timescale_repo: Any | None = None,
        quota: RequestQuotaBudget | None = None,
        eligibility_reviewer: EligibilityReviewer | None = None,
    ) -> None:
        self._adapters = sorted(adapters, key=lambda a: a.priority)
        self._timescale = timescale_repo
        self._quota = quota or RequestQuotaBudget(
            None, daily_cap_override=settings.news_daily_request_cap
        )
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
                adapter.fetch, window, limit=settings.news_max_articles_per_run
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
                item = adapter.replay_item(row["payload"])
                pairs = adapter._normalize([item])
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
        floor = now - timedelta(minutes=settings.news_lookback_minutes)
        if self._timescale is None:
            return floor
        try:
            watermark = await self._timescale.get_news_watermark(provider_id)
        except Exception as exc:  # noqa: BLE001 - never block ingestion
            logger.warning("Watermark read failed for %s: %s", provider_id, exc)
            return floor
        if watermark is None:
            return floor
        bounded = now - timedelta(minutes=settings.news_max_window_minutes)
        return max(bounded, watermark - timedelta(minutes=settings.news_lookback_minutes))

    async def _stage(self, result: ProviderFetchResult) -> None:
        """Stage raw provider payloads immutably BEFORE any graph write."""
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
                key = f"rejected:{decision.reason or 'UNKNOWN'}"
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


def build_news_adapters(
    resolver: CanonicalEntityResolver | None = None,
    http_client: ResilientHttpClient | None = None,
) -> list[NewsProviderAdapter]:
    """Composition root: build the enabled provider adapters, in priority order.

    This is the ONLY place that names the concrete provider classes, so
    adding or removing a provider never touches the fetch service.
    """
    resolver = resolver or CanonicalEntityResolver.from_seed()
    adapters: list[NewsProviderAdapter] = []
    for raw_name in settings.news_providers_enabled.split(","):
        name = raw_name.strip().lower()
        entry = _PROVIDER_REGISTRY.get(name)
        if entry is None:
            logger.warning("Unknown news provider %r - ignored", raw_name)
            continue
        adapter_cls, key_attr = entry
        adapters.append(
            adapter_cls(
                api_key=getattr(settings, key_attr),
                resolver=resolver,
                http_client=http_client,
            )
        )
    return sorted(adapters, key=lambda a: a.priority)


class CommittedNewsFetchService(NewsFetchService):
    """Fail closed on SQL staging failures; commit the graph outbox atomically."""

    async def _stage(self, result: ProviderFetchResult) -> None:
        if self._timescale is None:
            raise RuntimeError("News ingestion requires a durable SQL repository")
        await self._timescale.commit_news(result)

    async def _advance_watermark(self, provider_id: str, result: ProviderFetchResult) -> None:
        # commit_news advanced this watermark in the same transaction as its outbox.
        return None
