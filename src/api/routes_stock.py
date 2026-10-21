"""Stock dossier REST routes (Milestone 3)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.domain.enums import Window
from src.domain.schemas import StockDossierResponse
from src.services.stock_context_service import UnknownTickerError

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])


def _service(request: Request):
    svc = getattr(request.app.state, "stock_context_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Stock context service not configured")
    return svc


@router.get("/{ticker}/dossier", response_model=StockDossierResponse)
async def get_dossier(
    ticker: str,
    request: Request,
    window: Window = Query(default=Window.LAST_6M),
) -> StockDossierResponse:
    try:
        return await _service(request).get_stock_dossier(ticker, window)
    except UnknownTickerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
