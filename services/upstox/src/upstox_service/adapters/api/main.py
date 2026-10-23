"""Independent REST API for registration and SQL-only financial reads."""

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis

from upstox_service.adapters.api.market_routes import create_market_router
from upstox_service.adapters.api.stock_routes import create_stock_router
from upstox_service.adapters.providers.upstox.client import UpstoxClient
from upstox_service.adapters.providers.upstox.market import UpstoxMarketProvider
from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider
from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.adapters.repositories.timescale.stock_data import init_stock_data_schema
from upstox_service.config.settings import Settings
from upstox_service.domain.enums import Window
from upstox_service.domain.models import EntityInput, EntityKind, StockRegistration


def create_app(repository=None, redis_client=None, config: Settings | None = None) -> FastAPI:
    config = config or Settings()
    owned_repository = repository is None
    owned_redis = redis_client is None
    repository = repository or DataRepository(config.timescale_dsn)
    redis_client = redis_client or Redis.from_url(config.redis_url, decode_responses=True)
    v2_client = UpstoxClient(config.upstox_analytics_token, base_url=config.upstox_api_base_url,
                             timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries)
    v3_client = UpstoxClient(config.upstox_analytics_token, base_url=config.upstox_api_v3_base_url,
                             timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries)
    stock_provider = UpstoxStockDataProvider(v2_client, v3_client)

    @asynccontextmanager
    async def lifespan(app):
        try:
            if owned_repository:
                await repository.init_schema()
                await init_stock_data_schema(repository)
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
    app.include_router(create_stock_router(repository, stock_provider, redis_client, config))
    app.include_router(create_market_router(
        UpstoxMarketProvider(v2_client), redis_client,
        live_ttl_seconds=config.market_live_cache_ttl_seconds,
        dated_ttl_seconds=config.market_dated_cache_ttl_seconds,
    ))

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "upstox-data"}

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

    @app.get("/api/v1/stocks/{ticker}/financials")
    async def financials(ticker: str, window: Window):
        ticker = ticker.strip().upper()
        if await repository.get_entity("Stock", ticker) is None:
            raise HTTPException(404, "Stock is not registered")
        return await repository.get_financials(ticker, window)

    return app
