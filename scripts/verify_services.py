"""Read-only local deployment report; never prints credentials or provider data."""

import asyncio
import json

import redis
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.runtime.settings import Settings as GraphSettings
from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.config.settings import Settings as DataSettings


async def main():
    data = DataRepository(DataSettings().timescale_dsn)
    graph_config = GraphSettings()
    graph = GraphRepository()
    broker = redis.Redis.from_url(graph_config.redis_url, decode_responses=True)
    try:
        pool = await data.connect()
        async with pool.acquire() as conn:
            catalog = [
                dict(row)
                for row in await conn.fetch(
                    "SELECT kind,count(*) AS count FROM entity_catalog GROUP BY kind ORDER BY kind"
                )
            ]
            sql = {
                table: await conn.fetchval(f'SELECT count(*) FROM "{table}"')
                for table in (
                    "stock_fundamentals_raw",
                    "daily_stock_metrics",
                    "news_raw",
                    "normalized_news",
                    "graph_outbox",
                    "registration_jobs",
                )
            }
            unpublished = await conn.fetchval(
                "SELECT count(*) FROM graph_outbox WHERE published_at IS NULL"
            )
        report = {
            "sql_catalog": catalog,
            "sql_rows": sql,
            "unpublished_events": unpublished,
            "graph_stocks": graph._run(
                "MATCH (s:Stock) RETURN s.ticker,s.processing_state,s.revision,s.inference_revision ORDER BY s.ticker",
                {},
            ),
            "baseline_macro_pairs": graph._run(
                "MATCH (s:Stock)-[r:SENSITIVE_TO_MACRO {baseline:true}]->(m:MacroFactor) RETURN count(r)",
                {},
            ),
            "llm_relationships": graph._run(
                "MATCH ()-[r]->() WHERE r.inferred_by='LLM' RETURN count(r)", {}
            ),
            "canonical_news": graph._run(
                "MATCH (n:NewsEvent) WHERE NOT (n)-[:DUPLICATE_OF]->() RETURN count(n)", {}
            ),
            "stream_length": broker.xlen(graph_config.event_stream),
        }
        try:
            report["pending_events"] = broker.xpending(
                graph_config.event_stream, graph_config.event_consumer_group
            )["pending"]
        except redis.ResponseError:
            report["pending_events"] = "consumer group not initialized"
        print(json.dumps(report, indent=2))
    finally:
        await data.close()
        broker.close()


if __name__ == "__main__":
    asyncio.run(main())
