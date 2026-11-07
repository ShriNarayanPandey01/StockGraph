"""Authenticated Platform boundary for accounts, permissions and market intelligence."""

from contextlib import asynccontextmanager
from importlib.util import find_spec
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from marketgraph_platform.accounts import Accounts
from marketgraph_platform.application.contributions import (
    AccountAdministrationService,
    ContributionService,
)
from marketgraph_platform.application.ports import GraphClientPort
from marketgraph_platform.application.research import AgentContextService, ResearchSubmissionService
from marketgraph_platform.auth import current_user
from marketgraph_platform.brokers import BrokerConnections, build_broker_router
from marketgraph_platform.entitlements import Entitlements
from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import (
    ContributionInput,
    Principal,
    RetractionInput,
    ReviewInput,
    RevisionInput,
    VersionInput,
)
from marketgraph_platform.policy import access_policy
from marketgraph_platform.repository import Repository
from marketgraph_platform.settings import Settings


class HttpDataClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=settings.data_service_url,
            timeout=settings.http_timeout_seconds,
            headers={"X-Internal-Service-Key": settings.internal_service_key.get_secret_value()},
            transport=transport,
        )

    async def get(self, path: str, params: dict | None = None, *, headers=None):
        try:
            result = await self._client.get(path, params=params, headers=headers)
            if result.status_code in (400, 401, 403, 404, 409, 422):
                message = "Data request rejected"
                if result.status_code == 401 and "broker_reconnect_required" in result.text:
                    message = "broker_reconnect_required"
                raise PlatformError(result.status_code, message)
            result.raise_for_status()
            return result.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Data Service unavailable") from None

    async def post_internal(self, path, payload, *, headers=None):
        try:
            result = await self._client.post(path, json=payload, headers=headers)
            if result.status_code in (400, 401, 403, 404, 409, 422):
                raise PlatformError(result.status_code, "Data Service rejected the operation")
            result.raise_for_status()
            return result.json()
        except (httpx.HTTPError, ValueError):
            raise PlatformError(503, "Data Service temporarily unavailable") from None

    async def patch_internal(self, path, payload, *, headers=None):
        try:
            result = await self._client.patch(path, json=payload, headers=headers)
            if result.status_code in (400, 401, 403, 404, 409, 422):
                raise PlatformError(result.status_code, "Data Service rejected the operation")
            result.raise_for_status()
            return result.json()
        except (httpx.HTTPError, ValueError):
            raise PlatformError(503, "Data Service temporarily unavailable") from None

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
                response = await self._client.get(f"/api/v1/documents/{reference.document_version_id}")
                if response.status_code == 404:
                    raise HTTPException(422, "Citation references an unknown document version")
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, "Document service unavailable") from None
            if document.get("ticker") != content.ticker:
                raise HTTPException(422, "Document citation must reference the same canonical stock")

    async def close(self):
        await self._client.aclose()


CanonicalClient = HttpDataClient


