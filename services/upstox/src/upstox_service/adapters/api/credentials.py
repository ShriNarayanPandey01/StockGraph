"""Request-scoped provider credentials; no user token reaches jobs or shared state."""

import hmac
import re
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi.responses import JSONResponse
from pydantic import SecretStr

from upstox_service.adapters.providers.upstox.client import UpstoxClient
from upstox_service.adapters.providers.upstox.market import UpstoxMarketProvider
from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider


@dataclass(frozen=True)
class CredentialContext:
    scope: str
    stock_provider: UpstoxStockDataProvider
    market_provider: UpstoxMarketProvider


credential_context: ContextVar[CredentialContext | None] = ContextVar("upstox_credential", default=None)
_SCOPE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}:[1-9][0-9]{0,18}$")


class ScopedMarketProvider:
    def __init__(self, shared):
        self.__shared = shared

    def __getattr__(self, name):
        context = credential_context.get()
        return getattr(context.market_provider if context else self.__shared, name)


def install_internal_boundary(app, config):
    @app.middleware("http")
    async def internal_boundary(request, call_next):
        path = request.url.path
        if path in {"/health", "/ready", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}:
            return await call_next(request)
        key = config.internal_service_key.get_secret_value()
        if not key:
            return JSONResponse({"detail": "Internal service authentication is not configured"}, status_code=503)
        supplied = request.headers.get("X-Internal-Service-Key", "")
        if not hmac.compare_digest(supplied.encode(), key.encode()):
            return JSONResponse({"detail": "Internal service credentials required"}, status_code=401)
        token = request.headers.get("X-Upstox-Access-Token")
        if not token:
            return await call_next(request)
        scope = request.headers.get("X-MarketGraph-Credential-Scope", "")
        if not token.strip() or len(token) > 8192 or not _SCOPE.fullmatch(scope):
            return JSONResponse({"detail": "Invalid broker credential context"}, status_code=422)
        # A personal credential may be used only for existing read-only market routes.
        allowed = request.method == "GET" and (path.startswith("/api/v1/stocks/") or path.startswith("/api/v1/market/") or path.startswith("/api/v1/option-chains"))
        if not allowed:
            return JSONResponse({"detail": "Personal broker credentials are restricted to market data"}, status_code=403)
        v2 = UpstoxClient(SecretStr(token), base_url=config.upstox_api_base_url,
                         timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries,
                         redis_client=app.state.broker, requests_per_minute=config.upstox_requests_per_minute)
        v3 = UpstoxClient(SecretStr(token), base_url=config.upstox_api_v3_base_url,
                         timeout=config.upstox_timeout_seconds, max_retries=config.upstox_max_retries,
                         redis_client=app.state.broker, requests_per_minute=config.upstox_requests_per_minute)
        stock_provider = UpstoxStockDataProvider(v2, v3)
        context_token = credential_context.set(CredentialContext(scope, stock_provider, UpstoxMarketProvider(v2)))
        try:
            return await call_next(request)
        finally:
            credential_context.reset(context_token)
            await stock_provider.close()
            await v2.close()
            await v3.close()
