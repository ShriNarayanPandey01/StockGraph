"""Graph API composition root. Source workers never run inside the API process."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

import httpx
import redis
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from stockgraph.adapters.api.data_client import DataServiceClient
from stockgraph.adapters.api.evidence_routes import build_evidence_router
from stockgraph.adapters.api.internal_auth import install_internal_boundary
from stockgraph.adapters.llm.providers import LiteLLMChatProvider
from stockgraph.adapters.messaging.consumer import renewable_lock
from stockgraph.adapters.repositories.falkor.repository import GraphRepository
from stockgraph.application.graph_queries.context import GraphContextService
from stockgraph.application.graph_queries.public_preview import PublicMarketGraphService
from stockgraph.application.processors.news_eligibility import (
    GraphNewsEligibilityReviewer,
    NewsEligibilityRequest,
    NewsEligibilityVerdict,
)
from stockgraph.domain.context import GraphContextResponse, PublicMarketGraphResponse
from stockgraph.domain.developer import (
    DeveloperEdgeCreate,
    DeveloperEdgeDeleteResponse,
    DeveloperEdgeResponse,
    DeveloperEdgeUpdate,
)
from stockgraph.domain.enums import Window
from stockgraph.domain.manual import ManualEntityInput, ManualEntityKind, ManualNewsInput
from stockgraph.runtime.settings import settings


class StockRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1, max_length=50, description="Company name, stock symbol or ISIN"
    )
    exchange: str = Field(default="NSE", pattern="^(NSE|BSE)$")
    strengths: list[str] = Field(default_factory=list)
    business_exclusions: list[str] = Field(default_factory=list)


class AgentCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickers: list[str] = Field(max_length=5000)
    as_of_ts: int = Field(ge=0)


def create_app(
    repo: Any | None = None,
    broker: Any | None = None,
    data_client: Any | None = None,
    eligibility_reviewer: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="StockGraph", version="0.2.0")
    install_internal_boundary(app, settings)
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
    app.include_router(build_evidence_router(app.state.repo))
    app.state.public_market_graph = PublicMarketGraphService(app.state.repo)
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

    @app.post("/internal/v1/agents/candidates")
    async def agent_candidates(body: AgentCandidateRequest) -> dict:
        import time
        now = int(time.time())
        if body.as_of_ts > now or body.as_of_ts < now - 300:
            raise HTTPException(422, "Candidate snapshot time must be recent")
        return await asyncio.to_thread(app.state.repo.agent_candidates, body.tickers, body.as_of_ts)

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

    @app.post("/api/v1/manual/stocks", status_code=202)
    async def register_manual_stock(body: StockRegistration) -> dict:
        """Explicit manual-registration alias; stock identity stays source-owned."""
        return await register_stock(body)

    @app.post("/api/v1/manual/entities/{kind}", status_code=202)
    async def submit_manual_entity(kind: ManualEntityKind, body: ManualEntityInput) -> dict:
        """Commit a canonical entity, then let the graph worker infer edges.

        Arbitrary node labels and caller-supplied edges are intentionally not
        accepted.  The Data Service commits a registry revision and outbox
        event; processing that event invokes ``DynamicOntologyBuilder`` for
        the affected stock contexts.
        """
        try:
            return await app.state.data.upsert_entity(kind, body.model_dump(exclude_none=True))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "Data service rejected manual entity") from exc
        except httpx.RequestError as exc:
            raise HTTPException(503, "Data service is unavailable") from exc

    @app.post("/api/v1/manual/news", status_code=202)
    async def submit_manual_news(body: ManualNewsInput) -> dict:
        """Stage manual news for the normal LLM-backed graph ingestion path."""
        try:
            return await app.state.data.submit_manual_news(body.model_dump(mode="json", exclude_none=True))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "Data service rejected manual news") from exc
        except httpx.RequestError as exc:
            raise HTTPException(503, "Data service is unavailable") from exc

    async def developer_write(callback, request: Request):
        """Run an explicit developer mutation under the graph-writer lease."""
        if not request.state.developer:
            raise HTTPException(403, "Developer permissions required")
        if not settings.developer_graph_mutations_enabled:
            raise HTTPException(403, "Developer graph editing is disabled by configuration")
        with renewable_lock(app.state.broker) as guard:
            if not guard:
                raise HTTPException(409, "Graph writer is busy; retry the mutation")
            if hasattr(app.state.repo, "set_write_guard"):
                app.state.repo.set_write_guard(guard)
            try:
                return await asyncio.to_thread(callback)
            finally:
                if hasattr(app.state.repo, "set_write_guard"):
                    app.state.repo.set_write_guard(None)

    @app.post(
        "/api/v1/developer/edges", status_code=201, response_model=DeveloperEdgeResponse
    )
    async def create_developer_edge(body: DeveloperEdgeCreate, request: Request) -> DeveloperEdgeResponse:
        """Create a manual FalkorDB edge between two existing graph nodes."""
        try:
            result = await developer_write(
                lambda: app.state.repo.create_developer_edge(
                    source_kind=body.source.kind,
                    source_id=body.source.id,
                    target_kind=body.target.kind,
                    target_id=body.target.id,
                    relation=body.relation,
                    rationale=body.rationale,
                    actor=body.actor,
                    confidence=body.confidence,
                    metadata=body.metadata,
                ), request
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return DeveloperEdgeResponse.model_validate(result)

    @app.delete(
        "/api/v1/developer/edges/{edge_id}", response_model=DeveloperEdgeDeleteResponse
    )
    async def delete_developer_edge(edge_id: str, request: Request) -> DeveloperEdgeDeleteResponse:
        """Delete a developer-created edge by ID; inferred and baseline edges are protected."""
        deleted = await developer_write(lambda: app.state.repo.delete_developer_edge(edge_id), request)
        if not deleted:
            raise HTTPException(404, "Developer edge not found")
        return DeveloperEdgeDeleteResponse(edge_id=edge_id, deleted=True)

    @app.get("/api/v1/developer/edges")
    async def list_developer_edges(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        if not request.state.developer:
            raise HTTPException(403, "Developer permissions required")
        items = await asyncio.to_thread(app.state.repo.list_developer_edges, limit, offset)
        return {"items": items, "limit": limit, "offset": offset}

    @app.put("/api/v1/developer/edges/{edge_id}")
    async def update_developer_edge(
        edge_id: str, body: DeveloperEdgeUpdate, request: Request
    ) -> dict:
        result = await developer_write(
            lambda: app.state.repo.update_developer_edge(
                edge_id,
                relation=body.relation,
                rationale=body.rationale,
                actor=body.actor,
                confidence=body.confidence,
                metadata=body.metadata,
            ),
            request,
        )
        if result is None:
            raise HTTPException(404, "Developer edge not found")
        return result

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
        hops: Annotated[int | None, Query(ge=1, le=3)] = None,
    ) -> GraphContextResponse:
        # Reject old date-range and unbounded contracts instead of silently ignoring them.
        if set(request.query_params) - {"window", "offset", "limit", "as_of_ts", "hops"}:
            raise HTTPException(422, "Only fixed windows, pagination and hops parameters are accepted")
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
                app.state.context.get_context, ticker, window, offset, limit, as_of_ts,
                include_professional=request.state.include_professional, hops=hops,
            )
        except KeyError as exc:
            raise HTTPException(
                404, "Stock is not yet projected; check its registration job"
            ) from exc

    @app.get("/api/v1/public/market-graph", response_model=PublicMarketGraphResponse)
    async def public_market_graph(request: Request) -> PublicMarketGraphResponse:
        """Return a small cached graph payload for public clients."""
        if request.query_params:
            raise HTTPException(422, "This public graph preview does not accept query parameters")
        cache_key = "stockgraph:public-market-graph:v1"
        try:
            cached = await asyncio.to_thread(app.state.broker.get, cache_key)
            if cached:
                if isinstance(cached, bytes):
                    cached = cached.decode()
                return PublicMarketGraphResponse.model_validate_json(cached)
        except Exception:
            pass
        preview = await asyncio.to_thread(app.state.public_market_graph.get_preview)
        try:
            await asyncio.to_thread(
                app.state.broker.set,
                cache_key,
                preview.model_dump_json(),
                ex=settings.public_graph_cache_ttl_seconds,
            )
        except Exception:
            pass
        return preview

    return app
