"""Graph API composition root. Source workers never run inside the API process."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

import httpx
import redis
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from stockgraph.adapters.api.data_client import DataServiceClient
from stockgraph.adapters.llm.providers import LiteLLMChatProvider
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.application.processors.news_eligibility import (
    GraphNewsEligibilityReviewer,
    NewsEligibilityRequest,
    NewsEligibilityVerdict,
)
from stockgraph.domain.context import GraphContextResponse
from stockgraph.domain.enums import Window
from stockgraph.runtime.settings import settings


class StockRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1, max_length=50, description="Company name, stock symbol or ISIN"
    )
    exchange: str = Field(default="NSE", pattern="^(NSE|BSE)$")
    strengths: list[str] = Field(default_factory=list)
    business_exclusions: list[str] = Field(default_factory=list)


def create_app(
    repo: Any | None = None,
    broker: Any | None = None,
    data_client: Any | None = None,
    eligibility_reviewer: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="StockGraph", version="0.2.0")
    app.state.repo = repo if repo is not None else GraphRepository()
    app.state.broker = (
        broker
        if broker is not None
        else redis.Redis.from_url(settings.redis_url, decode_responses=True)
    )
    app.state.data = (
        data_client if data_client is not None else DataServiceClient(settings.data_service_url)
    )
    app.state.context = GraphContextService(app.state.repo)
    app.state.eligibility_reviewer = eligibility_reviewer or GraphNewsEligibilityReviewer(
        LiteLLMChatProvider(app.state.broker)
    )

    @app.get("/health")
    async def health() -> dict:
        return {"service": "stockgraph", "status": "ok"}

    @app.get("/ready")
    async def ready() -> dict:
        try:
            await asyncio.to_thread(app.state.broker.ping)
            await asyncio.to_thread(app.state.repo._run, "RETURN 1", {})
        except Exception as exc:
            raise HTTPException(503, "Graph dependencies are unavailable") from exc
        return {"status": "ready"}

    @app.post("/internal/v1/news/eligibility", response_model=NewsEligibilityVerdict)
    async def review_news_eligibility(body: NewsEligibilityRequest) -> NewsEligibilityVerdict:
        """Internal-only, non-persisting ambiguity review for the Data Service."""
        return await asyncio.to_thread(app.state.eligibility_reviewer.review, body)

    @app.post("/api/v1/stocks", status_code=202)
    async def register_stock(body: StockRegistration) -> dict:
        try:
            return await app.state.data.register_stock(body.model_dump(exclude_none=True))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                exc.response.status_code, "Data service rejected stock registration"
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(503, "Data service is unavailable") from exc

    @app.get("/api/v1/jobs/{job_id}")
    async def job_status(job_id: UUID) -> dict:
        job = str(job_id)
        graph = await asyncio.to_thread(app.state.broker.hgetall, f"stockgraph:job:{job}")
        try:
            upstream = await app.state.data.job_status(job)
        except httpx.HTTPStatusError as exc:
            if not graph:
                raise HTTPException(exc.response.status_code, "Job not found") from exc
            upstream = {"job_id": job}
        except httpx.RequestError as exc:
            if not graph:
                raise HTTPException(503, "Job status is temporarily unavailable") from exc
            upstream = {"job_id": job}
        graph = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in graph.items()
        }
        return {
            **upstream,
            **graph,
            "job_id": job,
            "data_state": upstream.get("state"),
            "graph_state": graph.get("state", "pending"),
        }

    @app.get("/api/v1/stocks/{ticker}/context", response_model=GraphContextResponse)
    async def graph_context(
        ticker: str,
        request: Request,
        window: Window = Window.LAST_6M,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        as_of_ts: Annotated[int | None, Query(ge=0)] = None,
    ) -> GraphContextResponse:
        # Reject old date-range and unbounded contracts instead of silently ignoring them.
        if set(request.query_params) - {"window", "offset", "limit", "as_of_ts"}:
            raise HTTPException(422, "Only fixed windows and pagination parameters are accepted")
        import time

        if as_of_ts is not None and as_of_ts > int(time.time()):
            raise HTTPException(422, "as_of_ts cannot be in the future")
        if (
            as_of_ts is not None
            and as_of_ts < int(time.time()) - settings.pagination_snapshot_max_age_seconds
        ):
            raise HTTPException(422, "Pagination snapshot expired; restart at the first page")
        try:
            return await asyncio.to_thread(
                app.state.context.get_context, ticker, window, offset, limit, as_of_ts
            )
        except KeyError as exc:
            raise HTTPException(
                404, "Stock is not yet projected; check its registration job"
            ) from exc

    return app
