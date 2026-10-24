"""Opt-in parser/projection checks against a disposable local Falkor graph.

RUN_GRAPH_LIVE_TESTS=1 enables these tests. No production graph is read/written.
"""

import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.domain.enums import Window
from stockgraph.runtime.settings import settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_GRAPH_LIVE_TESTS") != "1", reason="opt-in local Falkor integration"
)


@pytest.fixture
def graph():
    name = "stockgraph_test_" + uuid4().hex
    repository = GraphRepository(
        host=settings.falkor_host, port=settings.falkor_port, graph_name=name
    )
    repository.ensure_indexes_and_constraints()
    try:
        yield repository
    finally:
        # Exact generated test graph only: never delete a server/database/volume.
        assert name.startswith("stockgraph_test_") and len(name) == len("stockgraph_test_") + 32
        client = redis.Redis(host=settings.falkor_host, port=settings.falkor_port)
        if client.exists(name):
            client.execute_command("GRAPH.DELETE", name)
        client.close()


def seed_graph(graph):
    now = int(time.time()) - 60
    graph.project_entity("Commodity", "BRENT_CRUDE", {"id": "BRENT_CRUDE", "name": "Crude"}, 1, now)
    graph.project_entity(
        "MacroFactor",
        "RBI_REPO_RATE",
        {"id": "RBI_REPO_RATE", "description": "Policy rate"},
        1,
        now,
    )
    graph.project_entity(
        "MacroFactor", "USD_INR_FX", {"id": "USD_INR_FX", "description": "Currency rate"}, 1, now
    )
    graph.project_entity(
        "Stock",
        "TESTPAINT",
        {
            "ticker": "TESTPAINT",
            "name": "Test Paint",
            "business_summary": "A test manufacturer exposed to crude",
        },
        1,
        now,
    )
    graph.merge_ontology_edge(
        "TESTPAINT",
        "EXPOSED_TO",
        "BRENT_CRUDE",
        0.9,
        "Crude derivatives are production inputs",
        valid_from_ts=now,
    )
    graph.mark_entity_processed("Stock", "TESTPAINT", 1)
    return now


def news(graph, identity, headline, now, coordinate):
    embedding = [0.0] * settings.embedding_dimension
    embedding[coordinate] = 1.0
    return graph.merge_news_event(
        {
            "id": identity,
            "headline": headline,
            "summary": headline,
            "event_ts": now,
            "event_date": datetime.fromtimestamp(now, UTC).date().isoformat(),
            "ticker": "BROAD_MARKET",
            "source": "TEST",
            "source_url": f"https://example.com/{identity}",
            "norm_headline": headline.lower(),
        },
        embedding,
    )


def test_live_graph_macro_baseline_versions_and_indirect_paths(graph):
    now = seed_graph(graph)
    macros = graph._run(
        "MATCH (:Stock {ticker:'TESTPAINT'})-[r:SENSITIVE_TO_MACRO {baseline:true}]->(m) RETURN m.id",
        {},
    )
    assert len(macros) == 2
    graph.project_entity(
        "MacroFactor",
        "RBI_REPO_RATE",
        {"id": "RBI_REPO_RATE", "description": "Policy tightened"},
        2,
        now + 10,
    )
    graph.project_entity(
        "MacroFactor",
        "RBI_REPO_RATE",
        {"id": "RBI_REPO_RATE", "description": "Policy tightened"},
        3,
        now + 20,
    )
    versions = graph._run(
        "MATCH (m:MacroFactor {id:'RBI_REPO_RATE'})-[:HAS_VERSION]->(v) RETURN v.id,v.is_latest,v.valid_from_ts,v.valid_to_ts ORDER BY v.valid_from_ts",
        {},
    )
    assert len(versions) == 2
    assert versions[0][1] is False and versions[1][1] is True
    assert versions[0][3] == now + 9
    news(graph, "oil-shock", "Oil prices surge after supply disruption", now + 30, 0)
    graph.merge_news_shock("oil-shock", "commodity", "BRENT_CRUDE", 0.95, "Higher input costs")
    context = GraphContextService(graph).get_context("TESTPAINT", Window.LAST_1Y)
    assert any(n.id == "Commodity:BRENT_CRUDE" for n in context.nodes)
    assert any(n.id == "MacroFactor:USD_INR_FX" for n in context.nodes)
    assert any(n.id == "NewsEvent:oil-shock" for n in context.nodes)
    assert context.indirect_news[0].model_dump()["id"] == "oil-shock"
    assert {e.relation for e in context.edges} >= {"EXPOSED_TO", "SENSITIVE_TO_MACRO", "SHOCKS"}


