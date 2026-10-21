"""Test scheduler hardening, single-flight locks & job defaults (Rule 6)."""

import pytest

from src.ingestion.scheduler import (
    DEFAULT_MISFIRE_GRACE_TIME,
    SchedulerFactory,
    register_default_jobs,
    single_flight_lock,
)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = val
        return True

    def delete(self, key):
        self.store.pop(key, None)


def test_scheduler_factory_defaults():
    sched = SchedulerFactory.build()
    defaults = sched._job_defaults
    assert defaults["coalesce"] is True
    assert defaults["max_instances"] == 1
    assert defaults["misfire_grace_time"] == DEFAULT_MISFIRE_GRACE_TIME


def test_register_default_jobs():
    sched = SchedulerFactory.build()

    def dummy():
        pass

    register_default_jobs(
        scheduler=sched,
        stream_job_callable=dummy,
        daily_open_callable=dummy,
        daily_eod_callable=dummy,
        revision_sweep_callable=dummy,
        periodic_monthly_callable=dummy,
        periodic_bimonthly_callable=dummy,
        quarterly_callable=dummy,
    )

    job_ids = {j.id for j in sched.get_jobs()}
    assert "stream_news_30m" in job_ids
    assert "daily_open_checkpoint" in job_ids
    assert "daily_eod_cron" in job_ids
    assert "vendor_revision_sweep" in job_ids
    assert "periodic_macro_monthly" in job_ids
    assert "periodic_macro_bimonthly" in job_ids
    assert "quarterly_filing_scan" in job_ids


@pytest.mark.asyncio
async def test_single_flight_lock_guards_concurrency():
    redis = _FakeRedis()

    async with single_flight_lock(redis, "test_job") as acquired_first:
        assert acquired_first is True

        # Second concurrent attempt must fail to acquire lock
        async with single_flight_lock(redis, "test_job") as acquired_second:
            assert acquired_second is False

    # Once released, can acquire again
    async with single_flight_lock(redis, "test_job") as acquired_third:
        assert acquired_third is True
