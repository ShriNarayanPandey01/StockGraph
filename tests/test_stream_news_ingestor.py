"""Test 30-minute news stream ingestor pipeline (Rules 5 & 6)."""

import pytest
from src.domain.enums import CorrelationType
from src.domain.schemas import InferredNewsCorrelation, InferredNewsStockImpact
from src.ingestion.stream_news_ingestor import StreamNewsIngestor
from src.processors.entity_resolver import CanonicalEntityResolver
from src.processors.news_correlator import NewsCorrelationBatch
from src.processors.news_graph_extractor import NewsImpactBatch


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = val
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class _FakeFalkor:
    def __init__(self):
        self.news = {}
        self.duplicates = []
        self.impacts = []
        self.shocks = []
        self.correlations = []

    def find_text_dup(self, norm_headline, ticker, window_secs):
        for nid, props in self.news.items():
            if props.get("norm_headline") == norm_headline and props.get("ticker") == ticker:
                return [{"id": nid}]
        return None

    def find_near_dup(self, embedding, ticker, now_ts):
        return None

    def merge_news_event(self, props, embedding=None):
        nid = props["id"]
        self.news[nid] = dict(props)
        if embedding:
            self.news[nid]["embedding"] = embedding
        return {"id": nid}

    def link_duplicate(self, dup_id, canon_id):
        self.duplicates.append((dup_id, canon_id))

    def merge_stock_impact(self, news_id, ticker, impact_type, confidence, rationale):
        self.impacts.append((news_id, ticker, impact_type, confidence, rationale))

    def merge_news_shock(self, news_id, kind, target_id, confidence, rationale):
        self.shocks.append((news_id, kind, target_id, confidence, rationale))

    def find_correlation_candidates(self, news_id, now_ts):
        return []

    def merge_news_correlation(self, new_id, prior_id, ctype, confidence, rationale, ts):
        self.correlations.append((new_id, prior_id, ctype, confidence, rationale, ts))

    def get_active_exposures(self, ticker):
        return ["COKING_COAL"]


class _FakeTimescale:
    def __init__(self):
        self.runs = []

    async def record_ingest_run(self, job_name, status, started_at=None, finished_at=None, error=None):
        run_id = len(self.runs) + 1
        self.runs.append({"id": run_id, "name": job_name, "status": status})
        return run_id

    async def update_ingest_run(self, run_id, status, finished_at=None, error=None):
        for r in self.runs:
            if r["id"] == run_id:
                r["status"] = status
                r["error"] = error


class _FakeChat:
    def __init__(self):
        self.prompts = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        if schema is NewsImpactBatch:
            return NewsImpactBatch(
                impacts=[
                    InferredNewsStockImpact(
                        news_id="n1",
                        ticker="TATASTEEL",
                        impact_type="DIRECTLY_IMPACTS",
                        confidence=0.88,
                        rationale="Company reported record production",
                    )
                ]
            )
        if schema is NewsCorrelationBatch:
            return NewsCorrelationBatch(correlations=[])
        return {}


class _FakeEmbedder:
    def embed_one(self, text):
        return [0.1] * 1536


@pytest.mark.asyncio
async def test_stream_pipeline_canonical_creation_and_routing():
    falkor = _FakeFalkor()
    timescale = _FakeTimescale()
    redis = _FakeRedis()
    chat = _FakeChat()
    embedder = _FakeEmbedder()

    ingestor = StreamNewsIngestor(
        falkor_repo=falkor,
        timescale_repo=timescale,
        chat_provider=chat,
        embedding_provider=embedder,
        redis_client=redis,
    )

    articles = [
        {
            "headline": "Tata Steel posts strong Q2 performance",
            "summary": "Tata Steel reported high delivery volumes in India.",
            "source_url": "https://example.com/news/1?utm_source=twitter",
            "source": "RSS",
            "event_date": "2026-10-18",
            "event_ts": 1780000000,
        }
    ]

    stats = await ingestor.ingest_articles(articles, now_ts=1780000000)

    assert stats.total_articles == 1
    assert stats.canonical_created == 1
    assert stats.impact_edges_created >= 1
    assert len(falkor.news) == 1
    assert len(falkor.impacts) == 1
    assert falkor.impacts[0][1] == "TATASTEEL"
    assert timescale.runs[0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_stream_pipeline_l1_and_l2_dedup():
    falkor = _FakeFalkor()
    timescale = _FakeTimescale()
    redis = _FakeRedis()
    embedder = _FakeEmbedder()

    ingestor = StreamNewsIngestor(
        falkor_repo=falkor,
        timescale_repo=timescale,
        chat_provider=_FakeChat(),
        embedding_provider=embedder,
        redis_client=redis,
    )

    # Ingest initial article
    art1 = {
        "headline": "Tata Steel expands plant",
        "summary": "New blast furnace added.",
        "source_url": "https://example.com/plant-news",
        "source": "RSS",
        "event_date": "2026-10-18",
        "event_ts": 1780000000,
    }
    stats1 = await ingestor.ingest_articles([art1], now_ts=1780000000)
    assert stats1.canonical_created == 1

    # Exact URL again -> L1 drop
    art_l1 = dict(art1)
    stats2 = await ingestor.ingest_articles([art_l1], now_ts=1780000000)
    assert stats2.dropped_l1 == 1

    # Different URL, same headline -> L2 near-dup
    art_l2 = dict(art1)
    art_l2["source_url"] = "https://different.com/same-headline"
    stats3 = await ingestor.ingest_articles([art_l2], now_ts=1780000000)
    assert stats3.duplicates_l2 == 1
    assert len(falkor.duplicates) == 1