def test_live_graph_news_pagination_and_confidence(graph):
    now = seed_graph(graph)
    for index in range(3):
        identity = f"direct-{index}"
        news(graph, identity, f"Test company earnings report {index}", now + index, index)
        graph.merge_stock_impact(
            identity, "TESTPAINT", "DIRECTLY_IMPACTS", 0.9, "Earnings affect the company"
        )
    news(graph, "weak", "Speculative test story", now, 4)
    graph.merge_stock_impact("weak", "TESTPAINT", "DIRECTLY_IMPACTS", 0.1, "Low confidence")
    service = GraphContextService(graph)
    first = service.get_context("TESTPAINT", Window.LAST_1Y, limit=1)
    second = service.get_context(
        "TESTPAINT", Window.LAST_1Y, offset=1, limit=1, as_of_ts=first.end_ts
    )
    final = service.get_context(
        "TESTPAINT", Window.LAST_1Y, offset=2, limit=1, as_of_ts=first.end_ts
    )
    assert first.pagination["has_more"]["direct"]
    assert not final.pagination["has_more"]["direct"]
    assert len({p.direct_news[0].model_dump()["id"] for p in (first, second, final)}) == 3
    assert all(p.direct_news[0].model_dump()["id"] != "weak" for p in (first, second, final))
    assert len(graph.historical_news(now - 10)) == 4


def test_live_graph_curated_links_survive_event_order_and_replay(graph):
    now = int(time.time())
    source = {"id": "INPUT", "name": "Input commodity", "related_ids": ["OUTPUT"]}
    graph.project_entity("Commodity", "INPUT", source, 1, now)
    graph.project_entity(
        "Commodity", "OUTPUT", {"id": "OUTPUT", "name": "Output commodity"}, 1, now
    )
    graph.project_entity("Commodity", "INPUT", source, 1, now + 5)
    rows = graph._run(
        "MATCH (:Commodity {id:'INPUT'})-[r:RELATED_TO]->(:Commodity {id:'OUTPUT'}) RETURN r.edge_id,r.valid_from_ts",
        {},
    )
    assert len(rows) == 1
    assert rows[0][1] == 0
    graph.reconcile_curated_links()
    assert len(graph._run(
        "MATCH (:Commodity {id:'INPUT'})-[r:RELATED_TO]->(:Commodity {id:'OUTPUT'}) RETURN r.edge_id", {}
    )) == 1


def test_live_reconcile_accepts_empty_old_relationships_and_replaces_direct_with_indirect(graph):
    now = seed_graph(graph)
    news(graph, "reconcile-test", "Test Paint changes guidance", now, 0)
    graph.reconcile_news_impacts("reconcile-test", ["TESTPAINT"], [{
        "ticker": "TESTPAINT", "impact_type": "DIRECTLY_IMPACTS", "confidence": 0.9,
        "rationale": "Direct announcement", "sentiment": -0.4}], [])
    assert graph._run("MATCH (:NewsEvent {id:'reconcile-test'})-[r:DIRECTLY_IMPACTS]->"
                      "(:Stock {ticker:'TESTPAINT'}) RETURN r.confidence", {}) == [[0.9]]
    graph.reconcile_news_impacts("reconcile-test", ["TESTPAINT"], [{
        "ticker": "TESTPAINT", "impact_type": "INDIRECTLY_IMPACTS", "confidence": 0.85,
        "rationale": "Corrected: sector exposure"}], [{"kind": "commodity", "entity_id": "BRENT_CRUDE",
        "confidence": 0.8, "rationale": "Crude shock"}])
    rows = graph._run("MATCH (:NewsEvent {id:'reconcile-test'})-[r]->(t) "
                      "RETURN type(r),coalesce(t.ticker,t.id),r.sentiment", {})
    assert not any(row[0] == "DIRECTLY_IMPACTS" for row in rows)
    indirect = next(row for row in rows if row[0] == "INDIRECTLY_IMPACTS")
    assert indirect[1:] == ["TESTPAINT", -0.4]
    assert any(row[0] == "SHOCKS" for row in rows)
    graph.reconcile_news_impacts("reconcile-test", ["TESTPAINT"], [], [])
    assert graph._run("MATCH (:NewsEvent {id:'reconcile-test'})-[r]->() RETURN type(r)", {}) == []


def test_live_failed_inference_keeps_previously_accepted_relationships(graph):
    from stockgraph.application.ingestion.pipeline import CheckedChat, GraphPipeline
    from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver
    now = seed_graph(graph)
    news(graph, "failed-inference-test", "Test Paint changes guidance", now, 0)
    graph.merge_stock_impact("failed-inference-test", "TESTPAINT", "DIRECTLY_IMPACTS", 0.9,
                             "Previously accepted inference")
    class BrokenChat:
        def complete_json(self, *args, **kwargs):
            raise RuntimeError("Inference provider unavailable")
    pipeline = GraphPipeline(graph, None, BrokenChat(), None)
    with pytest.raises(RuntimeError, match="inference failed"):
        pipeline._route({"id": "failed-inference-test", "headline": "Corrected headline", "summary": "Changed"},
                        CanonicalEntityResolver.from_catalog(graph.catalog()), CheckedChat(BrokenChat()))
    rows = graph._run("MATCH (:NewsEvent {id:'failed-inference-test'})-[r:DIRECTLY_IMPACTS]->"
                      "(:Stock {ticker:'TESTPAINT'}) RETURN r.causal_rationale", {})
    assert rows == [["Previously accepted inference"]]


