"""Financial market read APIs, with provider validation and bounded Redis caching."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Literal, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from upstox_service.adapters.api.credentials import credential_context
from upstox_service.adapters.providers.upstox.client import ProviderError
from upstox_service.adapters.providers.upstox.market import (
    MarketInstrumentAmbiguous,
    MarketInstrumentNotFound,
    MarketProductUnavailable,
    UpstoxMarketProvider,
)

DataT = TypeVar("DataT")
EquityExchange = Literal["NSE", "BSE"]
SmartlistKind = Literal["mtf", "options", "futures"]
Investor = Literal["FII", "DII"]
AnalyticsMetric = Literal["pcr", "oi", "change-oi", "max-pain"]

_BASE_CATEGORIES = {"TOP_TRADED", "MOST_ACTIVE", "OI_GAINERS", "OI_LOSERS"}
_PRICE_CATEGORIES = {"PRICE_GAINERS", "PRICE_LOSERS"}
_FUTURES_EXTRA = {"PREMIUM", "DISCOUNT"}
_OPTIONS_EXTRA = {"IV_GAINERS", "IV_LOSERS", "UNDER_5000", "UNDER_10000"}
_FII_SEGMENTS = {
    "NSE_EQ|CASH",
    "NSE_FO|INDEX_FUTURES",
    "NSE_FO|STOCK_FUTURES",
    "NSE_FO|INDEX_OPTIONS",
    "NSE_FO|STOCK_OPTIONS",
}
_EXPIRY_KEYWORDS = {
    "current_week", "next_week", "far_week", "current_month", "next_month", "far_month"
}
_STATUS_EXCHANGES = {"NSE", "NFO", "CDS", "BSE", "BFO", "BCD", "MCX", "NSCOM"}


class MarketResponse[DataT](BaseModel):
    source: Literal["UPSTOX"] = "UPSTOX"
    fetched_at: datetime
    provider_as_of: datetime | None = None
    data: DataT


class OptionExpiries(BaseModel):
    underlying: str
    exchange: EquityExchange
    instrument_key: str
    expiries: list[date]


class OptionChain(BaseModel):
    underlying: str
    exchange: EquityExchange
    instrument_key: str
    expiry: str
    strikes: list[dict[str, Any]]


class SmartlistPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    asset_type: str
    category: str
    metric_key: str
    time_stamp: int | None = None
    smartlist: list[dict[str, Any]]
    page_number: int
    page_size: int
    total_pages: int


class InstitutionalFlows(BaseModel):
    investor: Investor
    interval: Literal["1D", "1M"]
    segments: dict[str, list[dict[str, Any]]]


class HolidaySession(BaseModel):
    exchange: str
    start_time: int
    end_time: int


class MarketHoliday(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: date
    description: str | None = None
    holiday_type: str | None = None
    closed_exchanges: list[str] = Field(default_factory=list)
    open_exchanges: list[HolidaySession] = Field(default_factory=list)


class ExchangeStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    exchange: str
    status: str
    last_updated: int | None = None


class DerivativesAnalytics(BaseModel):
    metric: AnalyticsMetric
    underlying: str
    exchange: EquityExchange
    instrument_key: str
    date: date
    data: dict[str, Any]


def _validate_expiry(expiry: str, *, allow_past: bool) -> str:
    if expiry in _EXPIRY_KEYWORDS:
        return expiry
    try:
        parsed = date.fromisoformat(expiry)
    except ValueError:
        raise HTTPException(422, "Expiry must be YYYY-MM-DD or a supported relative keyword") from None
    if not allow_past and parsed < _today_ist():
        raise HTTPException(422, "Option-chain expiry has passed")
    return parsed.isoformat()


def _today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _provider_as_of(data: Any) -> str | None:
    stamps: list[int | float] = []
    if isinstance(data, dict):
        for field in ("time_stamp", "last_updated"):
            value = data.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stamps.append(value)
        segments = data.get("segments")
        if isinstance(segments, dict):
            for rows in segments.values():
                if isinstance(rows, list):
                    stamps.extend(
                        row["time_stamp"]
                        for row in rows
                        if isinstance(row, dict)
                        and isinstance(row.get("time_stamp"), (int, float))
                    )
    if not stamps:
        return None
    try:
        value = max(stamps)
        return datetime.fromtimestamp(value / 1000 if value >= 10**12 else value, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _provider_http_error(exc: ProviderError) -> HTTPException:
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        if credential_context.get() is not None:
            return HTTPException(401, "broker_reconnect_required: Upstox credential rejected")
        return HTTPException(503, "Upstox authorization or market-data entitlement is unavailable")
    if status == 404:
        return HTTPException(404, "Requested Upstox market data is unavailable")
    if status in {400, 422}:
        return HTTPException(422, "Upstox does not support this market-data request")
    if exc.retryable or status == 429 or (status is not None and status >= 500):
        return HTTPException(503, "Upstox market data is temporarily unavailable")
    return HTTPException(502, "Upstox returned an invalid market-data response")


def create_market_router(
    provider: UpstoxMarketProvider,
    redis_client: Redis,
    *,
    live_ttl_seconds: int = 30,
    dated_ttl_seconds: int = 3600,
) -> APIRouter:
    """Create read-only routes; the API lifespan owns provider/client/Redis cleanup."""
    router = APIRouter(tags=["Market data"])

    async def respond(
        cache_parts: tuple[Any, ...], ttl: int, fetch: Callable[[], Awaitable[DataT]]
    ) -> dict[str, Any]:
        context = credential_context.get()
        cache_parts = (context.scope if context else "shared", *cache_parts)
        encoded = json.dumps(cache_parts, sort_keys=True, default=str, separators=(",", ":"))
        key = "upstox:market:v1:" + hashlib.sha256(encoded.encode()).hexdigest()
        try:
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass  # Cache outages must not change the result of a market read.
        try:
            data = await fetch()
        except MarketInstrumentNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except MarketInstrumentAmbiguous as exc:
            raise HTTPException(422, str(exc)) from None
        except MarketProductUnavailable as exc:
            raise HTTPException(404, str(exc)) from None
        except ProviderError as exc:
            raise _provider_http_error(exc) from None
        result = {
            "source": "UPSTOX",
            "fetched_at": datetime.now(UTC).isoformat(),
            "provider_as_of": _provider_as_of(data),
            "data": data,
        }
        if ttl > 0:
            try:
                await redis_client.set(key, json.dumps(result, separators=(",", ":")), ex=ttl)
            except Exception:
                pass
        return result

    @router.get("/api/v1/option-chains/expiries", response_model=MarketResponse[OptionExpiries])
    async def option_expiries(underlying: str = Query(min_length=2, max_length=50), exchange: EquityExchange = "NSE"):
        underlying = underlying.strip()
        return await respond(
            ("expiries", underlying.upper(), exchange),
            max(live_ttl_seconds, 300),
            lambda: provider.option_expiries(underlying, exchange),
        )

    @router.get("/api/v1/option-chains", response_model=MarketResponse[OptionChain])
    async def option_chain(
        underlying: str = Query(min_length=2, max_length=50),
        expiry: str = Query(min_length=7, max_length=20),
        exchange: EquityExchange = "NSE",
    ):
        underlying = underlying.strip()
        expiry = _validate_expiry(expiry, allow_past=False)
        return await respond(
            ("chain", underlying.upper(), exchange, expiry),
            live_ttl_seconds,
            lambda: provider.option_chain(underlying, exchange, expiry),
        )

    @router.get("/api/v1/market/smartlists/{kind}", response_model=MarketResponse[SmartlistPage])
    async def smartlist(
        kind: SmartlistKind,
        asset_type: Literal["INDEX", "STOCK", "COMMODITY"] | None = None,
        category: str | None = Query(default=None, min_length=2, max_length=30),
        page_number: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=50),
    ):
        if kind == "mtf":
            if asset_type is not None or category is not None:
                raise HTTPException(422, "MTF smartlist accepts pagination only")
        else:
            if asset_type is None or category is None:
                raise HTTPException(422, "asset_type and category are required")
            category = category.upper()
            allowed = _BASE_CATEGORIES.copy()
            if asset_type != "COMMODITY":
                allowed |= _PRICE_CATEGORIES
                allowed |= _OPTIONS_EXTRA if kind == "options" else _FUTURES_EXTRA
            if category not in allowed:
                raise HTTPException(422, "Category is unsupported for this smartlist asset type")
        return await respond(
            ("smartlist", kind, asset_type, category, page_number, page_size),
            live_ttl_seconds,
            lambda: provider.smartlist(
                kind,
                asset_type=asset_type,
                category=category,
                page_number=page_number,
                page_size=page_size,
            ),
        )

    @router.get("/api/v1/market/institutional-flows", response_model=MarketResponse[InstitutionalFlows])
    async def institutional_flows(
        investor: Investor,
        segment: str = Query(min_length=3, max_length=150),
        interval: Literal["1D", "1M"] = "1D",
        from_date: date | None = Query(default=None, alias="from"),
    ):
        data_types = tuple(part.strip().upper() for part in segment.split(","))
        if not data_types or any(part not in _FII_SEGMENTS for part in data_types):
            raise HTTPException(422, "Unsupported institutional-flow segment")
        if investor == "DII" and data_types != ("NSE_EQ|CASH",):
            raise HTTPException(422, "DII data supports NSE_EQ|CASH only")
        if len(set(data_types)) != len(data_types):
            raise HTTPException(422, "Duplicate institutional-flow segments")
        if from_date is not None and (from_date < date(2026, 4, 1) or from_date > _today_ist()):
            raise HTTPException(422, "Institutional-flow start date is outside available history")
        return await respond(
            ("flows", investor, data_types, interval, from_date),
            live_ttl_seconds,
            lambda: provider.institutional_flows(investor, data_types, interval, from_date),
        )

    @router.get("/api/v1/market/holidays", response_model=MarketResponse[list[MarketHoliday] | dict[str, Any]])
    async def holidays(for_date: date | None = Query(default=None, alias="date")):
        return await respond(
            ("holidays", for_date),
            dated_ttl_seconds,
            lambda: provider.holidays(for_date),
        )

    @router.get("/api/v1/market/status/{exchange}", response_model=MarketResponse[ExchangeStatus])
    async def exchange_status(exchange: str):
        exchange = exchange.upper()
        if exchange not in _STATUS_EXCHANGES:
            raise HTTPException(422, "Unsupported exchange")
        return await respond(
            ("status", exchange),
            live_ttl_seconds,
            lambda: provider.exchange_status(exchange),
        )

    @router.get("/api/v1/market/pcr", response_model=MarketResponse[DerivativesAnalytics])
    @router.get("/api/v1/market/oi", response_model=MarketResponse[DerivativesAnalytics])
    @router.get("/api/v1/market/change-oi", response_model=MarketResponse[DerivativesAnalytics])
    @router.get("/api/v1/market/max-pain", response_model=MarketResponse[DerivativesAnalytics])
    async def analytics(
        request: Request,
        underlying: str = Query(min_length=2, max_length=50),
        expiry: str = Query(min_length=7, max_length=20),
        exchange: EquityExchange = "NSE",
        for_date: date = Query(alias="date"),
        interval: int | None = Query(default=None, ge=1, le=30),
        bucket_interval: int | None = Query(default=None, ge=1, le=375),
    ):
        metric = request.url.path.rsplit("/", 1)[-1]
        underlying = underlying.strip()
        expiry = _validate_expiry(expiry, allow_past=True)
        if for_date > _today_ist():
            raise HTTPException(422, "Analytics date cannot be in the future")
        if metric == "change-oi":
            if bucket_interval is not None:
                raise HTTPException(422, "change-oi does not accept bucket_interval")
            interval = interval or 1
        elif metric in {"pcr", "max-pain"}:
            if interval is not None:
                raise HTTPException(422, "This metric does not accept interval")
            bucket_interval = bucket_interval or 60
        elif interval is not None or bucket_interval is not None:
            raise HTTPException(422, "oi does not accept interval parameters")
        ttl = dated_ttl_seconds if for_date < _today_ist() else live_ttl_seconds
        return await respond(
            ("analytics", metric, underlying.upper(), exchange, expiry, for_date, interval, bucket_interval),
            ttl,
            lambda: provider.derivatives_analytics(
                metric,
                underlying,
                exchange,
                expiry,
                for_date,
                interval=interval,
                bucket_interval=bucket_interval,
            ),
        )

    @router.get("/api/v1/market/{metric}", include_in_schema=False)
    async def unknown_metric(metric: str):
        raise HTTPException(404, "Unknown market metric")

    return router
