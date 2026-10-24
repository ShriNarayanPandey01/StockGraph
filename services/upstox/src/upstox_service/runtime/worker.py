"""Runs SQL registration jobs and committed outbox publication, separately from API."""

import asyncio
import logging

from redis.asyncio import Redis

from upstox_service.adapters.messaging import RedisPublisher
from upstox_service.adapters.providers.upstox.client import UpstoxClient
from upstox_service.adapters.providers.upstox.company import UpstoxCompanyProvider
from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.adapters.repositories.timescale.documents import DocumentRepository
from upstox_service.application.stock_registration import RegistrationWorker
from upstox_service.config.settings import Settings


async def run():
    config = Settings()
    repository = DataRepository(config.timescale_dsn)
    client = UpstoxClient(
        config.upstox_analytics_token,
        base_url=config.upstox_api_base_url,
        timeout=config.upstox_timeout_seconds,
        max_retries=config.upstox_max_retries,
    )
    redis = Redis.from_url(config.redis_url, decode_responses=True)
    publisher = RedisPublisher(redis, config.event_stream)
    worker = RegistrationWorker(
        repository,
        UpstoxCompanyProvider(client),
        max_attempts=config.job_max_attempts,
        lease_seconds=config.job_lease_seconds,
    )
    await repository.init_schema()
    documents = DocumentRepository(repository)
    await documents.init_schema()
    await repository.bootstrap()
    try:
        while True:
            try:
                await repository.publish_outbox(publisher)
                await documents.publish_outbox(redis)
                worked = await worker.run_once()
                if not worked:
                    await asyncio.sleep(1)
            except Exception:
                logging.error("Source worker stage unavailable; committed jobs and outboxes remain retryable")
                await asyncio.sleep(1)
    finally:
        await client.close()
        await repository.close()
        await redis.aclose()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
