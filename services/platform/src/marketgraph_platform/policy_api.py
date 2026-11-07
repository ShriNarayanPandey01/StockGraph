"""Authenticated policy and administrative quota configuration."""
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from marketgraph_platform.policy import FEATURES, require_permission


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
        return {"items": await request.app.state.repository.plan_policies()}

    @router.put("/api/v1/admin/plans/{plan}")
    async def update(plan: Literal["FREE", "PRO"], body: PlanInput, request: Request, user=Depends(current_user)):
        require_permission(user, "admin")
        return await request.app.state.repository.update_plan_policy(
            plan, body.expected_revision, body.active_stock_limit,
            body.monthly_alert_limit, body.features, user.id
        )

    return router

