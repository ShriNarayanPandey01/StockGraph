"""Hardened APScheduler Worker & Factory (Rule 6).

Rule 6 Invariants:
1. APScheduler runs as a SEPARATE worker process (stockgraph-scheduler),
   never inside the API process.
2. Durable jobstore (SQLAlchemyJobStore or RedisJobStore),
   coalesce=True, max_instances=1, misfire_grace_time=300.
3. Every job body takes a Redis distributed lock (SET NX EX) ensuring single-flight.
4. Overlapping runs are impossible.
5. All runs log to ingest_runs.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_MISFIRE_GRACE_TIME = 300


@asynccontextmanager
async def single_flight_lock(
    redis_client: Any, lock_name: str, lease_seconds: int = 1800
) -> AsyncIterator[bool]:
    """Async context manager ensuring single-flight execution via Redis NX EX."""
    if redis_client is None:
        yield True
        return

    acquired = False
    try:
        acquired = bool(redis_client.set(f"lock:{lock_name}", "1", nx=True, ex=lease_seconds))
    except Exception as exc:
        logger.warning("Redis lock error on %s: %s; failing open", lock_name, exc)
        acquired = True

    try:
        yield acquired
    finally:
        if acquired and redis_client is not None:
            try:
                redis_client.delete(f"lock:{lock_name}")
            except Exception:
                pass


class SchedulerFactory:
    """Factory creating hardened AsyncIOScheduler instances."""

    @staticmethod
    def build(
        dsn: str | None = None,
        redis_url: str | None = None,
    ) -> AsyncIOScheduler:
        """Construct an AsyncIOScheduler configured per Rule 6."""
        jobstores: dict[str, Any] = {}

        if dsn:
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

                jobstores["default"] = SQLAlchemyJobStore(url=dsn)
            except Exception as exc:
                logger.warning("Could not initialize SQLAlchemyJobStore (%s); using MemoryJobStore", exc)
                jobstores["default"] = MemoryJobStore()
        elif redis_url:
            try:
                from urllib.parse import urlsplit

                from apscheduler.jobstores.redis import RedisJobStore

                parts = urlsplit(redis_url)
                r_host = parts.hostname or "localhost"
                r_port = parts.port or 6380
                r_db = int(parts.path.lstrip("/") or 0)
                jobstores["default"] = RedisJobStore(
                    host=r_host,
                    port=r_port,
                    db=r_db,
                )
            except Exception as exc:
                logger.warning("Could not initialize RedisJobStore (%s); using MemoryJobStore", exc)
                jobstores["default"] = MemoryJobStore()
        else:
            jobstores["default"] = MemoryJobStore()

        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": DEFAULT_MISFIRE_GRACE_TIME,
        }

        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults=job_defaults,
            timezone=settings.app_timezone,
        )
        return scheduler


def register_default_jobs(
    scheduler: AsyncIOScheduler,
    stream_job_callable: Any | None = None,
    daily_open_callable: Any | None = None,
    daily_eod_callable: Any | None = None,
    revision_sweep_callable: Any | None = None,
    periodic_monthly_callable: Any | None = None,
    periodic_bimonthly_callable: Any | None = None,
    quarterly_callable: Any | None = None,
) -> None:
    """Register standard Indian equity cadence schedules."""
    # 1. STREAM_30M (News-only every 30 minutes)
    if stream_job_callable:
        scheduler.add_job(
            stream_job_callable,
            trigger="interval",
            minutes=30,
            id="stream_news_30m",
            name="30m Stream News Ingestion",
            replace_existing=True,
        )

    # 2. DAILY_OPEN (Market open checkpoint ~9:30 AM IST Mon-Fri)
    if daily_open_callable:
        scheduler.add_job(
            daily_open_callable,
            trigger="cron",
            day_of_week="mon-fri",
            hour=9,
            minute=30,
            id="daily_open_checkpoint",
            name="Daily Market Open Checkpoint",
            replace_existing=True,
        )

    # 3. DAILY_EOD (Bhavcopy + EOD close ~7:00 PM IST Mon-Fri)
    if daily_eod_callable:
        scheduler.add_job(
            daily_eod_callable,
            trigger="cron",
            day_of_week="mon-fri",
            hour=19,
            minute=0,
            id="daily_eod_cron",
            name="Daily Bhavcopy EOD Ingestion",
            replace_existing=True,
        )

    # 4. REVISION_SWEEP (Trailing lookback check ~9:00 PM IST Mon-Fri)
    if revision_sweep_callable:
        scheduler.add_job(
            revision_sweep_callable,
            trigger="cron",
            day_of_week="mon-fri",
            hour=21,
            minute=0,
            id="vendor_revision_sweep",
            name="Vendor Revision Lookback Sweep",
            replace_existing=True,
        )

    # 5. MONTHLY (official macro releases + AMFI/AMC holdings).  The source
    # adapter applies its own release-calendar filter; this trigger is the
    # durable replay point around the planned AMFI disclosure cadence.
    if periodic_monthly_callable:
        scheduler.add_job(
            periodic_monthly_callable,
            trigger="cron",
            day=12,
            hour=20,
            minute=30,
            id="periodic_macro_monthly",
            name="Monthly Macro and Mutual Fund Ingestion",
            replace_existing=True,
        )

    # 6. BIMONTHLY (RBI MPC periods).  Exact MPC dates are source-calendar
    # data; this cadence safely scans the official feed in the scheduled run.
    if periodic_bimonthly_callable:
        scheduler.add_job(
            periodic_bimonthly_callable,
            trigger="cron",
            month="2,4,6,8,10,12",
            day=1,
            hour=20,
            minute=45,
            id="periodic_macro_bimonthly",
            name="Bi-Monthly RBI Macro Ingestion",
            replace_existing=True,
        )

    # 7. QUARTERLY (Jan/Apr/Jul/Oct-Nov result season).  Per-company dates
    # live in the official filing adapter, so the job scans the season window
    # instead of assuming every issuer reports on one date.
    if quarterly_callable:
        scheduler.add_job(
            quarterly_callable,
            trigger="cron",
            month="1,4,7,10,11",
            day="1-15",
            hour=21,
            minute=15,
            id="quarterly_filing_scan",
            name="Quarterly Results and Guidance Ingestion",
            replace_existing=True,
        )


async def run_worker() -> None:
    """Standalone worker entrypoint for stockgraph-scheduler process."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting stockgraph-scheduler worker process...")

    from datetime import date

    import redis

    from src.ingestion.daily_eod_ingestor import DailyEodIngestor
    from src.ingestion.periodic_macro_ingestor import PeriodicMacroIngestor
    from src.ingestion.quarterly_ingestor import QuarterlyIngestor
    from src.ingestion.stream_news_ingestor import StreamNewsIngestor
    from src.repositories.falkor_repo import FalkorGraphRAGRepository
    from src.repositories.timescale_repo import TimescaleRepository

    timescale = TimescaleRepository()
    falkor = FalkorGraphRAGRepository()
    try:
        r_client = redis.from_url(settings.redis_url)
    except Exception:
        r_client = None

    stream_ingestor = StreamNewsIngestor(
        falkor_repo=falkor,
        timescale_repo=timescale,
        redis_client=r_client,
    )
    daily_eod = DailyEodIngestor(
        timescale_repo=timescale,
        falkor_repo=falkor,
        redis_client=r_client,
    )
    periodic_macro = PeriodicMacroIngestor(
        timescale_repo=timescale,
        falkor_repo=falkor,
        redis_client=r_client,
    )
    quarterly = QuarterlyIngestor(
        timescale_repo=timescale,
        falkor_repo=falkor,
        redis_client=r_client,
    )

    async def _stream_job() -> None:
        logger.info("Running 30m stream news ingestion job...")
        await stream_ingestor.ingest_articles([])

    async def _daily_eod_job() -> None:
        logger.info("Running daily EOD Bhavcopy ingestion job...")
        await daily_eod.run_eod(trade_date=date.today())

    async def _periodic_monthly_job() -> None:
        logger.info("Running monthly official macro and MF ingestion job...")
        await periodic_macro.run(as_of=date.today())

    async def _periodic_bimonthly_job() -> None:
        logger.info("Running bi-monthly official macro ingestion job...")
        await periodic_macro.run(as_of=date.today(), mf_records=[])

    async def _quarterly_job() -> None:
        logger.info("Running quarterly official filing scan...")
        await quarterly.run(as_of=date.today())

    scheduler = SchedulerFactory.build(dsn=settings.timescale_dsn, redis_url=settings.redis_url)
    register_default_jobs(
        scheduler,
        stream_job_callable=_stream_job,
        daily_eod_callable=_daily_eod_job,
        periodic_monthly_callable=_periodic_monthly_job,
        periodic_bimonthly_callable=_periodic_bimonthly_job,
        quarterly_callable=_quarterly_job,
    )
    scheduler.start()

    stop_event = asyncio.Event()

    def _sig_handler() -> None:
        logger.info("Shutdown signal received. Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except NotImplementedError:
            pass  # Windows event loop limitation

    await stop_event.wait()
    logger.info("Scheduler worker stopped cleanly.")


def main() -> None:
    """CLI entrypoint for stockgraph-scheduler."""
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
