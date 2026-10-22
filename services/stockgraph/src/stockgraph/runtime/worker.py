"""Run independently of the API: python -m stockgraph.runtime.worker."""

import logging
import time

import redis

from stockgraph.adapters.llm.providers import LiteLLMChatProvider, LiteLLMEmbeddingProvider
from stockgraph.adapters.messaging.consumer import EventConsumer, renewable_lock
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.ingestion.pipeline import GraphPipeline
from stockgraph.runtime.settings import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    broker = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    repo = GraphRepository()
    repo.ensure_indexes_and_constraints()
    with renewable_lock(broker) as guard:
        if guard:
            repo.set_write_guard(guard)
            try:
                repo.reconcile_curated_links()
            finally:
                repo.set_write_guard(None)
    pipeline = GraphPipeline(
        repo, broker, LiteLLMChatProvider(broker), LiteLLMEmbeddingProvider(broker)
    )
    consumer = EventConsumer(broker, pipeline)
    consumer.ensure_group()
    try:
        while True:
            try:
                consumer.run_once()
            except Exception:
                logging.exception("Event transport unavailable; pending work is retained")
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        broker.close()


if __name__ == "__main__":
    main()
