"""Separate worker: recoverable SQL-to-Redis relay and monitor scheduling."""

import asyncio
import json
import logging
from importlib.util import find_spec

from redis.asyncio import Redis

from marketgraph_platform.repository import Repository
from marketgraph_platform.settings import Settings

logger = logging.getLogger(__name__)


async def relay_once(repository: Repository, redis, settings: Settings) -> int:
    published = 0
    for row in await repository.claim_outbox():
        try:
            # A crash after XADD and before the SQL acknowledgement can duplicate
            # transport, not application state: consumers key by event/revision.
            await redis.xadd(settings.outbox_stream, {"event": json.dumps(row["event"], default=str)})
            await repository.finish_outbox(row["event_id"], row["lease_id"])
            published += 1
        except Exception:
            # Provider/DSN exception text must not enter persistent errors/logs.
            await repository.retry_outbox(row["event_id"], row["lease_id"], row["attempts"])
            logger.warning("Platform outbox delivery deferred")
    return published


async def run():
    settings = Settings()
    repository = Repository(settings)
    redis = Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True,
                           socket_timeout=10, socket_connect_timeout=5)
    try:
        await repository.connect()
        while True:
            try:
                await relay_once(repository, redis, settings)
                if find_spec("marketgraph_platform.agent_repository"):
                    from marketgraph_platform.agent_repository import schedule_due_monitors
                    await schedule_due_monitors(repository.pool, settings)
                await repository.housekeeping()
            except Exception:
                logger.warning("Platform worker iteration deferred")
            await asyncio.sleep(2)
    finally:
        await redis.aclose()
        await repository.close()


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
