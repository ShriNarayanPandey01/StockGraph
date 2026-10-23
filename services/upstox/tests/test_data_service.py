from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from upstox_service.adapters.api.main import create_app
from upstox_service.adapters.messaging import RedisPublisher
from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient
from upstox_service.adapters.providers.upstox.company import UpstoxCompanyProvider
from upstox_service.adapters.repositories.timescale.catalog import merge_company_profile
from upstox_service.application.stock_registration import RegistrationWorker
from upstox_service.config.settings import Settings
from upstox_service.domain.models import CompanyBundle, StockRegistration, event
from upstox_service.domain.resolver import CanonicalEntityResolver
from upstox_service.runtime.scheduler import build_scheduler


def test_default_seed_is_packaged_with_data_service():
    resolver = CanonicalEntityResolver.from_seed()
    assert resolver.resolve_stock("Reliance") == "RELIANCE"
    assert resolver.resolve_registry("USD/INR").id == "USD_INR_FX"


def test_registration_api_returns_accepted_without_fetching():
    repo = AsyncMock()
    repo.create_job.return_value = {"job_id": str(uuid4()), "state": "pending"}
    app = create_app(repo, AsyncMock())
    with TestClient(app) as client:
        response = client.post("/api/v1/stocks", json={"query": "Reliance"})
    assert response.status_code == 202
    assert response.json()["state"] == "pending"
    repo.create_job.assert_awaited_once()
    repo.commit_company.assert_not_called()


def test_data_service_exposes_stock_and_market_read_routes():
    paths = create_app(AsyncMock(), AsyncMock()).openapi()["paths"]
    assert {
        "/api/v1/stocks/{ticker}",
        "/api/v1/stocks/{ticker}/shareholding",
        "/api/v1/stocks/{ticker}/candles",
        "/api/v1/option-chains",
        "/api/v1/market/institutional-flows",
        "/api/v1/market/pcr",
        "/api/v1/market/oi",
        "/api/v1/market/change-oi",
        "/api/v1/market/max-pain",
    } <= paths.keys()


def test_job_status_includes_graph_failures():
    job_id = str(uuid4())
    repo = AsyncMock()
    repo.get_job.return_value = {"job_id": job_id, "state": "graph_processing", "ticker": "TCS"}
    redis = AsyncMock()
    redis.hgetall.return_value = {"state": "failed", "error": "LLM disabled"}
    with TestClient(create_app(repo, redis)) as client:
        response = client.get("/api/v1/jobs/" + job_id)
    assert response.json()["state"] == "failed"
    assert response.json()["error"] == "LLM disabled"


def test_invalid_window_rejected_and_missing_stock_404():
    repo = AsyncMock()
    repo.get_entity.return_value = None
    with TestClient(create_app(repo, AsyncMock())) as client:
        assert client.get("/api/v1/stocks/TCS/financials?window=ALL").status_code == 422
        assert client.get("/api/v1/stocks/TCS/financials?window=LAST_1Y").status_code == 404


