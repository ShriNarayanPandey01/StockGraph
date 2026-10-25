"""Only trusted service callers can supply developer and evidence-access context."""

import hmac

from fastapi.responses import JSONResponse


def install_internal_boundary(app, settings):
    @app.middleware("http")
    async def internal_boundary(request, call_next):
        if request.url.path in {"/health", "/ready", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}:
            return await call_next(request)
        key = settings.internal_service_key.get_secret_value()
        if not key:
            return JSONResponse({"detail": "Internal service authentication is not configured"}, status_code=503)
        supplied = request.headers.get("X-Internal-Service-Key", "")
        if not hmac.compare_digest(supplied.encode(), key.encode()):
            return JSONResponse({"detail": "Internal service credentials required"}, status_code=401)
        request.state.developer = request.headers.get("X-MarketGraph-Developer", "").lower() == "true"
        request.state.include_professional = request.headers.get("X-MarketGraph-Evidence-Scope", "ordinary") == "professional"
        return await call_next(request)