def test_live_professional_publication_correction_revocation_and_out_of_order_retraction(graph):
    from datetime import timedelta

    from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
    from stockgraph.application.professional import EvidencePipeline, professional_context
    from stockgraph.domain.platform_events import PlatformEvent
    seed_graph(graph)
    EvidenceRepository(graph).ensure_indexes()
    contribution, author = str(uuid4()), str(uuid4())
    now = datetime.now(UTC) - timedelta(seconds=10)
    version1, version2 = str(uuid4()), str(uuid4())
    def publication(revision, version, title):
        return PlatformEvent(event_id=uuid4(), kind="professional.published", entity_id=contribution,
            revision=revision, occurred_at=now + timedelta(seconds=revision), payload={
            "contribution_id": contribution, "version_id": version, "author_id": author,
            "author_name": "Verified analyst", "ticker": "TESTPAINT", "title": title,
            "body": "Demand improves despite opposing crude evidence", "direction": "BULLISH",
            "horizon": "next quarter", "event_at": now.isoformat(), "known_at": now.isoformat(),
            "published_at": (now + timedelta(seconds=revision)).isoformat(),
            "expires_at": (now + timedelta(days=90)).isoformat(),
            "evidence": [{"url": "https://example.org/filing", "title": "Source", "locator": "page 1"}],
            "future_access": "PRO"})
    pipeline = EvidencePipeline(graph)
    first = publication(1, version1, "Initial view")
    second = publication(2, version2, "Corrected view")
    pipeline.process(first)
    pipeline.process(second)
    pipeline.process(first)  # Older delivery must not revive the superseded version.
    end = int(time.time())
    context = professional_context(graph, "TESTPAINT", end-180*86400, end)
    assert [v["id"] for v in context["items"]] == [version2]
    assert context["items"][0]["priority_weight"] > 1
    assert graph._run("MATCH (:ProfessionalEvidence {id:$new})-[:SUPERSEDES]->"
                     "(:ProfessionalEvidence {id:$old}) RETURN 1", {"new": version2, "old": version1}) == [[1]]
    pipeline.process(PlatformEvent(event_id=uuid4(), kind="professional.author-status", entity_id=author,
        revision=2, occurred_at=now, payload={"author_id": author, "verified": False}))
    revoked = professional_context(graph, "TESTPAINT", end-180*86400, end)
    assert revoked["items"][0]["priority_weight"] == 1.0
    pipeline.process(PlatformEvent(event_id=uuid4(), kind="professional.retracted", entity_id=contribution,
        revision=3, occurred_at=now + timedelta(seconds=4), payload={"ticker": "TESTPAINT", "reason": "Withdrawn"}))
    pipeline.process(second)
    assert professional_context(graph, "TESTPAINT", end-180*86400, end)["items"] == []


def test_live_document_revisions_guidance_citations_and_vectors(graph):
    from datetime import timedelta

    from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
    from stockgraph.application.processors.stock_profile_provider import StockProfileProvider
    from stockgraph.application.professional import EvidencePipeline
    from stockgraph.domain.platform_events import PlatformEvent
    seed_graph(graph)
    evidence = EvidenceRepository(graph)
    evidence.ensure_indexes()
    document_id = str(uuid4())
    now = datetime.now(UTC) - timedelta(seconds=30)
    version1, version2 = str(uuid4()), str(uuid4())
    def extracted(revision, version, text):
        return PlatformEvent(event_id=uuid4(), kind="document.extracted", entity_id=document_id,
            revision=revision, occurred_at=now + timedelta(seconds=revision), payload={
            "ticker": "TESTPAINT", "version_id": version, "document_id": document_id,
            "content_hash": str(revision) * 64, "title": "Earnings call", "source_url": "https://example.org/call",
            "document_kind": "GUIDANCE", "chunks": [{"id": version + ":0", "text": text,
            "page": 2, "ordinal": 0, "locator": "page 2, characters 1-40"}]})
    class Embedder:
        def embed_one(self, text):
            return [1.0] + [0.0] * (settings.embedding_dimension - 1)
    pipeline = EvidencePipeline(graph, Embedder())
    first, second = extracted(1, version1, "Old guidance"), extracted(2, version2, "New guidance")
    pipeline.process(second)
    pipeline.process(first)
    card = StockProfileProvider(graph).build_context_card("TESTPAINT")
    assert len(card.latest_guidance_highlights) == 1
    assert "New guidance" in card.latest_guidance_highlights[0]
    assert version2 in card.latest_guidance_highlights[0] and "page 2" in card.latest_guidance_highlights[0]
    chunks = evidence.document_page("TESTPAINT", "guidance")
    assert len(chunks) == 2 and all("embedding" not in c for c in chunks)
    rows = graph._run("CALL db.idx.vector.queryNodes('DocumentChunk','embedding',5,vecf32($embedding)) "
                     "YIELD node,score RETURN node.id,score", {"embedding": Embedder().embed_one("")})
    assert {row[0] for row in rows} == {version1 + ":0", version2 + ":0"}
