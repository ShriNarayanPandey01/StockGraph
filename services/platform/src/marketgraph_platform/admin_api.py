"""Audited developer operations over supported service contracts."""
from typing import Literal
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request

from marketgraph_platform.entitlements import audit_admin
from marketgraph_platform.policy import require_permission
from marketgraph_platform.repository import PlatformError

RECORDS = {"watchlists":"watchlists","conversations":"conversations","messages":"research_messages",
           "monitors":"monitors","jobs":"agent_jobs","alerts":"opportunity_alerts",
           "contributions":"platform_contributions"}


def build_admin_router(current_user):
    router = APIRouter(tags=["Developer operations"])

    async def developer(request: Request,user=Depends(current_user)):
        require_permission(user,"admin")
        request.state.access = await request.app.state.entitlements.check(user)
        return user

    async def graph(request,user,method,path,body=None):
        settings = request.app.state.settings
        await audit_admin(request.app.state.repository.pool,user.id,"graph."+method,details={"path":path})
        try:
            async with httpx.AsyncClient(base_url=settings.graph_service_url,timeout=settings.http_timeout_seconds,
                    headers={"X-Internal-Service-Key":settings.internal_service_key.get_secret_value(),
                             "X-MarketGraph-Developer":"true","X-MarketGraph-Evidence-Scope":"professional"}) as client:
                result = await client.request(method,path,json=body)
                if result.status_code in (400,404,409,422):
                    raise PlatformError(result.status_code,"Graph service rejected the operation")
                result.raise_for_status()
                return result.json()
        except (httpx.HTTPError,ValueError):
            raise PlatformError(503,"Graph service is unavailable") from None

    @router.get("/api/v1/admin/users/{owner_id}/records/{resource}")
    async def records(owner_id: UUID,resource: Literal["watchlists","conversations","messages","monitors","jobs","alerts","contributions"],
                      request: Request,user=Depends(developer),limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
        table = RECORDS[resource]
        column = "author_id" if resource == "contributions" else "user_id"
        rows = await request.app.state.repository.pool.fetch(
            f"SELECT * FROM {table} WHERE {column}=$1 ORDER BY id LIMIT $2 OFFSET $3",owner_id,limit,offset)
        await audit_admin(request.app.state.repository.pool,user.id,"records.read",owner_id,{"resource":resource})
        return {"items":[{k:v for k,v in dict(row).items() if k not in ("lease_token","fingerprint","result_fingerprint")} for row in rows]}

    @router.get("/api/v1/admin/audit")
    async def audit(request: Request,user=Depends(developer),limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
        return {"items":[dict(row) for row in await request.app.state.repository.pool.fetch(
            "SELECT * FROM platform_admin_audit ORDER BY id DESC LIMIT $1 OFFSET $2",limit,offset)]}

    @router.get("/api/v1/admin/users/{owner_id}/broker-connections/upstox")
    async def broker_status(owner_id: UUID,request: Request,user=Depends(developer)):
        await audit_admin(request.app.state.repository.pool,user.id,"broker.status",owner_id)
        return await request.app.state.brokers.status(owner_id)

    @router.delete("/api/v1/admin/users/{owner_id}/broker-connections/upstox")
    async def broker_disconnect(owner_id: UUID,request: Request,user=Depends(developer)):
        await audit_admin(request.app.state.repository.pool,user.id,"broker.disconnect",owner_id)
        return await request.app.state.brokers.disconnect(owner_id)

    @router.post("/api/v1/admin/manual/stocks",status_code=202)
    async def stock(body: dict,request: Request,user=Depends(developer)):
        return await graph(request,user,"POST","/api/v1/manual/stocks",body)

    @router.post("/api/v1/admin/manual/entities/{kind}",status_code=202)
    async def entity(kind: Literal["Commodity","MacroFactor","Sector"],body: dict,request: Request,user=Depends(developer)):
        return await graph(request,user,"POST","/api/v1/manual/entities/"+kind,body)

    @router.post("/api/v1/admin/manual/news",status_code=202)
    async def news(body: dict,request: Request,user=Depends(developer)):
        return await graph(request,user,"POST","/api/v1/manual/news",body)

    @router.post("/api/v1/admin/graph/edges",status_code=201)
    async def edge(body: dict,request: Request,user=Depends(developer)):
        return await graph(request,user,"POST","/api/v1/developer/edges",{**body,"actor":"developer:"+str(user.id)})

    @router.delete("/api/v1/admin/graph/edges/{edge_id}")
    async def remove_edge(edge_id: str,request: Request,user=Depends(developer)):
        return await graph(request,user,"DELETE","/api/v1/developer/edges/"+quote(edge_id,safe=""))

    @router.get("/api/v1/admin/market/{resource}")
    async def market(resource: Literal["option-expiries","option-chain","institutional-flows","holidays","pcr","oi","change-oi","max-pain"],
                     request: Request,user=Depends(developer)):
        paths = {"option-expiries":"/api/v1/option-chains/expiries","option-chain":"/api/v1/option-chains"}
        await audit_admin(request.app.state.repository.pool,user.id,"market.read",details={"resource":resource})
        return await request.app.state.canonical_client.get(paths.get(resource,"/api/v1/market/"+resource),dict(request.query_params))

    @router.post("/api/v1/admin/documents",status_code=202)
    async def upload_document(body: dict,request: Request,user=Depends(developer)):
        key = request.app.state.settings.document_internal_api_key.get_secret_value()
        if not key:
            raise PlatformError(503,"Document intake is not configured")
        await audit_admin(request.app.state.repository.pool,user.id,"documents.intake")
        return await request.app.state.canonical_client.post_internal("/api/v1/documents",body,headers={"X-Internal-Api-Key":key})

    return router

