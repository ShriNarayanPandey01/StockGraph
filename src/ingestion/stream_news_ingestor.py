"""30-Minute News Stream Ingestor (Rules 5 & 6).

30-minute cron, news-only:
1. Ingests raw news items / Reg-30 filings.
2. Shortlists candidate stocks via CanonicalEntityResolver + StockProfileProvider.
3. Multi-layer deduplication (NewsDeduper):
   - L1 exact seen URL drop (Redis SETNX).
   - L2 normalized headline match (repo.find_text_dup) - no embedding spent.
   - Text chunking (chunk_news <= 512 tokens) and cached embedding.
   - L3 semantic dedup gate (cosine >= 0.92 -> [:DUPLICATE_OF]).
4. If canonical item:
   - Injects StockContextCards into NewsGraphExtractor prompt.
   - Gated LLM routing -> [:DIRECTLY_IMPACTS], [:INDIRECTLY_IMPACTS], [:SHOCKS].
   - L4 cross-news correlation (NewsCorrelator) -> [:CORRELATED_WITH].
5. Distributed single-flight lock (lock:stream_news) and ops logging to ingest_runs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.llm.chunking import chunk_news
from src.processors.entity_resolver import CanonicalEntityResolver
from src.processors.news_correlator import NewsCorrelator
from src.processors.news_dedup import DedupOutcome, NewsDeduper, build_news_props
from src.processors.news_graph_extractor import NewsGraphExtractor
from src.processors.stock_profile_provider import StockProfileProvider

logger = logging.getLogger(__name__)


@dataclass
class StreamIngestStats:
    total_articles: int = 0
    dropped_l1: int = 0
    duplicates_l2: int = 0
    duplicates_l3: int = 0
    canonical_created: int = 0
    impact_edges_created: int = 0
    correlation_edges_created: int = 0
    status: str = "COMPLETED"
    error: str | None = None


class StreamNewsIngestor:
    """30-minute news cron orchestrator with multi-layered dedup, routing & correlation."""

    def __init__(
        self,
        falkor_repo: Any,
        timescale_repo: Any | None = None,
        chat_provider: Any | None = None,
        embedding_provider: Any | None = None,
        resolver: CanonicalEntityResolver | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._falkor = falkor_repo
        self._timescale = timescale_repo
        self._resolver = resolver or CanonicalEntityResolver.from_seed()
        self._profile_provider = StockProfileProvider(repo=falkor_repo)
        self._deduper = NewsDeduper(repo=falkor_repo, redis_client=redis_client)
        self._chat = chat_provider
        self._embedder = embedding_provider
        self._redis = redis_client
        self._extractor = (
            NewsGraphExtractor(chat=chat_provider, resolver=self._resolver)
            if chat_provider is not None
            else None
        )
        self._correlator = (
            NewsCorrelator(chat=chat_provider) if chat_provider is not None else None
        )

    async def ingest_articles(
        self, articles: list[dict[str, Any]], now_ts: int | None = None
    ) -> StreamIngestStats:
        """Run one batch of news articles through the complete stream pipeline."""
        now = now_ts or int(time.time())
        stats = StreamIngestStats(total_articles=len(articles))

        # 1. Acquire Redis single-flight lock
        lock_acquired = self._acquire_lock()
        if not lock_acquired:
            logger.warning("StreamNewsIngestor: lock busy, skipping concurrent run")
            stats.status = "SKIPPED"
            stats.error = "Lock busy"
            return stats

        run_id = None
        if self._timescale is not None:
            try:
                run_id = await self._timescale.record_ingest_run("stream_news_cron", "RUNNING")
            except Exception as exc:
                logger.warning("Could not record ingest run start: %s", exc)

        try:
            for art in articles:
                headline = art.get("headline", "").strip()
                if not headline:
                    continue

                summary = art.get("summary", "")
                source_url = art.get("source_url", "")
                source = art.get("source", "RSS")
                event_date = art.get(
                    "event_date", datetime.now(UTC).strftime("%Y-%m-%d")
                )
                event_ts = art.get("event_ts", now)
                category = art.get("category", "OTHER")
                sentiment = art.get("sentiment")

                # Shortlist candidate stocks via entity resolver
                candidate_tickers = self._shortlist_candidates(headline, summary)
                # Official periodic releases may supply a resolver-validated
                # macro/sector primary entity even when no stock is named.
                primary_entity = str(
                    art.get("primary_entity")
                    or (candidate_tickers[0] if candidate_tickers else "BROAD_MARKET")
                )

                # Assemble deterministic properties
                props = build_news_props(
                    headline=headline,
                    primary_entity=primary_entity,
                    event_date=event_date,
                    event_ts=event_ts,
                    summary=summary,
                    source=source,
                    source_url=source_url,
                    category=category,
                    sentiment=sentiment,
                )

                # Step 1: L1 Check (URL seen)
                if source_url:
                    is_dup, _ = self._deduper.check_l1_seen(source_url)
                    if is_dup:
                        stats.dropped_l1 += 1
                        continue

                # Step 2: L2 Check (normalized headline match, no embedding spent)
                norm_h = props["norm_headline"]
                l2_hit = self._deduper.check_l2_text_dup(norm_h, primary_entity, now)
                if l2_hit is not None and l2_hit.get("canon_id"):
                    self._deduper.link_duplicate(props["id"], str(l2_hit["canon_id"]))
                    stats.duplicates_l2 += 1
                    continue

                # Step 3: Embed text chunk if embedder is available
                embedding = None
                if self._embedder is not None:
                    chunks = chunk_news(props["id"], f"{headline}\n\n{summary}")
                    if chunks:
                        try:
                            embedding = self._embedder.embed_one(chunks[0].text)
                        except Exception as exc:
                            logger.warning("Embedding failed for news %s: %s", props["id"], exc)

                # Step 4: L3 Semantic Dedup Gate
                if embedding is not None:
                    outcome = self._deduper.semantic_link_or_create(props, embedding, now)
                else:
                    if self._falkor is not None:
                        self._falkor.merge_news_event(dict(props))
                    outcome = DedupOutcome(action="created", news_id=props["id"])

                if outcome.action == "duplicate_l3":
                    stats.duplicates_l3 += 1
                    continue

                stats.canonical_created += 1

                # Step 5: Context-Aware LLM Routing (NewsGraphExtractor)
                cards = [
                    self._profile_provider.build_context_card(t)
                    for t in candidate_tickers[:8]
                ]
                if self._extractor is not None and cards:
                    impacts = self._extractor.infer(
                        news_id=props["id"],
                        headline=headline,
                        summary=summary,
                        cards=cards,
                    )
                    if impacts:
                        edges_written = self._extractor.persist(self._falkor, impacts)
                        stats.impact_edges_created += edges_written

                # Step 6: Cross-News Correlation (NewsCorrelator)
                if self._correlator is not None:
                    corrs = self._correlator.correlate(
                        repo=self._falkor,
                        news_id=props["id"],
                        headline=headline,
                        summary=summary,
                        event_ts=event_ts,
                        now_ts=now,
                        embedding=embedding,
                    )
                    stats.correlation_edges_created += len(corrs)

            if run_id is not None and self._timescale is not None:
                await self._timescale.update_ingest_run(run_id, "COMPLETED")

        except Exception as exc:
            logger.error("StreamNewsIngestor failed: %s", exc, exc_info=True)
            stats.status = "FAILED"
            stats.error = str(exc)
            if run_id is not None and self._timescale is not None:
                await self._timescale.update_ingest_run(run_id, "FAILED", error=str(exc))
        finally:
            self._release_lock()

        return stats

    def _shortlist_candidates(self, headline: str, summary: str) -> list[str]:
        """Identify candidate stock tickers mentioned by name, ticker, or alias."""
        text = f"{headline} {summary}"
        found = set()
        for token in text.split():
            clean = token.strip(".,;:()[]'\"").upper()
            resolved = self._resolver.resolve_stock(clean)
            if resolved:
                found.add(resolved)
        # Check alias keys
        for key, ticker in self._resolver.stocks_by_key.items():
            if f" {key} " in f" {text.lower()} ":
                found.add(ticker)
        return sorted(found)

    def _acquire_lock(self) -> bool:
        if self._redis is None:
            return True
        try:
            return bool(self._redis.set("lock:stream_news", "1", nx=True, ex=1800))
        except Exception as exc:
            logger.warning("Redis lock error: %s; failing open", exc)
            return True

    def _release_lock(self) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete("lock:stream_news")
        except Exception:
            pass
