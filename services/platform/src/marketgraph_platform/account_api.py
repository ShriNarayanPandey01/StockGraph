"""Public account lifecycle and developer-only account administration."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, SecretStr, field_validator

from marketgraph_platform.auth import require_developer, token_digest
from marketgraph_platform.models import Input, Principal


def normalize_email(value: str) -> str:
    import re
    normalized = value.strip().casefold()
    if len(normalized) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("A valid email address is required")
    return normalized


class EmailInput(Input):
    email: str

    _email = field_validator("email")(normalize_email)


class PasswordInput(EmailInput):
    password: SecretStr = Field(min_length=12, max_length=1024)


class SignupInput(PasswordInput):
    name: str = Field(min_length=1, max_length=200)


class LoginInput(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=1024)


class ChangePasswordInput(Input):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    password: SecretStr = Field(min_length=12, max_length=1024)


class AdminUserInput(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[Literal["USER", "PROFESSIONAL", "REVIEWER"]] | None = Field(default=None, min_length=1, max_length=3)
    professional_verified: bool | None = None
    plan: Literal["FREE", "PRO"] | None = None
    plan_expires_at: datetime | None = None
    disabled: bool | None = None

    @field_validator("plan_expires_at")
    @classmethod
    def aware_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None or value <= datetime.now(UTC)):
            raise ValueError("Plan expiry must be an aware future timestamp")
        return value


def address(request: Request) -> str:
    # Forwarded headers are untrusted unless an operator-configured ASGI proxy resolves them.
    return request.client.host if request.client else "unknown"


def build_account_router(current_user):
    router = APIRouter(tags=["Accounts"])

    async def developer(user: Principal = Depends(current_user)):
        return require_developer(user)

    @router.post("/api/v1/auth/signup", status_code=202)
    async def signup(body: SignupInput, request: Request):
        return await request.app.state.accounts.signup(body.email, body.name, body.password.get_secret_value(), address(request))

    @router.post("/api/v1/auth/login")
    async def login(body: LoginInput, request: Request):
        return await request.app.state.accounts.login(body.email, body.password.get_secret_value(), address(request))

    @router.post("/api/v1/auth/logout")
    async def logout(request: Request, authorization: str = Header(), user: Principal = Depends(current_user)):
        return await request.app.state.accounts.logout(token_digest(authorization.partition(" ")[2]))

    @router.post("/api/v1/auth/change-password")
    async def change(body: ChangePasswordInput, request: Request, user: Principal = Depends(current_user)):
        return await request.app.state.accounts.change_password(user, body.current_password.get_secret_value(), body.password.get_secret_value())

    @router.get("/api/v1/admin/users")
    async def users(request: Request, user: Principal = Depends(developer), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        async with request.app.state.repository.pool.acquire() as conn:
            await request.app.state.accounts.audit(conn, user.id, "users.listed")
        return await request.app.state.accounts.list_users(limit, offset)

    @router.get("/api/v1/admin/users/{user_id}")
    async def user_detail(user_id: UUID, request: Request, user: Principal = Depends(developer)):
        result = await request.app.state.accounts.user_detail(user_id)
        async with request.app.state.repository.pool.acquire() as conn:
            await request.app.state.accounts.audit(conn, user.id, "user.read", user_id)
        return result

    @router.patch("/api/v1/admin/users/{user_id}")
    async def update_user(user_id: UUID, body: AdminUserInput, request: Request, user: Principal = Depends(developer)):
        changes = body.model_dump(exclude_unset=True)
        if any(value is None and key != "plan_expires_at" for key, value in changes.items()):
            from marketgraph_platform.repository import PlatformError
            raise PlatformError(422, "Account fields cannot be null")
        return await request.app.state.accounts.update_user(user, user_id, changes)

    @router.post("/api/v1/admin/users/{user_id}/revoke-sessions")
    async def revoke(user_id: UUID, request: Request, user: Principal = Depends(developer)):
        return await request.app.state.accounts.revoke_sessions(user, user_id)

    return router
