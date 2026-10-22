"""Opt-in real SQL smoke test, entirely rolled back in an isolated schema.

RUN_DATA_SQL_TESTS=1 pytest services/upstox/tests/test_sql_transactions.py
Uses TIMESCALE_DSN without logging it; never touches existing application rows.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
from upstox_service.adapters.providers.news.adapters import (
    ProviderFetchResult,
    ProviderStatus,
    StagedNewsItem,
)
from upstox_service.adapters.repositories.timescale.catalog import (
    CATALOG_DDL,
    DataRepository,
)
from upstox_service.adapters.repositories.timescale.numeric import DDL_SCHEMA
from upstox_service.config.settings import Settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory
from upstox_service.domain.models import CompanyBundle, EntityKind, StockRegistration


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DATA_SQL_TESTS") != "1", reason="Opt-in SQL integration test")
async def test_real_sql_catalog_jobs_outbox_and_rollback():
    conn = await asyncpg.connect(Settings().timescale_dsn)
    transaction = conn.transaction()
    await transaction.start()
    schema = "data_test_" + uuid4().hex
    try:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET LOCAL search_path TO {schema}, public")
        await conn.execute(DDL_SCHEMA)
        await conn.execute(CATALOG_DDL)

        class ConnectionPool:
            @asynccontextmanager
            async def acquire(self):
                yield conn

        repo = DataRepository()
        repo._pool = ConnectionPool()
        assert await repo.bootstrap() == 29
        assert await repo.bootstrap() == 0
        assert len(await repo.list_catalog("Stock")) == 5
        rows = await conn.fetch("SELECT event FROM graph_outbox ORDER BY sequence_id")
        kinds = [json.loads(r["event"])["payload"]["kind"] for r in rows]
        assert kinds[:5] == ["Commodity"] * 5
        assert kinds[-5:] == ["Stock"] * 5

        macro = {"id": "TEST_MACRO", "name": "Test macro", "description": "First state"}
        first = await repo.upsert_entity(EntityKind.MACRO, macro)
        unchanged = await repo.upsert_entity(EntityKind.MACRO, macro)
        changed = await repo.upsert_entity(
            EntityKind.MACRO, {**macro, "description": "Revised state"}
        )
        assert (first["revision"], unchanged["revision"], changed["revision"]) == (1, 1, 2)
        assert unchanged["changed"] is False
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM entity_catalog_versions WHERE entity_id='TEST_MACRO'"
            )
            == 2
        )

        enqueue = repo._enqueue
        repo._enqueue = AsyncMock(side_effect=RuntimeError("simulated outbox error"))
        with pytest.raises(RuntimeError, match="simulated outbox error"):
            await repo.upsert_entity(
                EntityKind.COMMODITY, {"id": "ROLLBACK_TEST", "name": "Must roll back"}
            )
        repo._enqueue = enqueue
        assert await repo.get_entity("Commodity", "ROLLBACK_TEST") is None

        job = await repo.create_job(StockRegistration(query="NEWCO"))
        claimed = await repo.claim_job(600, 3)
        assert claimed["job_id"] == job["job_id"]
        await repo.commit_company(
            job["job_id"],
            CompanyBundle(
                entity={"ticker": "NEWCO", "name": "New Company", "isin": "INE123456789"},
                raw={"profile": "example"},
            ),
        )
        assert (await repo.get_job(job["job_id"]))["state"] == "graph_processing"
        assert (await repo.get_entity("Stock", "NEWCO"))["name"] == "New Company"
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM stock_fundamentals_raw WHERE ticker=$1", "NEWCO"
            )
            == 1
        )

        expired = await repo.create_job(StockRegistration(query="EXPIRED"))
        first_attempt = await repo.claim_job(600, 3)
        assert first_attempt["job_id"] == expired["job_id"]
        assert await repo.renew_job(expired["job_id"], first_attempt["attempts"], 600)
        await conn.execute(
            "UPDATE registration_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=$1",
            UUID(expired["job_id"]),
        )
        assert not await repo.renew_job(expired["job_id"], first_attempt["attempts"], 600)
        with pytest.raises(RuntimeError, match="stale commit rejected"):
            await repo.commit_company(
                expired["job_id"], CompanyBundle(entity={"ticker": "EXPIRED"}, raw={}), attempt=1
            )
        second_attempt = await repo.claim_job(600, 3)
        assert second_attempt["attempts"] == 2
        await repo.fail_job(
            expired["job_id"], "Stale failure must not overwrite retry", False, attempt=1
        )
        assert (await repo.get_job(expired["job_id"]))["state"] == "data_collection"
        assert await repo.get_entity("Stock", "EXPIRED") is None

        today = datetime.now(UTC).date()
        await repo.upsert_daily_metrics(
            [
                {
                    "trade_date": today,
                    "session_type": "CLOSE",
                    "ticker": "NEWCO",
                    "close_price": 123.45,
                    "vendor_id": "UPSTOX",
                    "vendor_as_of": datetime.now(UTC),
                    "delivery_pct": 54.3,
                    "delivery_vendor_id": "NSE_BHAVCOPY",
                    "delivery_vendor_as_of": datetime.now(UTC),
                }
            ]
        )
        numeric = await repo.get_daily_range("NEWCO", today, today)
        assert numeric[0]["vendor_id"] == "UPSTOX"
        assert numeric[0]["delivery_vendor_id"] == "NSE_BHAVCOPY"
        await repo.advance_watermark("UPSTOX", "NEWCO", "CLOSE", today)
        from datetime import timedelta

        await repo.advance_watermark("UPSTOX", "NEWCO", "CLOSE", today - timedelta(days=1))
        assert await repo.get_watermark("UPSTOX", "NEWCO", "CLOSE") == today

        article = NewsArticle(
            "article-1",
            "Oil prices increase",
            "Oil prices increase",
            "https://example.com/a",
            "MEDIA",
            datetime.now(UTC),
            NewsCategory.COMMODITY,
        )
        result = ProviderFetchResult(
            provider_id="TEST",
            status=ProviderStatus.AVAILABLE,
            articles=(article,),
            staged=(
                StagedNewsItem(
                    article.external_id,
                    article.published_at,
                    article.source_url,
                    {"headline": article.headline},
                ),
            ),
            watermark_at=article.published_at,
            approvals={article.external_id: ("RULES", "CLEAR_COMMODITY")},
        )
        assert await repo.commit_news(result) == 1
        assert await repo.commit_news(result) == 0
        assert await conn.fetchval("SELECT count(*) FROM normalized_news") == 1
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM graph_outbox WHERE event->>'kind'='news.received'"
            )
            == 1
        )

        publisher = AsyncMock()
        publisher.publish.side_effect = RuntimeError("offline")
        assert await repo.publish_outbox(publisher) == 0
        assert (
            await conn.fetchval("SELECT count(*) FROM graph_outbox WHERE published_at IS NOT NULL")
            == 0
        )
        publisher.publish.side_effect = None
        assert await repo.publish_outbox(publisher) == 33
        assert await repo.publish_outbox(publisher) == 0
    finally:
        await transaction.rollback()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DATA_SQL_TESTS") != "1", reason="Opt-in SQL integration test")
async def test_sql_provider_refresh_preserves_existing_curated_stock_profile():
    conn = await asyncpg.connect(Settings().timescale_dsn)
    transaction = conn.transaction()
    await transaction.start()
    schema = "data_refresh_test_" + uuid4().hex
    try:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET LOCAL search_path TO {schema}, public")
        await conn.execute(DDL_SCHEMA)
        await conn.execute(CATALOG_DDL)

        class ConnectionPool:
            @asynccontextmanager
            async def acquire(self):
                yield conn

        repo = DataRepository()
        repo._pool = ConnectionPool()
        await repo.bootstrap()
        curated = await repo.get_entity("Stock", "RELIANCE")
        curated.update(
            strengths=["Integrated refining value chain"],
            business_exclusions=["Not a pure upstream oil producer"],
        )
        await repo.upsert_entity(EntityKind.STOCK, curated)

        request = StockRegistration(query="RELIANCE")
        job = await repo.create_job(request)
        claim = await repo.claim_job(600, 3)
        incoming = {
            "ticker": "RELIANCE",
            "isin": curated["isin"],
            "name": "Reliance Industries Limited - current official name",
            "business_summary": "Updated company description from provider",
            "revenue_segments": [],
            "raw_material_inputs": [],
            "geographic_exposure": None,
            "strengths": [],
            "business_exclusions": [],
            "aliases": ["New provider alias"],
            "vendor_id": "UPSTOX",
            "vendor_as_of": datetime.now(UTC).isoformat(),
        }
        await repo.commit_company(
            job["job_id"],
            CompanyBundle(entity=incoming, raw={"profile": "refreshed"}),
            attempt=claim["attempts"],
        )
        refreshed = await repo.get_entity("Stock", "RELIANCE")
        for field in (
            "sector",
            "exposures",
            "revenue_segments",
            "raw_material_inputs",
            "geographic_exposure",
            "strengths",
            "business_exclusions",
        ):
            assert refreshed[field] == curated[field]
        assert refreshed["business_summary"] == incoming["business_summary"]
        assert refreshed["name"] == incoming["name"]
        assert refreshed["vendor_as_of"] == incoming["vendor_as_of"]
        assert set(refreshed["aliases"]) == {*curated["aliases"], "New provider alias"}
        projected = json.loads(
            await conn.fetchval(
                "SELECT event FROM graph_outbox WHERE event->>'job_id'=$1", job["job_id"]
            )
        )
        assert projected["payload"]["entity"] == refreshed

        job2 = await repo.create_job(
            StockRegistration(query="RELIANCE", strengths=["Explicit new strength"])
        )
        claim2 = await repo.claim_job(600, 3)
        await repo.commit_company(
            job2["job_id"],
            CompanyBundle(
                entity={**incoming, "strengths": ["Explicit new strength"]},
                raw={"profile": "second refresh"},
            ),
            attempt=claim2["attempts"],
        )
        revised = await repo.get_entity("Stock", "RELIANCE")
        assert revised["strengths"] == ["Explicit new strength"]
        assert revised["business_exclusions"] == curated["business_exclusions"]
    finally:
        await transaction.rollback()
        await conn.close()
