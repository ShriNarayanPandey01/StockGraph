"""Bounded evidence reads for external agents and the connections explorer."""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
from stockgraph.application.professional import professional_context
from stockgraph.domain.enums import Window
from stockgraph.domain.schemas import resolve_window
from stockgraph.runtime.settings import settings


def build_evidence_router(repo):
    router = APIRouter(prefix="/api/v1/stocks/{ticker}", tags=["Evidence"])

    def stock(ticker):
        if not repo.get_entity("Stock", ticker.upper()):
            raise HTTPException(404, "Unknown registered stock")

    @router.get("/professional-evidence")
    def professional(ticker: str, request: Request, window: Window = Window.LAST_6M,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=10000),
                     as_of_ts: int | None = None):
        if not request.state.include_professional:
            raise HTTPException(403, "Professional evidence access required")
        stock(ticker)
        now = int(time.time())
        if as_of_ts is not None and not now - settings.pagination_snapshot_max_age_seconds <= as_of_ts <= now:
            raise HTTPException(422, "Pagination snapshot expired or is in the future")
        start, end = resolve_window(window, datetime.fromtimestamp(as_of_ts, UTC) if as_of_ts else None)
        return professional_context(repo, ticker.upper(), start, end, offset, limit,
                                    getattr(settings, "professional_evidence_weight", 1.5))

    @router.get("/documents/search")
    def documents(ticker: str, q: str = Query("", max_length=200),
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000)):
        stock(ticker)
        rows = EvidenceRepository(repo).document_page(ticker.upper(), q, offset, limit)
        return {"ticker": ticker.upper(), "items": rows[:limit],
                "pagination": {"offset": offset, "limit": limit, "has_more": len(rows) > limit,
                               "next_offset": offset + limit if len(rows) > limit else None}}

    return router
