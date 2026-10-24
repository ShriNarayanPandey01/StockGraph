from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from upstox_service.adapters.providers.news.adapters import (
    ProviderFetchResult,
    ProviderStatus,
    StagedNewsItem,
)
from upstox_service.adapters.repositories.timescale.stock_data import StockDataRepository
from upstox_service.application.ingestion.checkpoints import collect_checkpoints, recovery_dates
from upstox_service.application.ingestion.news_eligibility import NewsEligibilityGate
from upstox_service.application.ingestion.news_fetch import (
    CommittedNewsFetchService,
    NewsFetchService,
)
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory
from upstox_service.runtime.scheduler import PersistentSchedule


@pytest.mark.parametrize(
    "headline",
    [
        "PVR INOX quarterly profit rises on strong film releases",
        "Trent reports quarterly earnings growth in its fashion business",
        "TCS profits match analyst estimates",
    ],
)
async def test_sector_vocabulary_does_not_veto_financial_materiality(headline):
    item = NewsArticle(
        external_id="id",
        headline=headline,
        summary="",
        source_url="https://example.test",
        source="RSS",
        published_at=datetime.now(UTC),
        category=NewsCategory.EARNINGS,
    )
    assert (await NewsEligibilityGate().decide(item)).approved


async def test_review_unavailable_retains_raw_without_authorizing_graph_event():
    reviewer = SimpleNamespace(review=AsyncMock(return_value=None))
    item = NewsArticle(
        external_id="pending",
        headline="Unclear development",
        summary="",
        source_url="https://example.test",
        source="RSS",
        published_at=datetime.now(UTC),
        category=NewsCategory.OTHER,
    )
    raw = StagedNewsItem(
        item.external_id, item.published_at, item.source_url, {"title": item.headline}
    )
    result = ProviderFetchResult(
        provider_id="RSS",
        status=ProviderStatus.AVAILABLE,
        articles=(item,),
        staged=(raw,),
        watermark_at=item.published_at,
    )
    filtered = await NewsFetchService([], eligibility_reviewer=reviewer)._filter_eligible(result)
    assert filtered.staged == (raw,)
    assert not filtered.articles and not filtered.approvals
    assert filtered.eligibility_counts["deferred:REVIEW_UNAVAILABLE"] == 1


async def test_pending_review_replays_without_a_provider_request():
    item = NewsArticle(
        external_id="pending",
        headline="Export policy revised",
        summary="",
        source_url="https://example.test",
        source="RSS",
        published_at=datetime.now(UTC),
        category=NewsCategory.OTHER,
    )
    raw = StagedNewsItem(item.external_id, item.published_at, item.source_url, {})
    from upstox_service.application.ingestion.news_eligibility import EligibilityDecision

    reviewer = SimpleNamespace(
        review=AsyncMock(
            return_value=EligibilityDecision(True, NewsCategory.TRADE, "LLM", "Trade policy")
        )
    )
    repo = SimpleNamespace(
        pending_news_reviews=AsyncMock(
            return_value=[{"provider_id": "RSS", "external_id": item.external_id, "payload": {}}]
        ),
        commit_news=AsyncMock(),
        finish_news_review=AsyncMock(),
    )
    # Disabled live fetch still permits replay of already-paid raw data.
    adapter = SimpleNamespace(
        provider_id="RSS",
        priority=0,
        is_configured=False,
        replay_item=lambda raw: raw,
        _normalize=lambda raw: [(item, raw_item)],
    )
    raw_item = raw
    await CommittedNewsFetchService([adapter], repo, eligibility_reviewer=reviewer).fetch_cycle()
    assert repo.commit_news.await_count == 1
    committed = repo.commit_news.await_args.args[0]
    assert committed.articles[0].category is NewsCategory.TRADE
    repo.finish_news_review.assert_awaited_once_with("RSS", item.external_id)


def test_recovery_sweeps_revisions_and_recovers_missed_days_with_a_bound():
    today = date(2026, 10, 23)
    assert date(2026, 10, 20) in recovery_dates(today, date(2026, 10, 19), 1, 30)
    result = recovery_dates(today, date(2020, 1, 1), 10, 30)
    assert min(result) >= today - timedelta(days=30)
    assert all(value.weekday() < 5 for value in result)
    assert date(2026, 10, 14) in recovery_dates(today, today, 10, 30)


