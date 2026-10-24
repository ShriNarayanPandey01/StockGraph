"""Same-origin browser integration with the existing bounded Graph API."""

from importlib.resources import files
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from marketgraph_platform.agent_api import graph_get


def build_connections_router(current_user):
    router = APIRouter(tags=['Stock connections'])
    assets = files('marketgraph_platform').joinpath('web')

    @router.get('/connections',include_in_schema=False)
    async def explorer():
        return FileResponse(str(assets.joinpath('index.html')),headers={
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Cache-Control':'no-store',
        })

    @router.get('/connections/assets/{asset}',include_in_schema=False)
    async def asset(asset: Literal['explorer.js','explorer.css','mark.svg']):
        return FileResponse(str(assets.joinpath(asset)),headers={'X-Content-Type-Options':'nosniff'})

    @router.get('/api/v1/stocks/{ticker}/connections')
    async def connections(ticker: str,request: Request,user=Depends(current_user),
                          window: Literal['LAST_6M','LAST_1Y']='LAST_6M',
                          offset: int=Query(0,ge=0,le=100000),limit: int=Query(50,ge=1,le=200),
                          as_of_ts: int|None=Query(None,ge=0)):
        if set(request.query_params)-{'window','offset','limit','as_of_ts'}:
            raise HTTPException(422,'Only fixed research windows and pagination parameters are supported')
        params = {'window':window,'offset':offset,'limit':limit}
        if as_of_ts is not None:
            params['as_of_ts']=as_of_ts
        result = await graph_get(request,f'/api/v1/stocks/{quote(ticker.strip().upper(),safe="")}/context',params)
        await request.app.state.repository.measure(user.id,'stock_connections')
        return result

    return router
