"""Durable source scheduler. Nothing is scheduled inside an API process."""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.application.ingestion.news_fetch import (
    CommittedNewsFetchService,
    RequestQuotaBudget,
    build_news_adapters,
)
from upstox_service.config.settings import Settings
from upstox_service.domain.resolver import CanonicalEntityResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestOutcome:
    status: str
    details: dict[str, int] | None = None


async def run_locked(name, operation):
    config = Settings()
    repo = DataRepository(config.timescale_dsn)
    redis = Redis.from_url(config.redis_url, decode_responses=True)
    token = str(uuid4())
    key = f"upstox:lock:{name}"
    run_id = None
    acquired = False
    renewer = None

    async def renew():
        try:
            while True:
                await asyncio.sleep(60)
                kept = await redis.eval(
                    "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],900) else return 0 end",
                    1,
                    key,
                    token,
                )
                if not kept:
                    parent.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # No lease means no authority to continue writing, even on a network error.
            parent.cancel()

    parent = asyncio.current_task()
    try:
        acquired = bool(await redis.set(key, token, nx=True, ex=900))
        if not acquired:
            return "SKIPPED_LOCKED"
        run_id = await repo.record_ingest_run(name, "RUNNING")
        renewer = asyncio.create_task(renew())
        outcome = await operation(repo, config)
        if isinstance(outcome, IngestOutcome):
            await repo.update_ingest_run(run_id, outcome.status, details=outcome.details)
            result = outcome.status
        else:
            result = outcome or "SUCCESS"
            await repo.update_ingest_run(run_id, result)
        return result
    except Exception:
        if run_id:
            await repo.update_ingest_run(
                run_id,
                "FAILED",
                error="Source job failed; inspect provider status without credentials",
            )
        logger.error("Source job %s failed", name)
        return "FAILED"
    except asyncio.CancelledError:
        if run_id:
            await repo.update_ingest_run(
                run_id, "FAILED", error="Source job cancelled or lock lease lost"
            )
        raise
    finally:
        if renewer:
            renewer.cancel()
            await asyncio.gather(renewer, return_exceptions=True)
        try:
            if acquired:
                await redis.eval(
                    "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                    1,
                    key,
                    token,
                )
        finally:
            await repo.close()
            await redis.aclose()


async def _news(repo, config):
    # Refresh SQL identities each run: stocks registered via API are immediately queryable.
    resolver = CanonicalEntityResolver.from_catalog(await repo.list_catalog())
    quota_redis = SyncRedis.from_url(config.redis_url, decode_responses=True)
    try:
        service = CommittedNewsFetchService(
            build_news_adapters(resolver=resolver),
            repo,
            RequestQuotaBudget(quota_redis, config.news_daily_request_cap),
        )
        cycle = await service.fetch_cycle()
        return IngestOutcome(
            "SUCCESS" if any(r.status.value == "AVAILABLE" for r in cycle.results) else "DEGRADED",
            details=cycle.eligibility_metrics,
        )
    finally:
        quota_redis.close()


async def hourly_news_job():
    await run_locked("hourly_news", _news)


async def open_checkpoint_job():
    from upstox_service.application.ingestion.checkpoints import collect_checkpoints

    await run_locked("daily_open", lambda repo, config: collect_checkpoints(repo, config, "OPEN"))


async def close_checkpoint_job():
    from upstox_service.application.ingestion.checkpoints import collect_checkpoints

    await run_locked("daily_close", lambda repo, config: collect_checkpoints(repo, config, "CLOSE"))


async def equity_universe_job():
    from upstox_service.adapters.providers.upstox.client import UpstoxClient
    from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider
    from upstox_service.application.stock_data import refresh_equity_universe

    async def refresh(repo, config):
        v2_client = UpstoxClient(
            config.upstox_analytics_token,
            base_url=config.upstox_api_base_url,
            timeout=config.upstox_timeout_seconds,
            max_retries=config.upstox_max_retries,
        )
        v3_client = UpstoxClient(
            config.upstox_analytics_token,
            base_url=config.upstox_api_v3_base_url,
            timeout=config.upstox_timeout_seconds,
            max_retries=config.upstox_max_retries,
        )
        try:
            provider = UpstoxStockDataProvider(v2_client, v3_client)
            await refresh_equity_universe(repo, provider)
            return "SUCCESS"
        finally:
            await v2_client.close()
            await v3_client.close()

    return await run_locked("daily_equity_universe", refresh)


class PersistentSchedule(AsyncIOScheduler):
    """Refresh job definitions without replacing a persisted missed execution."""

    def _real_add_job(self, job, jobstore_alias, replace_existing):
        store = self._lookup_jobstore(jobstore_alias)
        existing = store.lookup_job(job.id)
        if existing is not None:
            job._modify(next_run_time=existing.next_run_time)
        return super()._real_add_job(job, jobstore_alias, replace_existing)


def build_scheduler(config: Settings | None = None) -> AsyncIOScheduler:
    config = config or Settings()
    url = urlsplit(config.redis_url)
    store = RedisJobStore(
        jobs_key="upstox:scheduler:jobs",
        run_times_key="upstox:scheduler:runtimes",
        host=url.hostname or "localhost",
        port=url.port or 6379,
        db=int(url.path.lstrip("/") or 0),
        username=unquote(url.username) if url.username else None,
        password=unquote(url.password) if url.password else None,
        ssl=url.scheme == "rediss",
    )
    scheduler = PersistentSchedule(
        jobstores={"default": store},
        timezone=config.app_timezone,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    scheduler.add_job(hourly_news_job, "cron", minute=0, id="hourly_news", replace_existing=True)
    scheduler.add_job(
        equity_universe_job,
        "cron",
        hour=6,
        minute=0,
        id="daily_equity_universe",
        replace_existing=True,
    )
    scheduler.add_job(
        open_checkpoint_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=30,
        id="daily_open",
        replace_existing=True,
    )
    scheduler.add_job(
        close_checkpoint_job,
        "cron",
        day_of_week="mon-fri",
        hour=19,
        minute=0,
        id="daily_close",
        replace_existing=True,
    )
    return scheduler


async def run():
    from upstox_service.adapters.repositories.timescale.stock_data import init_stock_data_schema

    config = Settings()
    repo = DataRepository(config.timescale_dsn)
    await repo.init_schema()
    await init_stock_data_schema(repo)
    await repo.bootstrap()
    await repo.close()
    scheduler = build_scheduler(config)
    scheduler.start()
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
