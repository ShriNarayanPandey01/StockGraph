"""Narrow application-facing views of the shared transactional data store."""

from upstox_service.adapters.repositories.timescale.catalog import DataRepository


class RegistrationRepository:
    def __init__(self, repository: DataRepository) -> None:
        self._repository = repository

    async def create_job(self, request):
        return await self._repository.create_job(request)

    async def claim_job(self, lease_seconds, max_attempts):
        return await self._repository.claim_job(lease_seconds, max_attempts)

    async def renew_job(self, job_id, attempt, lease_seconds):
        return await self._repository.renew_job(job_id, attempt, lease_seconds)

    async def commit_company(self, job_id, bundle, *, attempt):
        return await self._repository.commit_company(job_id, bundle, attempt=attempt)

    async def fail_job(self, job_id, error, retry, *, attempt):
        return await self._repository.fail_job(job_id, error, retry, attempt=attempt)


class NewsRepository:
    def __init__(self, repository: DataRepository) -> None:
        self._repository = repository

    async def get_entity(self, kind, entity_id):
        return await self._repository.get_entity(kind, entity_id)

    async def commit_news(self, result):
        return await self._repository.commit_news(result)

    async def get_news_watermark(self, provider_id):
        return await self._repository.get_news_watermark(provider_id)

    async def get_staged_news(self, limit=500):
        return await self._repository.get_staged_news(limit=limit)

    async def stage_news_raw(self, **kwargs):
        return await self._repository.stage_news_raw(**kwargs)

    async def advance_news_watermark(self, provider_id, published_at):
        return await self._repository.advance_news_watermark(provider_id, published_at)

    async def pending_news_reviews(self, limit=100):
        return await self._repository.pending_news_reviews(limit=limit)

    async def defer_news_review(self, provider_id, external_id):
        return await self._repository.defer_news_review(provider_id, external_id)

    async def finish_news_review(self, provider_id, external_id):
        return await self._repository.finish_news_review(provider_id, external_id)


class CheckpointRepository:
    def __init__(self, repository: DataRepository) -> None:
        self._repository = repository

    async def list_catalog(self, kind):
        return await self._repository.list_catalog(kind)

    async def get_watermark(self, vendor_id, ticker, series):
        return await self._repository.get_watermark(vendor_id, ticker, series)

    async def missing_checkpoint_dates(self, ticker, session, start, end):
        return await self._repository.missing_checkpoint_dates(ticker, session, start, end)

    async def stage_vendor_quote(self, vendor_id, ticker, trade_date, series, payload, fetched_at):
        return await self._repository.stage_vendor_quote(
            vendor_id, ticker, trade_date, series, payload, fetched_at
        )

    async def upsert_daily_metrics(self, rows):
        return await self._repository.upsert_daily_metrics(rows)

    async def advance_watermark(self, vendor_id, ticker, series, trade_date):
        return await self._repository.advance_watermark(vendor_id, ticker, series, trade_date)
