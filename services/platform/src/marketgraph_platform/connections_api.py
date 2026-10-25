"""Authenticated Platform proxy endpoints for market and graph APIs."""

from datetime import date
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from marketgraph_platform.agent_api import graph_get


class StockRegistrationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=50)
    exchange: Literal['NSE', 'BSE'] = 'NSE'
    strengths: list[str] = Field(default_factory=list, max_length=30)
    business_exclusions: list[str] = Field(default_factory=list, max_length=30)


async def graph_post(request: Request, path: str, payload: dict):
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(base_url=settings.graph_service_url,
                                     timeout=settings.http_timeout_seconds,
                                     headers={"X-Internal-Service-Key":settings.internal_service_key.get_secret_value(),
                                              "X-MarketGraph-Developer":"true" if getattr(request.state,"user",None) and request.state.user.is_developer else "false"}) as client:
            response = await client.post(path, json=payload)
            if response.status_code in (400, 404, 409, 422):
                raise HTTPException(response.status_code, 'Graph service rejected the request')
            response.raise_for_status()
            return response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Graph service is unavailable; retry the request') from None


def build_connections_router(current_user):
    router = APIRouter(tags=['Stock connections'])

    async def check_stock(request, user, ticker):
        ticker = ticker.strip().upper()
        request.state.access = await request.app.state.entitlements.check(user, "stock_connections", [ticker])
        return ticker

    @router.get('/api/v1/market/stocks')
    async def market_stocks(request: Request, user=Depends(current_user),
                            query: str=Query('', max_length=80),
                            exchange: Literal['NSE','BSE']|None=None,
                            cursor: str|None=Query(None, max_length=1024),
                            limit: int=Query(50, ge=1, le=100)):
        if set(request.query_params)-{'query','exchange','cursor','limit'}:
            raise HTTPException(422, 'Unsupported market search parameter')
        params = {'query':query, 'limit':limit}
        if exchange:
            params['exchange'] = exchange
        if cursor:
            params['cursor'] = cursor
        result = await request.app.state.canonical_client.get('/api/v1/stocks', params)
        await request.app.state.repository.measure(user.id, 'market_stock_searches')
        return result

    @router.get('/api/v1/market/stocks/{ticker}')
    async def market_stock(ticker: str, request: Request, user=Depends(current_user),
                           exchange: Literal['NSE','BSE']='NSE'):
        ticker = await check_stock(request,user,ticker)
        result = await request.app.state.brokers.read(user.id,
            f'/api/v1/stocks/{quote(ticker.strip().upper(), safe="")}', {'exchange':exchange})
        await request.app.state.repository.measure(user.id, 'market_stock_reads')
        return result

    @router.get('/api/v1/market/stocks/{ticker}/candles')
    async def market_candles(ticker: str, request: Request, user=Depends(current_user),
                             exchange: Literal['NSE','BSE']='NSE',
                             start: date|None=Query(None, alias='from'),
                             end: date|None=Query(None, alias='to')):
        ticker = await check_stock(request,user,ticker)
        params = {'exchange':exchange}
        if start:
            params['from'] = start.isoformat()
        if end:
            params['to'] = end.isoformat()
        result = await request.app.state.brokers.read(user.id,
            f'/api/v1/stocks/{quote(ticker.strip().upper(), safe="")}/candles', params)
        await request.app.state.repository.measure(user.id, 'market_candle_reads')
        return result

    @router.get('/api/v1/market/stocks/{ticker}/shareholding')
    async def market_shareholding(ticker: str, request: Request, user=Depends(current_user),
                                  exchange: Literal['NSE','BSE']='NSE'):
        ticker = await check_stock(request,user,ticker)
        result = await request.app.state.brokers.read(user.id,
            f'/api/v1/stocks/{quote(ticker.strip().upper(), safe="")}/shareholding', {'exchange':exchange})
        await request.app.state.repository.measure(user.id, 'market_shareholding_reads')
        return result

    @router.post('/api/v1/market/stock-registrations', status_code=202)
    async def register_stock(body: StockRegistrationInput, request: Request,
                             user=Depends(current_user)):
        request.state.access = await request.app.state.entitlements.check(user)
        result = await graph_post(request, '/api/v1/stocks', body.model_dump())
        await request.app.state.repository.measure(user.id, 'stock_registrations')
        return result

    @router.get('/api/v1/market/stock-registrations/{job_id}')
    async def registration_status(job_id: str, request: Request, user=Depends(current_user)):
        request.state.access = await request.app.state.entitlements.check(user)
        result = await graph_get(request, f'/api/v1/jobs/{quote(job_id, safe="")}', {})
        await request.app.state.repository.measure(user.id, 'stock_registration_status_reads')
        return result

    @router.get('/api/v1/stocks/{ticker}/connections')
    async def connections(ticker: str,request: Request,user=Depends(current_user),
                          window: Literal['LAST_6M','LAST_1Y']='LAST_6M',
                          offset: int=Query(0,ge=0,le=100000),limit: int=Query(50,ge=1,le=200),
                          as_of_ts: int|None=Query(None,ge=0)):
        if set(request.query_params)-{'window','offset','limit','as_of_ts'}:
            raise HTTPException(422,'Only fixed research windows and pagination parameters are supported')
        ticker = await check_stock(request,user,ticker)
        params = {'window':window,'offset':offset,'limit':limit}
        if as_of_ts is not None:
            params['as_of_ts']=as_of_ts
        result = await graph_get(request,f'/api/v1/stocks/{quote(ticker.strip().upper(),safe="")}/context',params)
        await request.app.state.repository.measure(user.id,'stock_connections')
        return result

    @router.get("/api/v1/market/stocks/{ticker}/financials")
    async def financials(ticker: str,request: Request,user=Depends(current_user),
                         window: Literal["LAST_6M","LAST_1Y"]="LAST_6M"):
        ticker = await check_stock(request,user,ticker)
        return await request.app.state.canonical_client.get(
            f"/api/v1/stocks/{quote(ticker,safe='')}/financials", {"window":window})

    @router.get("/api/v1/stocks/{ticker}/documents/search")
    async def documents(ticker: str,request: Request,user=Depends(current_user),
                        q: str=Query("",max_length=200),offset: int=Query(0,ge=0,le=10000),
                        limit: int=Query(50,ge=1,le=200)):
        ticker = await check_stock(request,user,ticker)
        return await graph_get(request,f"/api/v1/stocks/{quote(ticker,safe='')}/documents/search",
                               {"q":q,"offset":offset,"limit":limit})

    @router.get("/api/v1/documents/{version_id}")
    async def document(version_id: str,request: Request,user=Depends(current_user)):
        from uuid import UUID
        try:
            identity = str(UUID(version_id))
        except ValueError:
            raise HTTPException(422,"Invalid document identity") from None
        item = await request.app.state.canonical_client.get(f"/api/v1/documents/{identity}")
        await check_stock(request,user,item["ticker"])
        return item

    return router