def test_entity_api_rejects_unresolved_stock_and_numeric_macros():
    with TestClient(create_app(AsyncMock(), AsyncMock())) as client:
        assert (
            client.post("/api/v1/entities/Stock", json={"id": "FAKE", "name": "Fake"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/entities/MacroFactor",
                json={"id": "INDIA_CPI", "name": "CPI", "value": 3.5},
            ).status_code
            == 422
        )


def test_manual_news_is_staged_then_enqueued_for_graph_inference():
    repo = AsyncMock()
    repo.get_entity.return_value = {"ticker": "TCS"}
    repo.commit_news.return_value = 1
    with TestClient(create_app(repo, AsyncMock())) as client:
        response = client.post(
            "/api/v1/manual/news",
            json={
                "headline": "Copper prices rise on supply disruption",
                "summary": "Industrial metals markets tightened.",
                "source_url": "https://example.test/copper-rise",
                "published_at": "2026-10-23T09:00:00+00:00",
                "category": "COMMODITY",
                "tickers": ["tcs"],
                "ticker_sentiment": {"TCS": 0.2},
            },
        )
    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    result = repo.commit_news.await_args.args[0]
    assert result.provider_id == "MANUAL"
    assert result.articles[0].tickers == ("TCS",)
    assert result.approvals[result.articles[0].external_id][0] == "RULES"


def test_manual_news_rejects_unknown_or_unpaired_ticker_sentiment():
    repo = AsyncMock()
    repo.get_entity.return_value = None
    with TestClient(create_app(repo, AsyncMock())) as client:
        response = client.post(
            "/api/v1/manual/news",
            json={
                "headline": "Copper prices rise",
                "source_url": "https://example.test/copper-rise",
                "published_at": "2026-10-23T09:00:00+00:00",
                "category": "COMMODITY",
                "tickers": ["UNKNOWN"],
            },
        )
    assert response.status_code == 422


def test_data_service_has_no_graph_or_llm_configuration():
    fields = Settings.model_fields
    assert not any("falkor" in name or "llm" in name for name in fields)
    config = Settings(_env_file=None, upstox_analytics_token="private-token")
    assert "private-token" not in repr(config)


def test_hourly_news_job_is_cron_minute_zero():
    scheduler = build_scheduler(Settings(_env_file=None))
    job = scheduler.get_job("hourly_news")
    assert str(job.trigger) == "cron[minute='0']"
    assert scheduler._job_defaults == {
        "misfire_grace_time": 300,
        "coalesce": True,
        "max_instances": 1,
    }
    assert {j.id for j in scheduler.get_jobs()} == {
        "hourly_news", "daily_equity_universe", "daily_open", "daily_close"
    }
    assert str(scheduler.get_job("daily_equity_universe").trigger) == "cron[hour='6', minute='0']"


def test_resolver_uses_sql_catalog_new_stocks():
    resolver = CanonicalEntityResolver.from_catalog(
        [
            {
                "kind": "Stock",
                "payload": {
                    "ticker": "NEWCO",
                    "isin": "INE123456789",
                    "name": "New Company",
                    "aliases": ["Newco Ltd"],
                },
            }
        ]
    )
    assert resolver.resolve_stock("NEWCO.NS") == "NEWCO"
    assert resolver.resolve_stock("Newco Ltd") == "NEWCO"
    assert resolver.resolve_stock("RANDOM") is None


@pytest.mark.asyncio
async def test_upstox_resolves_official_identity_and_fetches_profile():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer a-secret-token"
        if request.url.path.endswith("/instruments/search"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [
                        {
                            "trading_symbol": "TCS",
                            "name": "Tata Consultancy Services",
                            "isin": "INE467B01029",
                            "segment": "NSE_EQ",
                            "instrument_key": "NSE_EQ|INE467B01029",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/profile"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "company_profile": "Provides IT consulting services",
                        "sector": "IT",
                        "sector_market_cap_inr": {"value": 123},
                    },
                },
            )
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    client = UpstoxClient(SecretStr("a-secret-token"), transport=httpx.MockTransport(handler))
    try:
        bundle = await UpstoxCompanyProvider(client).fetch_company(
            StockRegistration(
                query="TCS", strengths=["consulting"], business_exclusions=["not a manufacturer"]
            )
        )
    finally:
        await client.close()
    assert bundle.entity["ticker"] == "TCS"
    assert bundle.entity["strengths"] == ["consulting"]
    assert "sector_market_cap_inr" not in bundle.entity
    assert bundle.raw["profile"]["data"]["sector_market_cap_inr"]["value"] == 123
    assert len(seen) == 6
    assert seen[0].url.params["segments"] == "EQ"


@pytest.mark.asyncio
async def test_auth_failures_are_not_retried_or_leaked():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"message": "token-private-123"})

    client = UpstoxClient(SecretStr("token-private-123"), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc:
            await client.get("/instruments/search")
    finally:
        await client.close()
    assert len(calls) == 1
    assert "token-private-123" not in str(exc.value)
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_ambiguous_instrument_requires_exact_symbol():
    client = AsyncMock()
    client.get.return_value = {
        "status": "success",
        "data": [
            {
                "trading_symbol": "ABC",
                "name": "ABC Company",
                "isin": "INE1",
                "instrument_key": "NSE_EQ|INE1",
                "segment": "NSE_EQ",
            },
            {
                "trading_symbol": "ABCD",
                "name": "ABCD Company",
                "isin": "INE2",
                "instrument_key": "NSE_EQ|INE2",
                "segment": "NSE_EQ",
            },
        ],
    }
    with pytest.raises(ProviderError, match="Ambiguous"):
        await UpstoxCompanyProvider(client).resolve("AB")


@pytest.mark.asyncio
async def test_worker_commits_only_after_provider_success():
    repo = AsyncMock()
    job_id = str(uuid4())
    repo.claim_job.return_value = {"job_id": job_id, "request": {"query": "TCS"}, "attempts": 1}
    provider = AsyncMock()
    bundle = CompanyBundle(entity={"ticker": "TCS"}, raw={})
    provider.fetch_company.return_value = bundle
    assert await RegistrationWorker(repo, provider).run_once()
    repo.commit_company.assert_awaited_once_with(job_id, bundle, attempt=1)
    repo.fail_job.assert_not_called()


@pytest.mark.asyncio
async def test_worker_auth_failure_marks_failed_without_graph_event():
    repo = AsyncMock()
    job_id = str(uuid4())
    repo.claim_job.return_value = {"job_id": job_id, "request": {"query": "TCS"}, "attempts": 1}
    provider = AsyncMock()
    provider.fetch_company.side_effect = ProviderError("Upstox authorization rejected")
    await RegistrationWorker(repo, provider).run_once()
    repo.commit_company.assert_not_called()
    repo.fail_job.assert_awaited_once_with(
        job_id, "Upstox authorization rejected", False, attempt=1
    )


@pytest.mark.asyncio
async def test_retryable_error_requeues_but_not_after_limit():
    repo = AsyncMock()
    job_id = str(uuid4())
    repo.claim_job.return_value = {"job_id": job_id, "request": {"query": "TCS"}, "attempts": 3}
    provider = AsyncMock()
    provider.fetch_company.side_effect = ProviderError("unavailable", retryable=True)
    await RegistrationWorker(repo, provider, max_attempts=3).run_once()
    repo.fail_job.assert_awaited_once_with(job_id, "unavailable", False, attempt=3)


@pytest.mark.asyncio
async def test_stream_contract_has_version_and_no_silent_trim():
    redis = AsyncMock()
    envelope = event("registry.updated", "TCS", 1, {"kind": "Stock", "entity": {"ticker": "TCS"}})
    await RedisPublisher(redis).publish(envelope)
    args, kwargs = redis.xadd.call_args
    assert args[0] == "stockgraph:events:v1"
    assert "event" in args[1]
    assert kwargs == {}
    assert envelope["schema_version"] == 1


def test_packaged_bootstrap_has_exactly_five_stocks():
    from importlib.resources import files

    import yaml

    data = yaml.safe_load(
        files("upstox_service.resources").joinpath("ontology_seed.yaml").read_text(encoding="utf-8")
    )
    assert {s["ticker"] for s in data["stocks"]} == {
        "TATASTEEL",
        "RELIANCE",
        "INFY",
        "TCS",
        "HDFCBANK",
    }
    assert len(data["macro_factors"]) == 7
    assert len(data["commodities"]) == 5
    assert all("macro_exposures" not in s for s in data["stocks"])


def test_company_refresh_preserves_curated_context_and_unions_aliases():
    old = {
        "ticker": "TCS",
        "name": "Old name",
        "business_summary": "Old summary",
        "sector": "IT",
        "exposures": ["BRENT_CRUDE"],
        "revenue_segments": ["Consulting"],
        "raw_material_inputs": ["Datacenter services"],
        "geographic_exposure": "Global",
        "strengths": ["Long client relationships"],
        "business_exclusions": ["No manufacturing"],
        "aliases": ["Tata Consultancy", "TCS"],
        "vendor_as_of": "old",
    }
    new = {
        "ticker": "TCS",
        "name": None,
        "business_summary": "Fresh source summary",
        "revenue_segments": [],
        "raw_material_inputs": [],
        "geographic_exposure": None,
        "strengths": [],
        "business_exclusions": [],
        "aliases": ["TCS", "New source alias"],
        "vendor_as_of": "new",
    }
    merged = merge_company_profile(old, new)
    for field in (
        "sector",
        "exposures",
        "revenue_segments",
        "raw_material_inputs",
        "geographic_exposure",
        "strengths",
        "business_exclusions",
    ):
        assert merged[field] == old[field]
    assert merged["name"] == "Old name"
    assert merged["business_summary"] == "Fresh source summary"
    assert merged["vendor_as_of"] == "new"
    assert merged["aliases"] == ["Tata Consultancy", "TCS", "New source alias"]
    assert merge_company_profile(old, {"strengths": ["Updated operator annotation"]})[
        "strengths"
    ] == ["Updated operator annotation"]
    merged["strengths"].append("Mutation should not escape")
    assert old["strengths"] == ["Long client relationships"]
