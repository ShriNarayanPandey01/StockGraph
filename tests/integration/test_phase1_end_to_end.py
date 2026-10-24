"""Real HTTP/SQL/Redis/Falkor workflow; provider and inference outputs are fixtures.

Opt in with RUN_PHASE1_E2E=1, PLATFORM_TEST_DATABASE_DSN pointing to an existing
local platform_test_* database, and E2E_REDIS_URL pointing to a disposable empty
Redis instance (default localhost:16380). No paid provider or model is contacted.
"""

import asyncio
import base64
import os
import re
import socket
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import httpx
import pytest
import redis
import uvicorn
from redis.asyncio import Redis

pytestmark = pytest.mark.skipif(os.getenv("RUN_PHASE1_E2E") != "1", reason="Opt-in isolated real-service integration")


@asynccontextmanager
async def serve_http(app):
    """Use real ephemeral loopback sockets, not ASGITransport or test-client mocks."""
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on"))
    server.capture_signals = lambda: nullcontext()
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                raise RuntimeError("Isolated HTTP server stopped before startup")
            await asyncio.sleep(.02)
        assert server.started, "Isolated HTTP server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 10)
        finally:
            sock.close()


class FixtureCompanyProvider:
    async def fetch_company(self, request):
        from upstox_service.domain.models import CompanyBundle
        assert request.query == "RELIANCE"
        return CompanyBundle(
            entity={"ticker":"RELIANCE", "isin":"INE002A01018", "name":"Reliance Industries Limited",
                    "aliases":["Reliance"], "business_summary":"Refining and petrochemicals use crude oil.",
                    "raw_material_inputs":["Crude oil"], "revenue_segments":["Refining"],
                    "geographic_exposure":"India", "exposures":["BRENT_CRUDE"]},
            raw={"fixture":True},
            checkpoint={"trade_date":datetime.now(UTC).date(), "session_type":"CLOSE",
                        "open_price":100, "high_price":105, "low_price":98,
                        "close_price":101, "volume":1000},
        )


class FixtureEmbedder:
    def embed_one(self, text):
        return [1.0, .2, .1]


class FixtureChat:
    """Typed deterministic output exercises routing without asserting model quality."""
    def complete_json(self, prompt, schema, **kwargs):
        name = schema.__name__
        if name == "OntologyEdgeBatch":
            return schema.model_validate({"edges":[{
                "source_id":"RELIANCE", "target_id":"BRENT_CRUDE", "relation":"EXPOSED_TO",
                "confidence":.95, "rationale":"Fixture business profile explicitly consumes crude oil.",
                "exposure_nature":"INPUT_COST", "margin_impact":"NEGATIVE", "sensitivity":.8}]})
        if name == "NewsImpactBatch":
            return schema.model_validate({"impacts":[{
                "ticker":"RELIANCE", "impact_type":"DIRECTLY_IMPACTS", "confidence":.95,
                "rationale":"Fixture filing names Reliance.", "shocked_entity_id":"BRENT_CRUDE"}]})
        if name == "NewsMarketImpactBatch":
            return schema.model_validate({"impacts":[{
                "entity_id":"BRENT_CRUDE", "impact_type":"SHOCKS", "confidence":.9,
                "rationale":"Fixture filing describes crude input costs."}]})
        return schema.model_validate({})


async def drain(consumer, expected):
    processed = 0
    for _ in range(max(5, expected * 3)):
        processed += await asyncio.to_thread(consumer.run_once, 1)
        if processed >= expected:
            return
    assert processed >= expected, "Committed events did not finish isolated graph projection"


