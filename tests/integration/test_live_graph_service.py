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
    assert context.indirect_news[0]["id"] == "oil-shock"
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
    assert len({p.direct_news[0]["id"] for p in (first, second, final)}) == 3
    assert all(p.direct_news[0]["id"] != "weak" for p in (first, second, final))
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
