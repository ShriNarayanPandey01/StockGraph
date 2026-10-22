"""Back up then remove stored news that fails the financial-news eligibility policy.

The script only operates on this project's local SQL database, Falkor graph,
and Redis stream.  Writers must be stopped first.  It never stores a rejected
headline or payload; the JSON result contains aggregate counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import redis
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from upstox_service.application.ingestion.news_eligibility import NewsEligibilityGate
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory

from scripts.project_data import CONFIRMATION, backup, validate_targets
from scripts.project_settings import ProjectDataSettings


def article_from_row(row: Any) -> NewsArticle | None:
    payload = row["article"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    try:
        category = NewsCategory(str(payload.get("category") or "OTHER"))
    except ValueError:
        category = NewsCategory.OTHER
    try:
        published = datetime.fromisoformat(str(payload["published_at"]).replace("Z", "+00:00"))
        return NewsArticle(
            external_id=str(row["external_id"]),
            headline=str(payload["headline"]),
            summary=str(payload.get("summary") or ""),
            source_url=str(payload.get("source_url") or ""),
            source=str(payload.get("source") or row["provider_id"]),
            published_at=published,
            category=category,
            sentiment=payload.get("sentiment"),
            tickers=tuple(payload.get("tickers") or ()),
            ticker_sentiment=payload.get("ticker_sentiment") or {},
        )
    except (KeyError, TypeError, ValueError):
        return None


async def purge(settings: ProjectDataSettings, apply: bool) -> dict[str, int]:
    sql = await asyncpg.connect(settings.timescale_dsn)
    graph = GraphRepository()
    stream = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    gate = NewsEligibilityGate()
    metrics: Counter[str] = Counter()
    candidates: list[tuple[str, str, NewsArticle]] = []
    try:
        rows = await sql.fetch(
            "SELECT provider_id,external_id,article FROM normalized_news ORDER BY committed_at"
        )
        metrics["examined"] = len(rows)
        review_candidates: list[tuple[str, str, NewsArticle]] = []
        for row in rows:
            article = article_from_row(row)
            if article is None:
                metrics["retained:MALFORMED_LEGACY"] += 1
                continue
            review_candidates.append((str(row["provider_id"]), str(row["external_id"]), article))

        # The historical reconciliation performs no writes during review.  Bounded
        # parallelism keeps an LLM-backed audit inside a maintenance window without
        # overwhelming the internal reviewer or bypassing its budget controls.
        limiter = asyncio.Semaphore(4)

        async def decide(article: NewsArticle):
            async with limiter:
                verdict = await gate.decide(article)
                # This is an offline maintenance pass, so one bounded retry is
                # safe. New ingestion still rejects a timed-out review on its
                # first attempt and writes nothing.
                if verdict.reason == "REVIEW_UNAVAILABLE":
                    return await gate.decide(article)
                return verdict

        verdicts = await asyncio.gather(
            *(decide(article) for _provider_id, _external_id, article in review_candidates)
        )
        for (provider_id, external_id, article), verdict in zip(
            review_candidates, verdicts, strict=True
        ):
            # An unavailable reviewer rejects new ingestion, but must never cause
            # destructive historical loss. It remains visible for a later replay.
            if verdict.reason == "REVIEW_UNAVAILABLE":
                metrics["retained:REVIEW_UNAVAILABLE"] += 1
                continue
            if verdict.approved:
                metrics["retained:APPROVED"] += 1
                continue
            metrics[f"purge:{verdict.reason}"] += 1
            candidates.append((provider_id, external_id, article))

        if not apply:
            return dict(metrics)

        # Delete graph nodes first. SQL remains intact if a graph failure stops
        # the run, and the backup made by main() can restore all stores.
        for _provider_id, _external_id, article in candidates:
            await asyncio.to_thread(
                graph._run,
                "MATCH (n:NewsEvent) WHERE n.source=$source AND n.headline=$headline "
                "AND n.event_ts=$event_ts DETACH DELETE n",
                {
                    "source": article.source.upper(),
                    "headline": article.headline,
                    "event_ts": article.event_ts,
                },
            )

        async with sql.transaction():
            for provider_id, external_id, _article in candidates:
                entity_id = f"{provider_id}:{external_id}"
                await sql.execute(
                    "DELETE FROM graph_outbox WHERE event->>'kind'='news.received' "
                    "AND event->>'entity_id'=$1",
                    entity_id,
                )
                await sql.execute(
                    "DELETE FROM news_raw WHERE provider_id=$1 AND external_id=$2",
                    provider_id,
                    external_id,
                )
                await sql.execute(
                    "DELETE FROM normalized_news WHERE provider_id=$1 AND external_id=$2",
                    provider_id,
                    external_id,
                )

        candidate_entities = {f"{provider}:{external}" for provider, external, _ in candidates}
        if candidate_entities:
            for message_id, fields in stream.xrange("stockgraph:events:v1"):
                raw_event = fields.get(b"event") or fields.get("event")
                try:
                    event = json.loads(raw_event)
                except (TypeError, ValueError):
                    continue
                if event.get("kind") == "news.received" and event.get("entity_id") in candidate_entities:
                    stream.xdel("stockgraph:events:v1", message_id)
                    metrics["stream_entries_deleted"] += 1
            state_keys = [f"stockgraph:news-source:{entity}" for entity in candidate_entities]
            if state_keys:
                metrics["news_state_keys_deleted"] = int(stream.delete(*state_keys))
        metrics["purged"] = len(candidates)
        return dict(metrics)
    finally:
        await sql.close()
        stream.close()


async def run(args: argparse.Namespace) -> None:
    settings = ProjectDataSettings()
    validate_targets(settings)
    if args.apply and (not args.writers_stopped or args.confirm != CONFIRMATION):
        raise ValueError(
            "Refusing destructive cleanup: stop writers and pass "
            "--writers-stopped --confirm stockgraph/stock_graph"
        )
    if args.apply:
        archive = await backup(settings, Path(args.backup_dir))
        result = await purge(settings, apply=True)
        print(json.dumps({"backup": str(archive), **result}, sort_keys=True))
    else:
        print(json.dumps(await purge(settings, apply=False), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform cleanup after creating a backup")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--backup-dir", default="backups")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
