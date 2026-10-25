"""Authenticated policy and administrative quota configuration."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from marketgraph_platform.entitlements import audit_admin
from marketgraph_platform.policy import FEATURES, require_permission
from marketgraph_platform.repository import PlatformError


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickers: list[str] = Field(default_factory=list, max_length=5000)

    @field_validator("tickers")
    @classmethod
    def canonical_shape(cls, tickers):
        return sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    active_stock_limit: int | None = Field(default=None, ge=1)
    monthly_alert_limit: int | None = Field(default=None, ge=1)
    features: dict[str, bool]

    @field_validator("features")
    @classmethod
    def complete_features(cls, value):
        if set(value) != set(FEATURES):
            raise ValueError("Supply exactly the documented feature names")
        return value


def build_policy_router(current_user):
    router = APIRouter(tags=["Access and plan administration"])

    @router.get("/api/v1/me/active-stocks")
    async def selection(request: Request, user=Depends(current_user)):
        return await request.app.state.entitlements.selection(user)

    @router.put("/api/v1/me/active-stocks")
    async def select(body: Selection, request: Request, user=Depends(current_user)):
        for ticker in body.tickers:
            await request.app.state.canonical_client.validate_ticker(ticker)
        return await request.app.state.entitlements.select(user, body.tickers)

    @router.get("/api/v1/admin/plans")
    async def plans(request: Request, user=Depends(current_user)):
        require_permission(user, "admin")
        rows = await request.app.state.repository.pool.fetch("SELECT * FROM platform_plan_policies ORDER BY plan")
        return {"items": [{**dict(row), "features": json.loads(row["features"]) if isinstance(row["features"],str) else row["features"]} for row in rows]}

    @router.put("/api/v1/admin/plans/{plan}")
    async def update(plan: Literal["FREE", "PRO"], body: PlanInput, request: Request, user=Depends(current_user)):
        require_permission(user, "admin")
        async with request.app.state.repository.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "UPDATE platform_plan_policies SET active_stock_limit=$2,monthly_alert_limit=$3,features=$4::jsonb,"
                "revision=revision+1 WHERE plan=$1 AND revision=$5 RETURNING *", plan,
                body.active_stock_limit, body.monthly_alert_limit, json.dumps(body.features), body.expected_revision)
            if row is None:
                raise PlatformError(409, "Plan changed; reload its revision")
            await audit_admin(conn, user.id, "plan.policy", details={"plan": plan, "revision": row["revision"]})
        return {**dict(row), "features": body.features}

    return router