@pytest.mark.asyncio
async def test_free_phase1_over_real_http_sql_streams_and_falkor(tmp_path, monkeypatch):
    from marketgraph_platform.agent_repository import schedule_due_monitors
    from marketgraph_platform.api import CanonicalClient
    from marketgraph_platform.api import create_app as platform_app
    from marketgraph_platform.auth import issue_token
    from marketgraph_platform.repository import Repository
    from marketgraph_platform.settings import Settings as PlatformSettings
    from marketgraph_platform.worker import relay_once
    from stockgraph.adapters.api.data_client import DataServiceClient
    from stockgraph.adapters.messaging.consumer import EventConsumer
    from stockgraph.adapters.messaging.platform_consumer import PlatformConsumer
    from stockgraph.adapters.repositories.falkor import legacy_repository
    from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
    from stockgraph.adapters.repositories.falkor.repository import GraphRepository
    from stockgraph.application.ingestion.pipeline import GraphPipeline
    from stockgraph.application.professional import EvidencePipeline
    from stockgraph.runtime.api import create_app as graph_app
    from stockgraph.runtime.settings import settings as graph_settings
    from upstox_service.adapters.api.main import create_app as data_app
    from upstox_service.adapters.messaging import RedisPublisher
    from upstox_service.adapters.repositories.timescale.catalog import DataRepository
    from upstox_service.application.stock_registration import RegistrationWorker
    from upstox_service.config.settings import Settings as DataSettings
    from upstox_service.domain.models import EntityKind

    dsn = os.environ.get("PLATFORM_TEST_DATABASE_DSN", "")
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"localhost","127.0.0.1","::1"} and parsed.path.startswith("/platform_test_"), "Use a disposable local platform_test_* database"
    redis_url = os.environ.get("E2E_REDIS_URL", "redis://localhost:16380/0")
    redis_target = urlsplit(redis_url)
    assert redis_target.hostname in {"localhost","127.0.0.1","::1"}, "Use isolated local Redis"
    assert (redis_target.port or 6379) >= 10000, "Use a dedicated Redis test port, never project Redis/Falkor"
    suffix = uuid4().hex
    data_schema, platform_schema, graph_name = (prefix+suffix for prefix in ("data_e2e_","platform_e2e_","stockgraph_test_"))
    admin = await asyncpg.connect(dsn)
    broker = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=10)
    transport = Redis.from_url(redis_url, decode_responses=True, socket_timeout=10)
    assert await transport.dbsize() == 0, "Refusing to alter a nonempty Redis instance"
    data, platform, canonical = None, None, None
    graph = GraphRepository(host=os.environ.get("E2E_FALKOR_HOST","localhost"),
                            port=int(os.environ.get("E2E_FALKOR_PORT","6379")), graph_name=graph_name)
    source_stream = "stockgraph:source-e2e:"+suffix
    platform_stream = "stockgraph:platform-events:v1"
    monkeypatch.setattr(graph_settings,"llm_enabled",True)
    monkeypatch.setattr(graph_settings,"event_stream",source_stream)
    monkeypatch.setattr(graph_settings,"event_consumer_group","e2e-source-"+suffix)
    monkeypatch.setattr(graph_settings,"platform_stream_name",platform_stream)
    monkeypatch.setattr(graph_settings,"platform_consumer_group","e2e-evidence-"+suffix)
    monkeypatch.setattr(legacy_repository,"INDEX_CYPHER_STATEMENTS",[
        re.sub(r"dimension: \d+", "dimension: 3", value) for value in legacy_repository.INDEX_CYPHER_STATEMENTS])
    config = PlatformSettings(_env_file=None, database_dsn=dsn, redis_url=redis_url,
                              agent_service_key="isolated-machine-"+suffix, outbox_stream=platform_stream)
    try:
        await admin.execute(f'CREATE SCHEMA "{data_schema}"')
        await admin.execute(f'CREATE SCHEMA "{platform_schema}"')
        data = DataRepository(dsn)
        data._pool = await asyncpg.create_pool(dsn,min_size=1,max_size=5,server_settings={"search_path":data_schema+",public"})
        await data.init_schema()
        platform = Repository(config)
        platform.pool = await asyncpg.create_pool(dsn,min_size=1,max_size=5,server_settings={"search_path":platform_schema})
        await platform.migrate()
        await asyncio.to_thread(graph.ensure_indexes_and_constraints)
        await asyncio.to_thread(EvidenceRepository(graph).ensure_indexes)
        source_consumer = EventConsumer(broker,GraphPipeline(graph,broker,FixtureChat(),FixtureEmbedder()))
        evidence_consumer = PlatformConsumer(broker,EvidencePipeline(graph,FixtureEmbedder()))
        await asyncio.to_thread(source_consumer.ensure_group)
        await asyncio.to_thread(evidence_consumer.ensure_group)
        await data.upsert_entity(EntityKind.COMMODITY,{"id":"BRENT_CRUDE","name":"Brent crude","description":"Oil input"})
        await data.upsert_entity(EntityKind.MACRO,{"id":"USD_INR_FX","name":"USD/INR","description":"Exchange rate"})
        count = await data.publish_outbox(RedisPublisher(transport,source_stream))
        await drain(source_consumer,count)
        author_token, author_digest = issue_token()
        reviewer_token, reviewer_digest = issue_token()
        outsider_token, outsider_digest = issue_token()
        await platform.provision_user("Verified professional",author_digest,True)
        await platform.provision_user("Independent reviewer",reviewer_digest)
        await platform.provision_user("Other researcher",outsider_digest)
        author_headers = {"Authorization":"Bearer "+author_token}
        reviewer_headers = {"Authorization":"Bearer "+reviewer_token}
        outsider_headers = {"Authorization":"Bearer "+outsider_token}
        source_config = DataSettings(_env_file=None,timescale_dsn=dsn,redis_url=redis_url,
                                    document_storage_root=str(tmp_path / "originals"),
                                    document_internal_api_key="isolated-upload-"+suffix,
                                    upstox_analytics_token="")
        async with AsyncExitStack() as stack:
            data_url = await stack.enter_async_context(serve_http(data_app(data,transport,source_config)))
            graph_url = await stack.enter_async_context(serve_http(graph_app(graph,broker,DataServiceClient(data_url))))
            config = config.model_copy(update={"data_service_url":data_url,"graph_service_url":graph_url})
            canonical = CanonicalClient(config)
            platform_url = await stack.enter_async_context(serve_http(platform_app(config,platform,canonical)))
            client = await stack.enter_async_context(httpx.AsyncClient(timeout=15))

            async def call(method,url,expected=200,**kwargs):
                response = await client.request(method,url,**kwargs)
                assert response.status_code == expected, f"{method} {urlsplit(url).path} returned {response.status_code}: {response.text[:500]}"
                return response.json() if response.content else None

            registration = await call("POST",graph_url+"/api/v1/stocks",202,json={"query":"RELIANCE"})
            assert await RegistrationWorker(data,FixtureCompanyProvider()).run_once()
            assert (await data.get_job(registration["job_id"]))["state"] == "graph_processing"
            count = await data.publish_outbox(RedisPublisher(transport,source_stream))
            await drain(source_consumer,count)
            context = await call("GET",graph_url+"/api/v1/stocks/RELIANCE/context",params={"window":"LAST_6M"})
            assert any(node["kind"] == "Commodity" for node in context["nodes"])
            assert context["processing_status"] == "completed"

            filing = await call("POST",data_url+"/api/v1/manual/news",202,json={
                "external_id":"fixture-reg30-"+suffix,"headline":"Reliance quarterly filing: refining demand improves",
                "summary":"Reliance reports improving refining demand and discusses rising crude input costs.",
                "source_url":"https://example.org/reg30/"+suffix,"source":"REG30",
                "published_at":datetime.now(UTC).isoformat(),"category":"REG30","tickers":["RELIANCE"],
                "sentiment":.4,"ticker_sentiment":{"RELIANCE":.4}})
            assert filing["state"] == "queued"
            count = await data.publish_outbox(RedisPublisher(transport,source_stream))
            await drain(source_consumer,count)
            context = await call("GET",graph_url+"/api/v1/stocks/RELIANCE/context",params={"window":"LAST_6M"})
            assert context["direct_news"] and context["direct_news"][0]["citation"]["url"].endswith(suffix)

            # Original text goes through HTTP intake, immutable source SQL and
            # the document outbox; no graph node is created directly by a test.
            original = "Reliance guidance: refining demand is expected to improve over the next quarter."
            document = await call("POST",data_url+"/api/v1/documents",202,
                headers={"X-Internal-Api-Key":"isolated-upload-"+suffix},json={
                    "ticker":"RELIANCE","title":"Quarterly guidance","source_url":"https://example.org/guidance",
                    "media_type":"text/plain","document_kind":"GUIDANCE",
                    "content_base64":base64.b64encode(original.encode()).decode(),"redistribution_permitted":True})
            await drain(evidence_consumer,1)
            doc_search = await call("GET",graph_url+"/api/v1/stocks/RELIANCE/documents/search",params={"q":"demand"})
            assert doc_search["items"] and doc_search["items"][0]["document_version_id"] == document["version_id"]
            download = await client.get(data_url+f"/api/v1/documents/{document['version_id']}/original")
            assert download.status_code == 200 and download.content.decode() == original

            now = datetime.now(UTC)
            content = {"ticker":"RELIANCE","title":"Demand outlook","body":"Refining demand should improve; crude costs remain a risk.",
                "direction":"BULLISH","horizon":"Next quarter","event_at":now.isoformat(),
                "expires_at":(now+timedelta(days=90)).isoformat(),"disclosures":"No position held",
                "evidence":[{"url":"https://example.org/guidance","title":"Quarterly guidance","locator":"Page 1",
                             "document_version_id":document["version_id"]}]}
            create_headers = {**author_headers,"Idempotency-Key":"contribution-1"}
            draft = await call("POST",platform_url+"/api/v1/contributions",201,headers=create_headers,json=content)
            retry = await call("POST",platform_url+"/api/v1/contributions",201,headers=create_headers,json=content)
            assert draft["id"] == retry["id"]
            contribution_url = platform_url+"/api/v1/contributions/"+draft["id"]
            await call("GET",contribution_url,404,headers=outsider_headers)
            submitted = await call("POST",contribution_url+"/submit",headers=author_headers,json={"expected_revision":draft["revision"]})
            await call("POST",contribution_url+"/review",403,headers=author_headers,
                json={"expected_revision":submitted["revision"],"decision":"APPROVE","reason":"Self review"})
            published = await call("POST",contribution_url+"/review",headers=reviewer_headers,
                json={"expected_revision":submitted["revision"],"decision":"APPROVE","reason":"Source checked"})
            assert await relay_once(platform,transport,config) == 1
            await drain(evidence_consumer,1)
            connections = await call("GET",platform_url+"/api/v1/stocks/RELIANCE/connections",headers=outsider_headers)
            assert len(connections["professional_evidence"]) == 1
            access = await call("GET",platform_url+"/api/v1/access-policy",headers=outsider_headers)
            assert access["features"]["professional_evidence"]["allowed"] and not access["quota_enforcement"]

            watchlist = await call("POST",platform_url+"/api/v1/watchlists",201,headers=author_headers,json={"name":"Research","tickers":["RELIANCE"]})
            assert watchlist["tickers"] == ["RELIANCE"]
            conversation = await call("POST",platform_url+"/api/v1/conversations",201,headers=author_headers,json={"title":"Demand research"})
            job = await call("POST",platform_url+f"/api/v1/conversations/{conversation['id']}/messages",202,
                headers={**author_headers,"Idempotency-Key":"chat-1"},json={"question":"What is the demand outlook?","tickers":["RELIANCE"]})
            await call("GET",platform_url+"/api/v1/agent-jobs/"+job["id"],404,headers=outsider_headers)
            machine = {"X-Agent-Key":config.agent_service_key.get_secret_value()}
            claimed = (await call("POST",platform_url+"/internal/v1/agent/jobs/claim",headers=machine))["job"]
            leased = {**machine,"X-Job-Lease":claimed["lease_token"]}
            offered = await call("GET",platform_url+f"/internal/v1/agent/jobs/{job['id']}/context/RELIANCE",headers=leased)
            assert any(item['kind'] == 'news' for item in offered['available_evidence'])
            assert any(item['kind'] == 'financial' for item in offered['available_evidence'])
            agent_documents = await call("GET",platform_url+f"/internal/v1/agent/jobs/{job['id']}/documents/RELIANCE",headers=leased,
                                         params={"q":"demand"})
            assert agent_documents['available_evidence'][0]['kind'] == 'document'
            evidence = next(item for item in offered["available_evidence"] if item["kind"] == "professional")
            reference = {"kind":"professional","id":evidence["id"],"locator":evidence["locator"],"quote":"Refining demand should improve"}
            result = {"answer":"Professional evidence expects improving demand, while noting crude-cost risk.",
                      "status":"supported","evidence":[reference],"reported_tokens":100,
                      "alerts":[{"ticker":"RELIANCE","event_id":evidence["id"],"material_version":evidence["material_version"],
                                 "direction":"BULLISH","summary":"Review improving demand alongside crude-cost risk.","evidence":[reference]}]}
            complete_url = platform_url+f"/internal/v1/agent/jobs/{job['id']}/complete"
            assert (await call("POST",complete_url,headers=leased,json=result))["state"] == "completed"
            assert (await call("POST",complete_url,headers=leased,json=result))["state"] == "completed"
            assert len((await call("GET",platform_url+"/api/v1/alerts",headers=author_headers))["items"]) == 1
            assert not (await call("GET",platform_url+"/api/v1/alerts",headers=outsider_headers))["items"]

            monitor = await call("POST",platform_url+"/api/v1/monitor-rules",201,headers=author_headers,
                                json={"watchlist_id":watchlist["id"],"question":"Track demand updates","interval_seconds":3600})
            assert await schedule_due_monitors(platform.pool,config) == 1
            monitoring = (await call("POST",platform_url+"/internal/v1/agent/jobs/claim",headers=machine))["job"]
            assert monitoring["kind"] == "monitor"
            monitor_lease = {**machine,"X-Job-Lease":monitoring["lease_token"]}
            await call("DELETE",platform_url+"/api/v1/monitor-rules/"+monitor["id"],204,headers=author_headers)
            await call("GET",platform_url+f"/internal/v1/agent/jobs/{monitoring['id']}/context/RELIANCE",409,headers=monitor_lease)
            await call("POST",platform_url+f"/internal/v1/agent/jobs/{monitoring['id']}/complete",409,headers=monitor_lease,json=result)
            assert (await call("GET",platform_url+"/api/v1/agent-jobs/"+monitoring["id"],headers=author_headers))["state"] == "cancelled"

            corrected = await call("POST",contribution_url+"/versions",201,headers=author_headers,
                                   json={**content,"direction":"BEARISH","body":"Crude-cost risk may outweigh demand improvement.","expected_revision":published["revision"]})
            submitted = await call("POST",contribution_url+"/submit",headers=author_headers,json={"expected_revision":corrected["revision"]})
            corrected = await call("POST",contribution_url+"/review",headers=reviewer_headers,
                json={"expected_revision":submitted["revision"],"decision":"APPROVE","reason":"Updated risk supported"})
            assert await relay_once(platform,transport,config) == 1
            await drain(evidence_consumer,1)
            current = await call("GET",graph_url+"/api/v1/stocks/RELIANCE/professional-evidence")
            assert len(current["items"]) == 1 and current["items"][0]["direction"] == "BEARISH"
            await call("POST",contribution_url+"/retract",headers=author_headers,
                       json={"expected_revision":corrected["revision"],"reason":"Source withdrawn"})
            assert await relay_once(platform,transport,config) == 1
            await drain(evidence_consumer,1)
            assert not (await call("GET",graph_url+"/api/v1/stocks/RELIANCE/professional-evidence"))["items"]
    finally:
        if canonical:
            await canonical.close()
        if platform:
            await platform.close()
        if data:
            await data.close()
        # Only this generated graph and generated schemas are removed.
        if graph_name.startswith("stockgraph_test_"):
            await asyncio.to_thread(graph._graph().delete)
        await admin.execute(f'DROP SCHEMA IF EXISTS "{data_schema}" CASCADE')
        await admin.execute(f'DROP SCHEMA IF EXISTS "{platform_schema}" CASCADE')
        await admin.close()
        # The empty-instance precondition makes this isolated-test cleanup safe.
        await transport.flushdb()
        await transport.aclose()
        broker.close()
