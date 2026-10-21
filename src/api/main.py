"""FastAPI application factory (Milestone 3)."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from src.api.routes_stock import router as stock_router
from src.processors.entity_resolver import CanonicalEntityResolver
from src.services.stock_context_service import StockContextService


def create_app(falkor_repo: Any | None = None, timescale_repo: Any | None = None) -> FastAPI:
    app = FastAPI(title="StockGraph Context Service", version="0.1.0")

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # The optional parameters keep tests and embedded deployments injectable,
    # while the module-level ASGI app must be useful when launched directly.
    if falkor_repo is None and timescale_repo is None:
        from src.repositories.falkor_repo import FalkorGraphRAGRepository
        from src.repositories.timescale_repo import TimescaleRepository

        falkor_repo = FalkorGraphRAGRepository()
        timescale_repo = TimescaleRepository()

    if falkor_repo is not None and timescale_repo is not None:
        app.state.stock_context_service = StockContextService(
            falkor_repo, timescale_repo,
            resolver=CanonicalEntityResolver.from_seed())
    app.include_router(stock_router)
    return app


app = create_app()
