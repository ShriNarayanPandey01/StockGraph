"""Opaque bearer authentication and application-role dependencies."""

import hashlib
import json
import secrets
from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request

from marketgraph_platform.models import Principal


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, token_digest(token)


async def current_user(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 512:
        raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
    principal = await request.app.state.repository.authenticate(token_digest(token))
    if principal is None:
        raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
    principal = dict(principal)
    if isinstance(principal.get("roles"), str):
        principal["roles"] = json.loads(principal["roles"])
    user = Principal.model_validate(principal)
    if user.disabled:
        raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
    if user.plan_expires_at is not None and user.plan_expires_at <= datetime.now(UTC) and not user.is_developer:
        user = user.model_copy(update={"plan": "FREE"})
    if not user.is_developer and not await request.app.state.repository.allow_request(user.id):
        raise HTTPException(429, "Operational request budget exceeded", headers={"Retry-After": "60"})
    request.state.user = user
    return user


def require_developer(user: Principal) -> Principal:
    if not user.is_developer:
        raise HTTPException(403, "Developer access required")
    return user


def require_role(user: Principal, *roles: str) -> Principal:
    if not user.is_developer and not set(roles).intersection(user.roles):
        raise HTTPException(403, "Role permission required")
    return user
