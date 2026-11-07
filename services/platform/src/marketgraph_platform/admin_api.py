"""Audited developer operations over supported service contracts."""
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from marketgraph_platform.errors import PlatformError
from marketgraph_platform.policy import require_permission

RECORDS = {"watchlists":"watchlists","conversations":"conversations","messages":"research_messages",
           "monitors":"monitors","jobs":"agent_jobs","alerts":"opportunity_alerts",
           "contributions":"platform_contributions"}


class CatalogEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    changes: dict[str, object] = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)


class DeveloperEdgeEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    relation: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("metadata")
    @classmethod
    def metadata_size(cls, value):
        if len(value) > 40:
            raise ValueError("Metadata is too large")
        return value


def build_admin_router(current_user):
    router = APIRouter(tags=["Developer operations"])

    async def developer(request: Request,user=Depends(current_user)):
        require_permission(user,"admin")
        request.state.access = await request.app.state.entitlements.check(user)
        return user

    async def graph(request,user,method,path,body=None,params=None):
        await request.app.state.repository.audit_action(
            user.id, "graph." + method, details={"path": path}
        )
        return await request.app.state.graph_client.request(
            method, path, body=body, params=params, developer=True, professional=True
        )

    @router.get("/api/v1/admin/users/{owner_id}/records/{resource}")
    async def records(owner_id: UUID,resource: Literal["watchlists","conversations","messages","monitors","jobs","alerts","contributions"],
                      request: Request,user=Depends(developer),limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
        repository = request.app.state.repository
        items = await repository.admin_records(owner_id, resource, limit, offset)
        await repository.audit_action(user.id, "records.read", owner_id, {"resource": resource})
        return {"items": items}

    @router.get("/api/v1/admin/audit")
    async def audit(request: Request,user=Depends(developer),limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
        return {"items": await request.app.state.repository.admin_audit(limit, offset)}

    @router.get("/api/v1/admin/graph/entities")
    async def graph_entities(request: Request,user=Depends(developer),
                             kind: Literal["Stock","Commodity","MacroFactor","Sector"]|None=None):
        result = await request.app.state.canonical_client.get(
            "/api/v1/entities", {"kind":kind} if kind else None)
        await request.app.state.repository.audit_action(
            user.id, "graph.catalog.read", details={"kind": kind}
        )
        return result

    @router.get("/api/v1/admin/graph/stocks/{ticker}/context")
    async def stock_graph_context(ticker: str,request: Request,user=Depends(developer),
                                  window: Literal["LAST_6M","LAST_1Y"]="LAST_6M",
                                  offset: int=Query(0,ge=0,le=100000),
                                  limit: int=Query(50,ge=1,le=200),
                                  as_of_ts: int|None=Query(None,ge=0)):
        if set(request.query_params)-{"window","offset","limit","as_of_ts"}:
            raise PlatformError(422,"Only supported graph windows and pagination parameters are accepted")
        params = {"window":window,"offset":offset,"limit":limit}
        if as_of_ts is not None:
            params["as_of_ts"] = as_of_ts
        return await graph(request,user,"GET",
                           f"/api/v1/stocks/{quote(ticker.strip().upper(),safe='')}/context",
                           params=params)

    @router.patch("/api/v1/admin/graph/entities/{kind}/{entity_id}",status_code=202)
    async def update_graph_entity(kind: Literal["Stock","Commodity","MacroFactor","Sector"],
                                  entity_id: str,body: CatalogEdit,request: Request,
                                  user=Depends(developer)):
        path = f"/api/v1/admin/entities/{kind}/{quote(entity_id,safe='')}"
        result = await request.app.state.canonical_client.patch_internal(
            path,{"changes":body.changes,"reason":body.reason})
        await request.app.state.repository.audit_action(
            user.id, "graph.catalog.update",
            details={"kind": kind, "entity_id": entity_id,
                     "fields": sorted(body.changes), "reason": body.reason,
                     "revision": result.get("revision")},
        )
        return result

    @router.get("/api/v1/admin/users/{owner_id}/broker-connections/upstox")
    async def broker_status(owner_id: UUID,request: Request,user=Depends(developer)):
        await request.app.state.repository.audit_action(user.id, "broker.status", owner_id)
        return await request.app.state.brokers.status(owner_id)

    @router.delete("/api/v1/admin/users/{owner_id}/broker-connections/upstox")
    async def broker_disconnect(owner_id: UUID,request: Request,user=Depends(developer)):
        await request.app.state.repository.audit_action(user.id, "broker.disconnect", owner_id)
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

    @router.get("/api/v1/admin/graph/edges")
    async def edges(request: Request,user=Depends(developer),
                    limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
        return await graph(request,user,"GET","/api/v1/developer/edges",
                           params={"limit":limit,"offset":offset})

    @router.put("/api/v1/admin/graph/edges/{edge_id}")
    async def update_edge(edge_id: str,body: DeveloperEdgeEdit,request: Request,
                          user=Depends(developer)):
        payload = body.model_dump(exclude={"reason"})
        payload["actor"] = "developer:" + str(user.id)
        result = await graph(request,user,"PUT",
                             "/api/v1/developer/edges/"+quote(edge_id,safe=""),payload)
        await request.app.state.repository.audit_action(
            user.id, "graph.edge.update", details={"edge_id": edge_id, "reason": body.reason}
        )
        return result

    @router.delete("/api/v1/admin/graph/edges/{edge_id}")
    async def remove_edge(edge_id: str,request: Request,user=Depends(developer)):
        return await graph(request,user,"DELETE","/api/v1/developer/edges/"+quote(edge_id,safe=""))

    @router.get("/api/v1/admin/market/{resource}")
    async def market(resource: Literal["option-expiries","option-chain","institutional-flows","holidays","pcr","oi","change-oi","max-pain"],
                     request: Request,user=Depends(developer)):
        paths = {"option-expiries":"/api/v1/option-chains/expiries","option-chain":"/api/v1/option-chains"}
        await request.app.state.repository.audit_action(
            user.id, "market.read", details={"resource": resource}
        )
        return await request.app.state.canonical_client.get(paths.get(resource,"/api/v1/market/"+resource),dict(request.query_params))

    @router.post("/api/v1/admin/documents",status_code=202)
    async def upload_document(body: dict,request: Request,user=Depends(developer)):
        key = request.app.state.settings.document_internal_api_key.get_secret_value()
        if not key:
            raise PlatformError(503,"Document intake is not configured")
        await request.app.state.repository.audit_action(user.id, "documents.intake")
        return await request.app.state.canonical_client.post_internal("/api/v1/documents",body,headers={"X-Internal-Api-Key":key})

    return router