class HttpGraphClient:
    """Reusable HTTP adapter for StockGraph's trusted service boundary."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.graph_service_url,
            timeout=settings.http_timeout_seconds,
            transport=transport,
        )

    async def get(self, path, params=None, *, professional=False, developer=False):
        return await self.request(
            "GET", path, params=params, professional=professional, developer=developer
        )

    async def request(self, method, path, *, body=None, params=None,
                      professional=False, developer=False):
        headers = {
            "X-Internal-Service-Key": self._settings.internal_service_key.get_secret_value(),
            "X-MarketGraph-Evidence-Scope": "professional" if professional else "ordinary",
            "X-MarketGraph-Developer": "true" if developer else "false",
        }
        try:
            result = await self._client.request(
                method, path, json=body, params=params, headers=headers
            )
            if result.status_code in (400, 401, 403, 404, 409, 422):
                detail = "Graph service rejected the request"
                if result.status_code == 404:
                    detail = "Requested graph evidence is not projected"
                elif result.status_code == 422:
                    detail = "Invalid or expired graph pagination; restart from the first page"
                raise PlatformError(result.status_code, detail)
            result.raise_for_status()
            return result.json()
        except PlatformError:
            raise
        except (httpx.HTTPError, ValueError):
            raise PlatformError(503, "Graph service is unavailable; retry the request") from None

    async def close(self):
        await self._client.aclose()


def create_app(settings: Settings | None = None, repository=None, canonical_client=None,
               graph_client: GraphClientPort | None = None) -> FastAPI:
    settings = settings or Settings()
    owned_repo, owned_client, owned_graph_client = (
        repository is None, canonical_client is None, graph_client is None
    )
    repository = repository or Repository(settings)
    canonical_client = canonical_client or HttpDataClient(settings)
    graph_client = graph_client or HttpGraphClient(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            if owned_repo:
                await repository.connect()
                await app.state.account_administration.bootstrap_developer()
            yield
        finally:
            if owned_client:
                await canonical_client.close()
            if owned_graph_client:
                await graph_client.close()
            if owned_repo:
                await repository.close()

    app = FastAPI(title="MarketGraph Platform", version="2.0.0", lifespan=lifespan)
    app.state.repository = repository
    app.state.canonical_client = canonical_client
    app.state.data_client = canonical_client
    app.state.graph_client = graph_client
    app.state.settings = settings
    app.state.accounts = Accounts(repository, settings=settings)
    app.state.account_administration = AccountAdministrationService(app.state.accounts)
    app.state.entitlements = Entitlements(repository)
    app.state.brokers = BrokerConnections(repository, settings, canonical_client)
    app.state.contributions = ContributionService(repository, canonical_client)
    app.state.research_submission = ResearchSubmissionService(
        app.state.entitlements, canonical_client, repository, settings, repository
    )
    app.state.agent_context = AgentContextService(
        repository, repository, canonical_client, graph_client
    )
    from marketgraph_platform.account_api import build_account_router
    from marketgraph_platform.admin_api import build_admin_router
    from marketgraph_platform.policy_api import build_policy_router
    app.include_router(build_account_router(current_user))
    app.include_router(build_admin_router(current_user))
    app.include_router(build_policy_router(current_user))
    app.include_router(build_broker_router(current_user))

    @app.exception_handler(PlatformError)
    async def platform_error(request, exc: PlatformError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "type": error["type"], "msg": "Invalid request field"}
            for error in exc.errors()
        ]})

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "marketgraph-platform", "phase": 2}

    @app.get("/ready")
    async def ready():
        try:
            if not await repository.health_check():
                raise RuntimeError("Database unavailable")
        except Exception:
            raise HTTPException(503, "Platform database is unavailable") from None
        return {"status": "ready"}

    @app.get("/api/v1/me")
    async def me(user: Principal = Depends(current_user)):
        access = await app.state.entitlements.access(user.id)
        return {"user": user, "access": access_policy(access.user, access.policy)}

    @app.get("/api/v1/access-policy")
    async def policy(user: Principal = Depends(current_user)):
        access = await app.state.entitlements.access(user.id)
        return access_policy(access.user, access.policy)

    @app.get("/api/v1/me/usage")
    async def usage(user: Principal = Depends(current_user)):
        return await app.state.entitlements.usage(user)

    @app.post("/api/v1/contributions", status_code=201)
    async def create_contribution(body: ContributionInput,
                                  idempotency_key: str = Header(min_length=1, max_length=200),
                                  user: Principal = Depends(current_user)):
        return await app.state.contributions.create(user, body, idempotency_key)

    @app.get("/api/v1/contributions")
    async def mine(user: Principal = Depends(current_user)):
        return {"items": await repository.list_mine(user)}

    @app.get("/api/v1/contributions/{contribution_id}")
    async def detail(contribution_id: UUID, user: Principal = Depends(current_user)):
        return await repository.detail(contribution_id, user)

    @app.post("/api/v1/contributions/{contribution_id}/versions", status_code=201)
    async def add_version(contribution_id: UUID, body: VersionInput, user: Principal = Depends(current_user)):
        return await app.state.contributions.add_version(contribution_id, user, body)

    @app.post("/api/v1/contributions/{contribution_id}/submit")
    async def submit(contribution_id: UUID, body: RevisionInput, user: Principal = Depends(current_user)):
        return await app.state.contributions.submit(contribution_id, user, body.expected_revision)

    @app.get("/api/v1/review-queue")
    async def reviews(user: Principal = Depends(current_user)):
        from marketgraph_platform.policy import require_permission
        require_permission(user, "review")
        return {"items": await repository.review_queue(user)}

    @app.post("/api/v1/contributions/{contribution_id}/review")
    async def review(contribution_id: UUID, body: ReviewInput, user: Principal = Depends(current_user)):
        return await app.state.contributions.review(
            contribution_id, user, body.expected_revision, body.decision, body.reason
        )

    @app.post("/api/v1/contributions/{contribution_id}/retract")
    async def retract(contribution_id: UUID, body: RetractionInput, user: Principal = Depends(current_user)):
        return await app.state.contributions.retract(
            contribution_id, user, body.expected_revision, body.reason
        )

    @app.get("/api/v1/stocks/{ticker}/professional-evidence")
    async def evidence(ticker: str, limit: int = Query(default=50, ge=1, le=100),
                       offset: int = Query(default=0, ge=0, le=10000), user: Principal = Depends(current_user)):
        await app.state.entitlements.check(user, "professional_evidence", [ticker.strip().upper()])
        await canonical_client.validate_ticker(ticker)
        items = await repository.published(ticker, limit + 1, offset)
        await repository.measure(user.id, "professional_evidence_reads")
        return {"items": items[:limit], "access": "PRO", "ordinary_weight": settings.ordinary_weight,
                "weight_policy_version": "professional-priority-v1", "contradictions_retained": True,
                "pagination": {"limit": limit, "offset": offset, "next_offset": offset + limit if len(items) > limit else None}}

    for module, builder in (("agent_api", "build_agent_router"), ("connections_api", "build_connections_router")):
        if find_spec(f"marketgraph_platform.{module}"):
            from importlib import import_module
            app.include_router(getattr(import_module(f"marketgraph_platform.{module}"), builder)(current_user))
    return app
