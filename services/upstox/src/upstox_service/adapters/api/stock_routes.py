"""Public SQL-backed equity reads. Registration remains a separate POST."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from upstox_service.adapters.providers.upstox.client import ProviderError
from upstox_service.application.stock_data import (
    InvalidCursor,
    StockDataService,
    StockNotFound,
)

Exchange = Literal["NSE", "BSE"]


class StockSummary(BaseModel):
    exchange: Exchange
    instrument_key: str
    trading_symbol: str
    isin: str
    name: str
    short_name: str | None = None
    source_as_of: datetime
    registered: bool


class StockListResponse(BaseModel):
    items: list[StockSummary]
    next_cursor: str | None = None


class CompanyProfile(BaseModel):
    business_summary: str
    sector: str | None = None
    sector_market_cap_inr: dict | None = None
    sector_market_cap_usd: dict | None = None


class StockDetail(StockSummary):
    profile: CompanyProfile
    vendor_id: str
    vendor_as_of: datetime


class HoldingPeriod(BaseModel):
    period: str
    promoters: float | None = None
    fii: float | None = None
    dii: float | None = None
    public: float | None = None
    breakdown: dict[str, float] = Field(default_factory=dict)


class ShareholdingResponse(BaseModel):
    exchange: Exchange
    ticker: str
    isin: str
    vendor_id: str
    vendor_as_of: datetime
    periods: list[HoldingPeriod]


class DailyCandle(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    vendor_id: str
    vendor_as_of: datetime


class CandleResponse(BaseModel):
    exchange: Exchange
    ticker: str
    isin: str
    from_date: date
    to_date: date
    vendor_id: str
    candles: list[DailyCandle]


def _raise_public_error(exc: Exception) -> None:
    if isinstance(exc, StockNotFound):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, InvalidCursor):
        raise HTTPException(422, str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(422, str(exc)) from exc
    if isinstance(exc, ProviderError):
        status = getattr(exc, "status_code", None)
        if status == 404:
            raise HTTPException(404, "Upstox has no data for this instrument") from exc
        if status in (401, 403):
            raise HTTPException(502, "Upstox authorization or entitlement unavailable") from exc
        if exc.retryable:
            raise HTTPException(503, "Upstox is temporarily unavailable") from exc
        raise HTTPException(502, str(exc)) from exc
    raise exc


def create_stock_router(repository, provider, redis_client=None, config=None) -> APIRouter:
    """The caller owns the provider and repository lifetimes."""
    _ = (redis_client, config)
    service = StockDataService(repository, provider)
    router = APIRouter(prefix="/api/v1", tags=["Stocks / Market Data"])

    @router.get("/stocks", response_model=StockListResponse)
    async def list_stocks(
        query: str = Query(default="", max_length=80),
        exchange: Exchange | None = None,
        cursor: str | None = Query(default=None, max_length=1024),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        try:
            return await service.list_stocks(query, exchange, cursor, limit)
        except (InvalidCursor, ValueError, ProviderError) as exc:
            _raise_public_error(exc)

    @router.get("/stocks/{ticker}", response_model=StockDetail)
    async def get_stock(ticker: str, exchange: Exchange = "NSE"):
        try:
            return await service.stock(ticker.strip().upper(), exchange)
        except (StockNotFound, ValueError, ProviderError) as exc:
            _raise_public_error(exc)

    @router.get("/stocks/{ticker}/shareholding", response_model=ShareholdingResponse)
    async def shareholding(ticker: str, exchange: Exchange = "NSE"):
        try:
            return await service.shareholding(ticker.strip().upper(), exchange)
        except (StockNotFound, ValueError, ProviderError) as exc:
            _raise_public_error(exc)

    @router.get("/stocks/{ticker}/candles", response_model=CandleResponse)
    async def candles(
        ticker: str,
        exchange: Exchange = "NSE",
        from_date: date | None = Query(default=None, alias="from"),
        to_date: date | None = Query(default=None, alias="to"),
    ):
        try:
            return await service.candles(ticker.strip().upper(), exchange, from_date, to_date)
        except (StockNotFound, ValueError, ProviderError) as exc:
            _raise_public_error(exc)

    return router
