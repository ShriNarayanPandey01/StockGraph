from stockgraph.application.graph_queries.public_preview import PublicMarketGraphService
from stockgraph.runtime.api import create_app
from fastapi.testclient import TestClient


class PreviewRepo:
    def __init__(self):
        self.calls = 0

    def public_market_graph_data(self, _start, _end):
        self.calls += 1
        candidates = [
            {"stock": {"ticker": ticker, "name": ticker, "processing_state": "completed"}, "news_count": 5 - index, "ontology_count": 3}
            for index, ticker in enumerate(("ALPHA", "BETA", "GAMMA"))
        ]
        ontology = [
            {
                "source": {"ticker": "ALPHA"}, "target_kind": "Stock", "target": {"ticker": "BETA"},
                "relation": "COMPETES_WITH", "properties": {"confidence": 0.9, "rationale": "Peer"},
            },
            {
                "source": {"ticker": "ALPHA"}, "target_kind": "Commodity", "target": {"id": "BRENT", "name": "Brent"},
                "relation": "EXPOSED_TO", "properties": {"confidence": 0.9, "baseline": False},
            },
            {
                "source": {"ticker": "BETA"}, "target_kind": "MacroFactor", "target": {"id": "USD_INR", "name": "USD/INR"},
                "relation": "SENSITIVE_TO_MACRO", "properties": {"confidence": 0.8, "baseline": False},
            },
        ]
        news = {"id": "news-1", "headline": "Oil supply tightens", "event_ts": 1_700_000_000, "embedding": [0.1]}
        return {
            "candidates": candidates,
            "ontology": ontology,
            "impacts": [{"news": news, "stock": {"ticker": "ALPHA"}, "relation": "DIRECTLY_IMPACTS", "properties": {"confidence": 0.95, "causal_rationale": "Input cost"}}],
            "shocks": [{"news": news, "target_kind": "Commodity", "target": {"id": "BRENT", "name": "Brent"}, "relation": "SHOCKS", "properties": {"confidence": 0.9}}],
            "correlations": [],
            "related": [],
        }


def test_public_preview_is_small_connected_and_safe():
    response = PublicMarketGraphService(PreviewRepo()).get_preview(now_ts=1_700_000_100)
    ids = {node.id for node in response.nodes}
    assert response.start_ts == 1_700_000_100 - 30 * 24 * 60 * 60
    assert {"Stock:ALPHA", "Stock:BETA", "Commodity:BRENT", "NewsEvent:news-1"} <= ids
    assert all("embedding" not in node.properties and "processing_state" not in node.properties for node in response.nodes)
    assert {edge.relation for edge in response.edges} >= {"COMPETES_WITH", "EXPOSED_TO", "DIRECTLY_IMPACTS", "SHOCKS"}
    assert response.selection.is_partial
    assert response.selection.edge_count <= 60


def test_stock_selection_prefers_connected_candidates_over_unconnected_rank():
    data = PreviewRepo().public_market_graph_data(0, 1)
    data["candidates"].append({"stock": {"ticker": "DELTA"}, "news_count": 4, "ontology_count": 3})
    data["ontology"].append(
        {
            "source": {"ticker": "GAMMA"}, "target_kind": "Stock", "target": {"ticker": "ALPHA"},
            "relation": "SUPPLIES_TO", "properties": {"confidence": 0.8},
        }
    )
    service = PublicMarketGraphService(PreviewRepo())
    selected = service._choose_stocks(data["candidates"], data["ontology"])
    assert [stock["ticker"] for stock in selected[:3]] == ["ALPHA", "BETA", "GAMMA"]


class Broker:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **_kwargs):
        self.values[key] = value
        return True

    def hgetall(self, _key):
        return {}


def test_public_market_graph_api_caches_and_rejects_parameters():
    class Data:
        pass

    broker = Broker()
    repo = PreviewRepo()
    app = create_app(repo, broker, Data())
    client = TestClient(app)
    first = client.get("/api/v1/public/market-graph")
    assert first.status_code == 200
    assert "stockgraph:public-market-graph:v1" in broker.values
    assert client.get("/api/v1/public/market-graph?window=LAST_1Y").status_code == 422
    assert client.get("/api/v1/public/market-graph").json() == first.json()
    assert repo.calls == 1


def test_preview_repository_filters_broad_baseline_and_internal_edges():
    from stockgraph.adapters.repositories.falkor.repository import GraphRepository

    repo = GraphRepository(graph_name="never-connect")
    captured = []
    repo._run = lambda query, params: captured.append((query, params)) or []
    assert repo.public_market_graph_data(10, 20) == {
        "candidates": [], "ontology": [], "impacts": [], "shocks": [], "correlations": [], "related": []
    }
    queries = "\n".join(query for query, _ in captured)
    assert len(captured) == 6
    assert "coalesce(ontology.baseline,false)" in queries
    assert "DUPLICATE_OF" in queries
    assert "DEVELOPER_LINK" not in queries
