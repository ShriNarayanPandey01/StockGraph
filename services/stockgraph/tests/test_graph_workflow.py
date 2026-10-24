"""Offline contracts for stock registration, graph routing and durable retries."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from stockgraph.adapters.messaging.consumer import EventConsumer
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.application.ingestion.pipeline import GraphPipeline
from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver
from stockgraph.application.processors.news_graph_extractor import NewsGraphExtractor
from stockgraph.domain.enums import Window
from stockgraph.domain.events import CommittedEvent
from stockgraph.runtime.api import create_app
from stockgraph.runtime.settings import settings


class Broker:
    def __init__(self):
        self.values, self.hashes, self.acks = {}, {}, []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, **kwargs):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, key, *args, mapping=None):
        self.hashes.setdefault(key, {}).update(mapping or {args[0]: args[1]})

    def xack(self, stream, group, message_id):
        self.acks.append(message_id)


class Repo:
    def __init__(self, count=1):
        self.entities = {
            ("Stock", f"STOCK{i}"): {
                "ticker": f"STOCK{i}",
                "name": f"Company {i}",
                "business_summary": "Refines crude oil into fuels",
                "strengths": ["Distribution"],
                "business_exclusions": ["No mining"],
            }
            for i in range(count)
        }
        self.entities[("Commodity", "BRENT_CRUDE")] = {"id": "BRENT_CRUDE", "name": "Brent Crude"}
        self.entities[("MacroFactor", "USD_INR_FX")] = {"id": "USD_INR_FX", "name": "Rupee"}
        self.news, self.impacts, self.shocks, self.old_news, self.embeddings = {}, [], [], [], []
        self.projections = 0

    def get_entity(self, kind, entity_id):
        return self.entities.get((kind, entity_id))

    def catalog(self):
        return {
            kind: [value for (label, _), value in self.entities.items() if label == kind]
            for kind in ("Stock", "Commodity", "MacroFactor", "Sector")
        }

    def get_active_exposures(self, ticker):
        return ["BRENT_CRUDE", "USD_INR_FX"]

    def project_entity(self, kind, entity_id, entity, revision, event_ts):
        self.projections += 1
        self.entities[(kind, entity_id)] = {
            **entity,
            "revision": revision,
            "processing_state": "graph_processing",
        }

    def mark_entity_processed(self, kind, entity_id, revision):
        self.entities[(kind, entity_id)].update(
            inference_revision=revision, processing_state="completed"
        )

    def mark_entity_failed(self, kind, entity_id):
        self.entities[(kind, entity_id)]["processing_state"] = "failed"

    def historical_news(self, cutoff, offset, limit):
        return self.old_news[offset : offset + limit]

    def merge_stock_profile_embedding(self, ticker, embedding):
        self.embeddings.append(ticker)

    def rotate_dynamic_ontology_edges(self, *args):
        return 0

    def find_news(self, news_id):
        return self.news.get(news_id)

    def find_text_dup(self, *args):
        return None

    def find_near_dup(self, *args):
        return None

    def merge_news_event(self, props, embedding=None):
        self.news.setdefault(props["id"], {}).update(props)
        return props

    def merge_stock_impact(self, news_id, ticker, kind, confidence, rationale, **kwargs):
        self.impacts.append((news_id, ticker, kind))

    def merge_news_shock(self, news_id, kind, entity_id, *args, **kwargs):
        self.shocks.append((news_id, entity_id))

    def find_correlation_candidates(self, *args, **kwargs):
        return []


class Chat:
    def __init__(self, fail=False):
        self.prompts, self.fail = [], fail

    def complete_json(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider unavailable")
        if schema.__name__ == "NewsImpactBatch":
            tickers = [
                line.split(": ", 1)[1]
                for line in prompt.splitlines()
                if line.startswith("TICKER: ")
            ]
            return schema.model_validate(
                {
                    "impacts": [
                        {
                            "ticker": ticker,
                            "impact_type": "INDIRECTLY_IMPACTS",
                            "confidence": 0.9,
                            "rationale": "Crude is a refinery input",
                            "shocked_entity_id": "BRENT_CRUDE",
                        }
                        for ticker in tickers
                    ]
                }
            )
        if schema.__name__ == "NewsMarketImpactBatch":
            return schema.model_validate(
                {
                    "impacts": [
                        {
                            "entity_id": "BRENT_CRUDE",
                            "impact_type": "SHOCKS",
                            "confidence": 0.9,
                            "rationale": "Oil supply shock",
                        }
                    ]
                }
            )
        return schema()


class Embedder:
    def embed_one(self, text):
        return [1.0, 0.0]


def make_event(kind="news.received", **updates):
    payload = {
        "external_id": "article-1",
        "headline": "Oil prices rise after supply cuts",
        "summary": "Refiners face higher input costs",
        "source_url": "https://example.com/oil",
        "source": "RSS",
        "published_at": datetime.now(UTC).isoformat(),
        "category": "COMMODITY",
        "eligibility": {
            "version": 1,
            "decision": "APPROVED",
            "source": "RULES",
            "reason": "CLEAR_COMMODITY",
        },
    }
    values = dict(
        schema_version=1,
        event_id=str(uuid4()),
        kind=kind,
        entity_id="article-1",
        revision=1,
        occurred_at=datetime.now(UTC),
        payload=payload,
        job_id=str(uuid4()),
    )
    values.update(updates)
    return CommittedEvent.model_validate(values)


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)


def test_news_routes_all_stocks_beyond_old_eight_cap():
    repo, broker, chat = Repo(count=30), Broker(), Chat()
    GraphPipeline(repo, broker, chat, Embedder()).process(make_event())
    assert {impact[1] for impact in repo.impacts} == {f"STOCK{i}" for i in range(30)}
    assert len(repo.news) == 1
    assert repo.shocks
    assert any("Business exclusions: No mining" in prompt for prompt in chat.prompts)


def test_new_stock_backfills_existing_news_without_new_news_or_url_dedup():
    repo, broker = Repo(), Broker()
    repo.old_news = [
        {"id": "existing-canonical", "headline": "Oil prices rise", "summary": "Input costs rise"}
    ]
    event = make_event(
        "registry.updated",
        entity_id="NEWCO",
        payload={
            "kind": "Stock",
            "entity": {
                "ticker": "NEWCO",
                "name": "New company",
                "business_summary": "Refines crude",
            },
        },
    )
    GraphPipeline(repo, broker, Chat(), Embedder()).process(event)
    assert ("existing-canonical", "NEWCO", "INDIRECTLY_IMPACTS") in repo.impacts
    assert not repo.news
    assert repo.entities[("Stock", "NEWCO")]["processing_state"] == "completed"


def test_llm_disabled_projects_but_does_not_report_semantic_completion(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)
    repo = Repo()
    event = make_event(
        "registry.updated",
        entity_id="NEWCO",
        payload={"kind": "Stock", "entity": {"ticker": "NEWCO"}},
    )
    with pytest.raises(RuntimeError, match="LLM_ENABLED"):
        GraphPipeline(repo, Broker(), Chat(), Embedder()).process(event)
    assert repo.entities[("Stock", "NEWCO")]["processing_state"] == "graph_processing"


def test_stale_registry_event_cannot_overwrite_newer_projection():
    repo = Repo()
    repo.entities[("Stock", "STOCK0")]["revision"] = 5
    event = make_event(
        "registry.updated",
        entity_id="STOCK0",
        payload={"kind": "Stock", "entity": {"ticker": "STOCK0"}},
    )
    GraphPipeline(repo, Broker(), Chat(), Embedder()).process(event)
    assert repo.projections == 0


def test_failure_retry_keeps_same_url_owner_and_routes_existing_news():
    repo, broker = Repo(), Broker()
    event = make_event()
    with pytest.raises(RuntimeError, match="LLM inference failed"):
        GraphPipeline(repo, broker, Chat(fail=True), Embedder()).process(event)
    assert len(repo.news) == 1
    GraphPipeline(repo, broker, Chat(), Embedder()).process(event)
    assert repo.impacts
    assert len(repo.news) == 1


def test_same_url_from_second_event_is_dropped():
    repo, broker = Repo(), Broker()
    pipeline = GraphPipeline(repo, broker, Chat(), Embedder())
    pipeline.process(make_event())
    before = len(repo.impacts)
    pipeline.process(make_event())
    assert len(repo.impacts) == before


def test_worker_acknowledges_only_success_and_recovers_failed_event(monkeypatch):
    import stockgraph.adapters.messaging.consumer as consumer_module

    @contextmanager
    def no_lock(redis):
        yield True

    monkeypatch.setattr(consumer_module, "renewable_lock", no_lock)
    repo, broker = Repo(), Broker()
    pipeline = GraphPipeline(repo, broker, Chat(fail=True), Embedder())
    consumer = EventConsumer(broker, pipeline)
    event = make_event()
    fields = {"event": event.model_dump_json()}
    assert not consumer.handle("1-0", fields)
    assert not broker.acks
    assert broker.hashes[f"stockgraph:job:{event.job_id}"]["state"] == "failed"
    pipeline._chat = Chat()
    assert consumer.handle("1-0", fields)
    assert broker.acks == ["1-0"]
    assert broker.hashes[f"stockgraph:job:{event.job_id}"]["state"] == "completed"


def test_context_contains_commodity_macro_and_indirect_path_with_pagination():
    repo = Repo()
    news = {
        "id": "oil-1",
        "headline": "Oil supply cut",
        "source": "Exchange filing",
        "source_url": "https://example.com/oil-supply-cut",
        "event_date": "2026-10-22",
    }
    confidence = {"confidence": 0.9, "rationale": "Input", "valid_from_ts": 0, "inferred_by": "LLM"}
    macro = {
        "confidence": 1.0,
        "baseline": True,
        "rationale": "All stocks",
        "inferred_by": "policy_baseline",
    }
    repo.context_page = lambda *args: {
        "ontology": [
            ("Commodity", {"id": "BRENT_CRUDE"}, "EXPOSED_TO", confidence),
            ("MacroFactor", {"id": "USD_INR_FX"}, "SENSITIVE_TO_MACRO", macro),
        ],
        "direct": [(news, "DIRECTLY_IMPACTS", confidence)],
        "indirect": [
            (
                news,
                "Commodity",
                {"id": "BRENT_CRUDE"},
                "EXPOSED_TO",
                confidence,
                "SHOCKS",
                confidence,
            )
        ],
    }
    result = GraphContextService(repo).get_context("stock0", Window.LAST_1Y, limit=1)
    assert {node.kind for node in result.nodes} == {"Stock", "Commodity", "NewsEvent"}
    assert {edge.relation for edge in result.edges} == {
        "DIRECTLY_IMPACTS",
        "EXPOSED_TO",
        "SHOCKS",
    }
    assert result.pagination["next_offset"] == 1
    assert result.direct_news[0].citation.url == "https://example.com/oil-supply-cut"
    assert result.direct_news[0].citation.publisher == "Exchange filing"
    assert result.indirect_news[0].via_node == "Commodity:BRENT_CRUDE"
    assert result.indirect_news[0].citation.title == "Oil supply cut"
    result = GraphContextService(repo).get_context("stock0", Window.LAST_1Y, limit=2)
    assert any(node.kind == "MacroFactor" for node in result.nodes)


def test_low_confidence_and_unknown_entities_do_not_create_edges():
    resolver = CanonicalEntityResolver.from_catalog(Repo().catalog())
    extractor = NewsGraphExtractor(Chat(), resolver)
    from stockgraph.domain.schemas import InferredNewsStockImpact

    bad = [
        InferredNewsStockImpact(
            ticker="STOCK0", impact_type="DIRECTLY_IMPACTS", confidence=0.4, rationale="Maybe"
        ),
        InferredNewsStockImpact(
            ticker="INVENTED", impact_type="DIRECTLY_IMPACTS", confidence=0.9, rationale="Maybe"
        ),
    ]
    assert extractor.filter_impacts("news", bad) == []


def test_context_queries_use_temporal_overlap_confidence_and_literal_pagination():
    repo = GraphRepository(graph_name="never_connect")
    captured = []
    repo._run = lambda query, params: captured.append((query, params)) or []
    repo.context_page("STOCK0", 10, 20, 50, 50)
    assert len(captured) == 3
    assert all("SKIP 50 LIMIT 51" in query for query, _ in captured)
    assert "exp.valid_to_ts" in captured[0][0]
    assert all("confidence" in query for query, _ in captured)


def test_api_registration_returns_accepted_and_separate_processing_status():
    class Data:
        async def register_stock(self, payload):
            return {"job_id": "job", "state": "pending"}

        async def job_status(self, job):
            return {"job_id": job, "state": "graph_processing"}

    broker, repo = Broker(), Repo()
    client = TestClient(create_app(repo, broker, Data()))
    response = client.post("/api/v1/stocks", json={"query": "Reliance"})
    assert response.status_code == 202
    job = str(uuid4())
    broker.hset(f"stockgraph:job:{job}", mapping={"state": "completed"})
    status = client.get(f"/api/v1/jobs/{job}").json()
    assert status["data_state"] == "graph_processing" and status["graph_state"] == "completed"
    assert client.get("/api/v1/stocks/STOCK0/context?window=ALL").status_code == 422
    assert client.get("/api/v1/stocks/STOCK0/context?from_date=2020-01-01").status_code == 422


def test_manual_graph_api_proxies_entities_news_and_stock_registration():
    class Data:
        async def register_stock(self, payload):
            return {"job_id": "job", "state": "pending", "query": payload["query"]}

        async def upsert_entity(self, kind, payload):
            return {"entity_id": payload["id"], "revision": 1, "changed": True, "state": "graph_processing", "kind": kind}

        async def submit_manual_news(self, payload):
            return {"external_id": "manual-1", "state": "queued", "headline": payload["headline"]}

    client = TestClient(create_app(Repo(), Broker(), Data()))
    assert client.post("/api/v1/manual/stocks", json={"query": "Reliance"}).status_code == 202
    entity = client.post(
        "/api/v1/manual/entities/Commodity",
        json={"id": "LITHIUM_CARBONATE", "name": "Lithium Carbonate"},
    )
    assert entity.status_code == 202 and entity.json()["state"] == "graph_processing"
    news = client.post(
        "/api/v1/manual/news",
        json={
            "headline": "Lithium prices rise",
            "source_url": "https://example.test/lithium-rise",
            "published_at": "2026-10-23T09:00:00+00:00",
            "category": "COMMODITY",
        },
    )
    assert news.status_code == 202 and news.json()["state"] == "queued"


def test_developer_edge_api_is_disabled_by_default():
    client = TestClient(create_app(Repo(), Broker(), object()))
    response = client.post(
        "/api/v1/developer/edges",
        json={
            "source": {"kind": "Stock", "id": "STOCK0"},
            "target": {"kind": "Commodity", "id": "BRENT_CRUDE"},
            "relation": "MANUALLY_REVIEWED",
            "rationale": "Developer review",
            "actor": "local-developer",
        },
    )
    assert response.status_code == 403


def test_developer_edge_api_creates_and_deletes_only_developer_links(monkeypatch):
    import stockgraph.runtime.api as api_module

    class DeveloperRepo(Repo):
        def set_write_guard(self, guard):
            self.guard = guard

        def create_developer_edge(self, **kwargs):
            self.created = kwargs
            return {
                "edge_id": "developer:1",
                "source": {"kind": kwargs["source_kind"], "id": kwargs["source_id"]},
                "target": {"kind": kwargs["target_kind"], "id": kwargs["target_id"]},
                "relation": kwargs["relation"],
                "rationale": kwargs["rationale"],
                "actor": kwargs["actor"],
                "confidence": kwargs["confidence"],
                "event_ts": 1,
                "metadata": kwargs["metadata"],
            }

        def delete_developer_edge(self, edge_id):
            self.deleted = edge_id
            return edge_id == "developer:1"

    @contextmanager
    def graph_lock(_broker):
        yield lambda: None

    monkeypatch.setattr(settings, "developer_graph_mutations_enabled", True)
    monkeypatch.setattr(api_module, "renewable_lock", graph_lock)
    repo = DeveloperRepo()
    client = TestClient(create_app(repo, Broker(), object()))
    created = client.post(
        "/api/v1/developer/edges",
        json={
            "source": {"kind": "Stock", "id": "STOCK0"},
            "target": {"kind": "Commodity", "id": "BRENT_CRUDE"},
            "relation": "MANUALLY_REVIEWED",
            "rationale": "Developer reviewed the exposure.",
            "actor": "local-developer",
            "confidence": 0.9,
            "metadata": {"ticket": "SG-123"},
        },
    )
    assert created.status_code == 201
    assert repo.created["relation"] == "MANUALLY_REVIEWED"
    assert created.json()["edge_id"] == "developer:1"
    assert client.delete("/api/v1/developer/edges/developer:1").json() == {
        "edge_id": "developer:1",
        "deleted": True,
    }
    assert client.delete("/api/v1/developer/edges/developer:missing").status_code == 404


def test_service_package_has_no_sql_driver_or_cross_service_imports():
    import ast
    from pathlib import Path

    package = Path(__file__).parents[1] / "src" / "stockgraph"
    forbidden = ("asyncpg", "sqlalchemy", "upstox_service", "src.")
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                assert not any(alias.name.startswith(forbidden) for alias in item.names), str(path)
            elif isinstance(item, ast.ImportFrom):
                assert not (item.module or "").startswith(forbidden), str(path)
    assert not hasattr(settings, "timescale_dsn")


def test_malformed_llm_output_is_retryable_not_empty_success():
    class InvalidChat:
        def complete_json(self, prompt, schema, **kwargs):
            return "not structured JSON"

    with pytest.raises(RuntimeError, match="LLM inference failed"):
        GraphPipeline(Repo(), Broker(), InvalidChat(), Embedder()).process(make_event())


def test_event_payload_identity_must_match_canonical_identity():
    repo = Repo()
    event = make_event(
        "registry.updated",
        entity_id="NEWCO",
        payload={"kind": "Stock", "entity": {"ticker": "SOMEONE_ELSE"}},
    )
    with pytest.raises(ValueError, match="identity"):
        GraphPipeline(repo, Broker(), Chat(), Embedder()).process(event)
    assert repo.projections == 0


def test_pagination_cannot_be_used_as_arbitrary_historical_date_api():
    client = TestClient(create_app(Repo(), Broker(), object()))
    stale = int(datetime.now(UTC).timestamp()) - settings.pagination_snapshot_max_age_seconds - 1
    assert client.get(f"/api/v1/stocks/STOCK0/context?as_of_ts={stale}").status_code == 422


@pytest.mark.asyncio
async def test_mcp_tool_is_registered_with_fixed_windows():
    from stockgraph.adapters.api.mcp_server import build_server

    tools = await build_server().list_tools()
    indexed = {tool.name: tool for tool in tools}
    assert set(indexed) == {"get_stock_graph_context", "get_professional_evidence",
                            "search_stock_documents", "get_stock_financial_history", "get_document_version"}
    assert "window" in indexed["get_stock_graph_context"].input_schema["properties"]


def test_repository_refuses_writes_after_lease_loss():
    repo = GraphRepository(graph_name="never_connect")

    def lost():
        raise RuntimeError("Lease lost")

    repo.set_write_guard(lost)
    with pytest.raises(RuntimeError, match="Lease lost"):
        repo.merge_stock_profile_embedding("STOCK0", [1.0, 0.0])


def test_repository_developer_edges_parameterize_node_labels_and_delete_by_id():
    repo = GraphRepository(graph_name="never_connect")
    captured = []
    repo._run = lambda query, params: captured.append((query, params)) or [[params.get("edge_id")]]
    edge = repo.create_developer_edge(
        source_kind="Stock",
        source_id="STOCK0",
        target_kind="Commodity",
        target_id="BRENT_CRUDE",
        relation="MANUALLY_REVIEWED",
        rationale="Developer review",
        actor="local-developer",
        confidence=0.9,
        metadata={"ticket": "SG-123"},
    )
    assert edge["source"] == {"kind": "Stock", "id": "STOCK0"}
    create_query, create_params = captured[-1]
    assert "$source_kind IN labels(source)" in create_query
    assert "DEVELOPER_LINK" in create_query
    assert create_params["source_kind"] == "Stock"
    assert repo.delete_developer_edge(edge["edge_id"])
    delete_query, delete_params = captured[-1]
    assert "DELETE r" in delete_query
    assert delete_params["edge_id"] == edge["edge_id"]


def test_stream_pending_entries_are_recovered_before_new_reads():
    broker = Broker()
    event = make_event()
    broker.xautoclaim = lambda *args, **kwargs: [
        "0-0",
        [("1-0", {"event": event.model_dump_json()})],
        [],
    ]
    consumer = EventConsumer(broker, GraphPipeline(Repo(), broker, Chat(), Embedder()))
    captured = []
    consumer.handle = lambda message_id, fields: captured.append(message_id) or True
    assert consumer.run_once() == 1
    assert captured == ["1-0"]


def test_dotenv_api_key_is_passed_privately_to_llm_and_embeddings(monkeypatch):
    import sys
    from types import SimpleNamespace

    from pydantic import SecretStr
    from stockgraph.adapters.llm.providers import LiteLLMChatProvider, LiteLLMEmbeddingProvider
    from stockgraph.application.processors.news_graph_extractor import NewsImpactBatch
    from stockgraph.runtime.settings import Settings

    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"impacts":[]}'))]
        )

    def embedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [1.0, 0.0]}])

    monkeypatch.setitem(
        sys.modules, "litellm", SimpleNamespace(completion=completion, embedding=embedding)
    )
    import stockgraph.adapters.llm.providers as providers

    monkeypatch.setattr(providers, "count_tokens", lambda text, model=None: len(text.split()))
    secret = SecretStr("test-secret-never-log")
    monkeypatch.setattr(settings, "openai_api_key", secret)
    monkeypatch.setattr(settings, "embedding_dimension", 2)
    LiteLLMChatProvider().complete_json("test", NewsImpactBatch)
    LiteLLMEmbeddingProvider().embed_one("test")
    assert len(calls) == 2 and all(call["api_key"] == secret.get_secret_value() for call in calls)
    assert secret.get_secret_value() not in repr(Settings(_env_file=None, openai_api_key=secret))


def test_newer_news_revision_retries_old_url_without_losing_routing():
    repo, broker = Repo(), Broker()
    first = make_event()
    with pytest.raises(RuntimeError):
        GraphPipeline(repo, broker, Chat(fail=True), Embedder()).process(first)
    newer = first.model_copy(update={"event_id": uuid4(), "revision": 2})
    pipeline = GraphPipeline(repo, broker, Chat(), Embedder())
    pipeline.process(newer)
    assert repo.impacts
    count = len(repo.impacts)
    pipeline.process(first)
    assert len(repo.impacts) == count


def test_openai_key_is_not_sent_to_other_llm_providers():
    from pydantic import SecretStr
    from stockgraph.adapters.llm.providers import _openai_credentials

    assert _openai_credentials(SecretStr("not-for-gemini"), "gemini/gemini-2.5-flash") == {}
