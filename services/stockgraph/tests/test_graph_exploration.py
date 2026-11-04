"""Interactive exploration expands real paths without paging the evidence graph."""

from fastapi.testclient import TestClient
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.application.graph_queries.exploration import stock_exploration
from stockgraph.domain.enums import Window
from stockgraph.runtime.api import create_app


def connection(number, source_kind, source, relation, target_kind, target):
    return (number, source_kind, source, relation,
            {"confidence": 0.9, "edge_id": f"edge-{number}", "rationale": "Evidence"},
            target_kind, target)


class Neighborhood:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or [
            connection(1, "Stock", {"ticker": "ROOT"}, "EXPOSED_TO", "Commodity", {"id": "OIL"}),
            connection(2, "NewsEvent", {"id": "news", "headline": "Oil supply cut"},
                       "SHOCKS", "Commodity", {"id": "OIL"}),
            connection(3, "NewsEvent", {"id": "prior", "embedding": [0.1]},
                       "CORRELATED_WITH", "NewsEvent", {"id": "news"}),
            connection(4, "Stock", {"ticker": "FAR"}, "DIRECTLY_IMPACTS",
                       "NewsEvent", {"id": "prior"}),
        ]

    def get_entity(self, kind, identity):
        return {"ticker": identity, "processing_state": "completed"}

    def context_page(self, *args):
        return {"ontology": [], "direct": [], "indirect": []}

    def exploration_neighbors(self, frontier, start, end, limit):
        self.calls.append((list(frontier), start, end))
        def key(kind, props):
            return f"{kind}:{props.get('ticker') if kind == 'Stock' else props['id']}"
        return [r for r in self.rows if key(r[1], r[2]) in frontier or key(r[5], r[6]) in frontier][:limit+1]


def test_depth_expands_inbound_paths_and_excludes_nodes_beyond_selected_hop():
    repo = Neighborhood()
    for hops, expected in ((1, {"Stock:ROOT", "Commodity:OIL"}),
                           (2, {"Stock:ROOT", "Commodity:OIL", "NewsEvent:news"}),
                           (3, {"Stock:ROOT", "Commodity:OIL", "NewsEvent:news", "NewsEvent:prior"})):
        repo.calls.clear()
        result = stock_exploration(repo, {"ticker": "ROOT"}, 10, 20, hops)
        assert {node.id for node in result.nodes} == expected
        assert max(result.distances.values()) == hops
        assert len(repo.calls) == hops
        assert all(call[1:] == (10, 20) for call in repo.calls)
        assert len(result.edges) == hops  # Previously visited edges do not duplicate.
        assert not result.truncated
        assert all("embedding" not in node.properties for node in result.nodes)
    assert result.edges[1].source == "NewsEvent:news"
    assert result.edges[1].target == "Commodity:OIL"


def test_exploration_is_independent_of_evidence_page_and_snapshot_is_shared():
    repo = Neighborhood()
    service = GraphContextService(repo)
    first = service.get_context("ROOT", Window.LAST_6M, limit=1, hops=3)
    later = service.get_context("ROOT", Window.LAST_6M, offset=50, limit=2,
                                as_of_ts=first.pagination["as_of_ts"], hops=3)
    assert first.exploration == later.exploration
    assert first.pagination["offset"] == 0
    assert later.pagination["offset"] == 50
    assert service.get_context("ROOT", Window.LAST_6M).exploration is None


def test_root_and_peer_nodes_decode_profiles_without_exposing_raw_profile_or_embeddings():
    profile = '{"business_summary":"An energy business","name":"Old name","embedding":[0.1]}'
    stock = {"ticker": "ROOT", "name": "Current name", "profile_json": profile,
             "profile_embedding": [0.2]}
    peer = {"ticker": "PEER", "name": "Current name", "profile_json": profile}
    repo = Neighborhood([connection(1, "Stock", stock, "COMPETES_WITH", "Stock", peer)])
    result = stock_exploration(repo, stock, 10, 20, 1)
    for node in result.nodes:
        assert node.properties["business_summary"] == "An energy business"
        assert node.properties["name"] == "Current name"
        assert "profile_json" not in node.properties
        assert "profile_embedding" not in node.properties
        assert "embedding" not in node.properties


def test_large_neighborhood_is_bounded_connected_and_reports_truncation():
    rows = [connection(i, "Stock", {"ticker": "ROOT"}, "EXPOSED_TO",
                       "Commodity", {"id": f"commodity-{i}"}) for i in range(300)]
    result = stock_exploration(Neighborhood(rows), {"ticker": "ROOT"}, 10, 20, 3)
    assert result.truncated
    assert len(result.nodes) == result.node_limit == 200
    identities = {node.id for node in result.nodes}
    assert all(edge.source in identities and edge.target in identities for edge in result.edges)
    assert len(result.edges) <= result.edge_limit


def test_parallel_edges_do_not_exhaust_budget_before_third_hop():
    repo = Neighborhood()
    repo.rows = [repo.rows[0], *[
        connection(100+i, "Stock", {"ticker": "ROOT"}, "EXPOSED_TO",
                   "Commodity", {"id": "OIL"}) for i in range(600)
    ], *repo.rows[1:]]
    result = stock_exploration(repo, {"ticker": "ROOT"}, 10, 20, 3)
    assert result.distances["NewsEvent:prior"] == 3
    assert len(result.edges) == result.edge_limit == 500
    assert result.truncated


def test_query_guards_both_endpoints_and_preserves_original_edge_direction():
    repo = GraphRepository(graph_name="never_connect")
    captured = []
    repo._run = lambda query, params: captured.append((query, params)) or []
    repo.exploration_neighbors(["Stock:ROOT"], 10, 20)
    query, params = captured[0]
    assert "LIMIT 1001" in query
    assert "r.confidence,0)>=$confidence" in query
    assert "r.valid_to_ts,9999999999)>=$start" in query
    for alias in ("a", "b"):
        assert f"{alias}.event_ts >= $start AND {alias}.event_ts <= $end" in query
        assert f"NOT ({alias})-[:DUPLICATE_OF]->()" in query
    assert "properties(startNode(r))" in query
    assert "properties(endNode(r))" in query
    assert "ProfessionalEvidence" not in params["kinds"]
    assert params["frontier"] == ["Stock:ROOT"]


def test_api_accepts_only_bounded_hop_values():
    with TestClient(create_app(Neighborhood(), object(), object()),
                    headers={"X-Internal-Service-Key": "test-internal-key"}) as client:
        result = client.get("/api/v1/stocks/ROOT/context?hops=3")
        assert result.status_code == 200
        assert result.json()["exploration"]["distances"]["NewsEvent:prior"] == 3
        for bad in ("0", "4", "all", "-1", "2.5"):
            assert client.get(f"/api/v1/stocks/ROOT/context?hops={bad}").status_code == 422
        assert client.get("/api/v1/stocks/ROOT/context?hops=3&from_date=2020-01-01").status_code == 422
