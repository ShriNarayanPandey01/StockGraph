"""Independent REST API for registration and SQL-only financial reads."""

from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis.asyncio import Redis

from upstox_service.adapters.api.credentials import ScopedMarketProvider, install_internal_boundary
from upstox_service.adapters.api.document_routes import build_document_router
from upstox_service.adapters.api.market_routes import create_market_router
from upstox_service.adapters.api.stock_routes import create_stock_router
from upstox_service.adapters.providers.news.adapters import (
    ProviderFetchResult,
    ProviderStatus,
    StagedNewsItem,
)
from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient
from upstox_service.adapters.providers.upstox.market import UpstoxMarketProvider
from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider
from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.adapters.repositories.timescale.documents import DocumentRepository
from upstox_service.adapters.repositories.timescale.stock_data import init_stock_data_schema
from upstox_service.application.ingestion.news_eligibility import NewsEligibilityGate
from upstox_service.config.settings import Settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import Window
from upstox_service.domain.models import (
    AdminCatalogUpdate,
    EntityInput,
    EntityKind,
    ManualNewsInput,
    StockRegistration,
)


def create_app(repository=None, redis_client=None, config: Settings | None = None) -> FastAPI:
    config = config or Settings()
    owned_repository = repository is None
    owned_redis = redis_client is None
    repository = repository or DataRepository(config.timescale_dsn)
    redis_client = redis_client or Redis.from_url(config.redis_url, decode_responses=True)
    v2_client = UpstoxClient(config.upstox_analytics_token, base_url=config.upstox_api_base_url,
                             timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries,
                             redis_client=redis_client, requests_per_minute=config.upstox_requests_per_minute)
    v3_client = UpstoxClient(config.upstox_analytics_token, base_url=config.upstox_api_v3_base_url,
                             timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries,
                             redis_client=redis_client, requests_per_minute=config.upstox_requests_per_minute)
    stock_provider = UpstoxStockDataProvider(v2_client, v3_client)

    @asynccontextmanager
    async def lifespan(app):
        try:
            if owned_repository:
                await repository.init_schema()
                await init_stock_data_schema(repository)
                await DocumentRepository(repository).init_schema()
                await repository.bootstrap()
            yield
        finally:
            await stock_provider.close()
            await v2_client.close()
            await v3_client.close()
            if owned_repository:
                await repository.close()
            if owned_redis:
                await redis_client.aclose()

    app = FastAPI(title="Upstox / Market Data Service", version="1.0.0", lifespan=lifespan)
    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, exc):
        # Validation failures must never reflect a submitted broker token.
        return JSONResponse(status_code=422, content={"detail": [
            {key: item[key] for key in ("loc", "msg", "type") if key in item}
            for item in exc.errors()
        ]})

    app.state.broker = redis_client
    install_internal_boundary(app, config)
    app.include_router(create_stock_router(repository, stock_provider, redis_client, config))
    app.include_router(build_document_router(repository, redis_client, config))
    app.include_router(create_market_router(
        ScopedMarketProvider(UpstoxMarketProvider(v2_client)), redis_client,
        live_ttl_seconds=config.market_live_cache_ttl_seconds,
        dated_ttl_seconds=config.market_dated_cache_ttl_seconds,
    ))

    class CredentialInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        access_token: SecretStr = Field(min_length=1, max_length=8192)

    @app.post("/internal/v1/upstox/validate-credential")
    async def validate_credential(body: CredentialInput):
        # A market quote is authenticated and contains no private account data.
        client = UpstoxClient(body.access_token, base_url=config.upstox_api_base_url,
                              timeout=config.upstox_timeout_seconds, max_retries=0,
                              redis_client=redis_client, requests_per_minute=config.upstox_requests_per_minute)
        try:
            await client.get("/market-quote/quotes", {"instrument_key": "NSE_INDEX|Nifty 50"})
        except ProviderError as exc:
            if exc.status_code in (401, 403):
                raise HTTPException(401, "broker_reconnect_required: Upstox credential rejected") from None
            raise HTTPException(503, "Upstox credential validation is temporarily unavailable") from None
        finally:
            await client.close()
        return {"status": "connected", "market_data_validated": True, "trading_enabled": False}

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "upstox-data"}

    @app.get("/ready")
    async def ready():
        try:
            pool = getattr(repository, "_pool", None)
            if pool is None or await pool.fetchval("SELECT 1") != 1:
                raise RuntimeError("TimescaleDB is unavailable")
            await redis_client.ping()
        except Exception:
            raise HTTPException(503, "Data service dependencies are unavailable") from None
        return {"status": "ready"}

    @app.post("/api/v1/stocks", status_code=202)
    async def register(request: StockRegistration):
        return await repository.create_job(request)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: UUID):
        job = await repository.get_job(str(job_id))
        if job is None:
            raise HTTPException(404, "Unknown registration job")
        if job["state"] == "graph_processing":
            try:
                graph = await redis_client.hgetall(f"stockgraph:job:{job_id}")
            except Exception:
                graph = {}
            if graph:
                job["graph"] = graph
                job["state"] = graph.get("state", job["state"])
                if graph.get("error"):
                    job["error"] = graph["error"]
        return job

    @app.get("/api/v1/entities")
    async def catalog(kind: EntityKind | None = None):
        return {"entities": await repository.list_catalog(kind.value if kind else None)}

    @app.post("/api/v1/entities/{kind}", status_code=202)
    async def upsert(kind: EntityKind, request: EntityInput):
        if kind == EntityKind.STOCK:
            raise HTTPException(422, "Use POST /api/v1/stocks to resolve official stock identity")
        return await repository.upsert_entity(kind, request.model_dump(exclude_none=True))

    @app.patch("/api/v1/admin/entities/{kind}/{entity_id}", status_code=202)
    async def update_catalog_entity(kind: EntityKind, entity_id: str, request: AdminCatalogUpdate):
        try:
            return await repository.update_catalog_entity(kind, entity_id, request.changes)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/manual/news", status_code=202)
    async def submit_manual_news(request: ManualNewsInput):
        """Stage a human-supplied article and enqueue normal graph processing.

        This is deliberately source-owned: the raw payload, normalized news
        record, eligibility decision, and outbox event commit in one SQL
        transaction.  The Graph service never receives a direct graph-write
        escape hatch.
        """
        mentioned_tickers = list(dict.fromkeys([*request.tickers, *request.ticker_sentiment]))
        unknown = [
            ticker
            for ticker in mentioned_tickers
            if await repository.get_entity(EntityKind.STOCK.value, ticker) is None
        ]
        if unknown:
            raise HTTPException(422, f"Unknown registered ticker(s): {', '.join(unknown)}")
        if set(request.ticker_sentiment) - set(request.tickers):
            raise HTTPException(422, "ticker_sentiment keys must also be present in tickers")

        published_at = request.published_at
        external_id = request.external_id or "manual-" + sha256(
            request.source_url.encode("utf-8")
        ).hexdigest()[:40]
        article = NewsArticle(
            external_id=external_id,
            headline=request.headline,
            summary=request.summary,
            source_url=request.source_url,
            source=request.source,
            published_at=published_at,
            category=request.category,
            sentiment=request.sentiment,
            tickers=tuple(request.tickers),
            ticker_sentiment=request.ticker_sentiment,
        )
        decision = await NewsEligibilityGate().decide(article)
        if not decision.approved or decision.category is None:
            raise HTTPException(422, f"Manual news rejected: {decision.reason}")
        approved_article = replace(article, category=decision.category)
        raw_payload = request.model_dump(mode="json", exclude_none=True)
        raw_payload["external_id"] = external_id
        result = ProviderFetchResult(
            provider_id="MANUAL",
            status=ProviderStatus.AVAILABLE,
            articles=(approved_article,),
            staged=(
                StagedNewsItem(
                    external_id=external_id,
                    published_at=published_at,
                    source_url=request.source_url,
                    payload=raw_payload,
                ),
            ),
            approvals={external_id: (decision.source, decision.reason)},
        )
        changed = await repository.commit_news(result)
        return {
            "external_id": external_id,
            "state": "queued" if changed else "unchanged",
            "eligibility": {"source": decision.source, "reason": decision.reason},
        }

    @app.get("/api/v1/stocks/{ticker}/financials")
    async def financials(ticker: str, window: Window):
        ticker = ticker.strip().upper()
        if await repository.get_entity("Stock", ticker) is None:
            raise HTTPException(404, "Stock is not registered")
        return await repository.get_financials(ticker, window)

    return app
