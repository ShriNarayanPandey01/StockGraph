"""Authenticated free application API; publication safety is independent of plan access."""

from contextlib import asynccontextmanager
from importlib.util import find_spec
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from marketgraph_platform.auth import current_user
from marketgraph_platform.models import (
    ContributionInput,
    Principal,
    RetractionInput,
    ReviewInput,
    RevisionInput,
    VersionInput,
)
from marketgraph_platform.policy import access_policy
from marketgraph_platform.repository import PlatformError, Repository
from marketgraph_platform.settings import Settings


class CanonicalClient:
    def __init__(self, settings: Settings):
        self.client = httpx.AsyncClient(base_url=settings.data_service_url, timeout=settings.http_timeout_seconds)

    async def get(self, path: str, params: dict | None = None):
        try:
            result = await self.client.get(path, params=params)
            result.raise_for_status()
            return result.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Data Service unavailable") from None

    async def validate_ticker(self, ticker: str) -> str:
        # Registry lookup only: a public company-detail read may resolve an
        # unregistered provider symbol and is not canonical registration.
        data = await self.get("/api/v1/entities", {"kind": "Stock"})
        if any(entity.get("entity_id") == ticker for entity in data.get("entities", [])):
            return ticker
        raise HTTPException(422, "Ticker must exist in the canonical registry")

    async def validate_citations(self, content: ContributionInput):
        for reference in content.evidence:
            if reference.document_version_id is None:
                continue
            try:
                response = await self.client.get(f"/api/v1/documents/{reference.document_version_id}")
                if response.status_code == 404:
                    raise HTTPException(422, "Citation references an unknown document version")
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, "Document service unavailable") from None
            if document.get("ticker") != content.ticker:
                raise HTTPException(422, "Document citation must reference the same canonical stock")

    async def close(self):
        await self.client.aclose()


def create_app(settings: Settings | None = None, repository=None, canonical_client=None) -> FastAPI:
    settings = settings or Settings()
    owned_repo, owned_client = repository is None, canonical_client is None
    repository = repository or Repository(settings)
    canonical_client = canonical_client or CanonicalClient(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            if owned_repo:
                await repository.connect()
            yield
        finally:
            if owned_client:
                await canonical_client.close()
            if owned_repo:
                await repository.close()

    app = FastAPI(title="MarketGraph Platform", version="1.0.0", lifespan=lifespan)
    app.state.repository = repository
    app.state.canonical_client = canonical_client
    app.state.settings = settings

    @app.exception_handler(PlatformError)
    async def platform_error(request, exc: PlatformError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "marketgraph-platform", "phase": 1}

    @app.get("/ready")
    async def ready():
        try:
            if repository.pool is None or await repository.pool.fetchval("SELECT 1") != 1:
                raise RuntimeError("Database unavailable")
        except Exception:
            raise HTTPException(503,"Platform database is unavailable") from None
        return {"status":"ready"}

    @app.get("/api/v1/me")
    async def me(user: Principal = Depends(current_user)):
        return {"user": user, "access": access_policy()}

    @app.get("/api/v1/access-policy")
    async def policy(user: Principal = Depends(current_user)):
        return access_policy()

    @app.get("/api/v1/me/usage")
    async def usage(user: Principal = Depends(current_user)):
        return {"items": await repository.usage(user.id), "quota_enforcement": False}

    @app.post("/api/v1/contributions", status_code=201)
    async def create_contribution(body: ContributionInput,
                                  idempotency_key: str = Header(min_length=1, max_length=200),
                                  user: Principal = Depends(current_user)):
        await canonical_client.validate_ticker(body.ticker)
        await canonical_client.validate_citations(body)
        result = await repository.create_contribution(user, body, idempotency_key)
        await repository.measure(user.id, "contribution_drafts")
        return result

    @app.get("/api/v1/contributions")
    async def mine(user: Principal = Depends(current_user)):
        return {"items": await repository.list_mine(user)}

    @app.get("/api/v1/contributions/{contribution_id}")
    async def detail(contribution_id: UUID, user: Principal = Depends(current_user)):
        return await repository.detail(contribution_id, user)

    @app.post("/api/v1/contributions/{contribution_id}/versions", status_code=201)
    async def add_version(contribution_id: UUID, body: VersionInput, user: Principal = Depends(current_user)):
        await canonical_client.validate_ticker(body.ticker)
        await canonical_client.validate_citations(body)
        content = ContributionInput.model_validate(body.model_dump(exclude={"expected_revision"}))
        return await repository.add_version(contribution_id, user, content, body.expected_revision)

    @app.post("/api/v1/contributions/{contribution_id}/submit")
    async def submit(contribution_id: UUID, body: RevisionInput, user: Principal = Depends(current_user)):
        return await repository.submit(contribution_id, user, body.expected_revision)

    @app.get("/api/v1/review-queue")
    async def reviews(user: Principal = Depends(current_user)):
        return {"items": await repository.review_queue(user)}

    @app.post("/api/v1/contributions/{contribution_id}/review")
    async def review(contribution_id: UUID, body: ReviewInput, user: Principal = Depends(current_user)):
        return await repository.review(contribution_id, user, body.expected_revision, body.decision, body.reason)

    @app.post("/api/v1/contributions/{contribution_id}/retract")
    async def retract(contribution_id: UUID, body: RetractionInput, user: Principal = Depends(current_user)):
        return await repository.retract(contribution_id, user, body.expected_revision, body.reason)

    @app.get("/api/v1/stocks/{ticker}/professional-evidence")
    async def evidence(ticker: str, limit: int = Query(default=50, ge=1, le=100),
                       offset: int = Query(default=0, ge=0, le=10000), user: Principal = Depends(current_user)):
        await canonical_client.validate_ticker(ticker)
        items = await repository.published(ticker, limit + 1, offset)
        await repository.measure(user.id, "professional_evidence_reads")
        return {"items": items[:limit], "access": "FREE_PHASE_1", "ordinary_weight": settings.ordinary_weight,
                "weight_policy_version": "professional-priority-v1", "contradictions_retained": True,
                "pagination": {"limit": limit, "offset": offset, "next_offset": offset + limit if len(items) > limit else None}}

    for module, builder in (("agent_api", "build_agent_router"), ("connections_api", "build_connections_router")):
        if find_spec(f"marketgraph_platform.{module}"):
            from importlib import import_module
            app.include_router(getattr(import_module(f"marketgraph_platform.{module}"), builder)(current_user))
    return app