async def test_empty_vendor_response_uses_official_close(monkeypatch):
    import upstox_service.application.ingestion.checkpoints as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 23, 14, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", Clock)
    vendor = SimpleNamespace(
        get=AsyncMock(return_value={"data": {"candles": []}}), close=AsyncMock()
    )
    monkeypatch.setattr(module, "UpstoxClient", lambda *args, **kwargs: vendor)
    monkeypatch.setattr(
        module,
        "ResilientHttpClient",
        lambda: SimpleNamespace(
            fetch=lambda url: SimpleNamespace(
                ok=True,
                text="SYMBOL,CLOSE_PRICE,TTL_TRD_QNTY,DELIV_PER,DELIV_QTY\nABC,100,1000,60,600",
            )
        ),
    )
    repo = SimpleNamespace(
        list_catalog=AsyncMock(return_value=[{"payload": {"ticker": "ABC", "isin": "isin"}}]),
        get_watermark=AsyncMock(return_value=None),
        stage_vendor_quote=AsyncMock(),
        upsert_daily_metrics=AsyncMock(),
        advance_watermark=AsyncMock(),
    )
    config = SimpleNamespace(
        upstox_analytics_token="",
        upstox_api_base_url="unused",
        upstox_timeout_seconds=1,
        upstox_max_retries=0,
        vendor_revision_lookback_days=0,
    )
    assert await collect_checkpoints(repo, config, "CLOSE") == "DEGRADED"
    metric = repo.upsert_daily_metrics.await_args.args[0][0]
    assert metric["close_price"] == 100 and metric["delivery_pct"] == 60
    assert metric["vendor_id"] == "NSE_BHAVCOPY"
    vendor.close.assert_awaited_once()


async def test_scheduler_keeps_persisted_due_time_on_definition_refresh():
    class DurableMemory(MemoryJobStore):
        def shutdown(self):
            pass

    store = DurableMemory()
    due = datetime.now(UTC) - timedelta(seconds=120)

    async def task():
        pass

    first = PersistentSchedule(jobstores={"default": store}, timezone="UTC")
    first.add_job(task, "interval", hours=1, id="checkpoint", next_run_time=due)
    first.start(paused=True)
    first.shutdown(wait=False)
    import asyncio

    await asyncio.sleep(0)
    second = PersistentSchedule(jobstores={"default": store}, timezone="UTC")
    second.add_job(task, "interval", hours=1, id="checkpoint", replace_existing=True)
    second.start(paused=True)
    try:
        assert second.get_job("checkpoint").next_run_time == due
    finally:
        second.shutdown(wait=False)
        await asyncio.sleep(0)


class Context(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


async def test_shareholding_snapshot_handles_a_b_a_and_removed_categories():
    import json

    class Connection:
        def __init__(self):
            self.snapshots = []

        def transaction(self):
            return Context(self)

        async def execute(self, query, *args):
            if "INSERT INTO stock_shareholding_snapshots" in query:
                self.snapshots.append({"payload": json.loads(args[2]), "vendor_as_of": args[1]})

        async def executemany(self, *args):
            pass

        async def fetchrow(self, query, *args):
            return max(self.snapshots, key=lambda row: row["vendor_as_of"])

    conn = Connection()
    owner = SimpleNamespace(
        connect=AsyncMock(return_value=SimpleNamespace(acquire=lambda: Context(conn)))
    )
    repo = StockDataRepository(owner)
    a = [
        {"period": "Sep 2026", "category": "promoter", "percentage": 50},
        {"period": "Sep 2026", "category": "public", "percentage": 50},
    ]
    b = [{"period": "Sep 2026", "category": "promoter", "percentage": 60}]
    stamp = datetime.now(UTC)
    for index, rows in enumerate((a, b, a)):
        await repo.save_shareholding("isin", rows, stamp + timedelta(seconds=index))
        current = await repo.get_shareholding("isin")
        assert [
            {key: value for key, value in row.items() if not key.startswith("vendor_")}
            for row in current["rows"]
        ] == rows
    assert len(conn.snapshots) == 3
