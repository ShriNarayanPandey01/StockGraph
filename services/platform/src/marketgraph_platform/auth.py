"""Opaque tokens are provisioned by an operator; only their digests are stored."""

import hashlib
import secrets

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
    if not await request.app.state.repository.allow_request(principal["id"]):
        raise HTTPException(429, "Operational request budget exceeded", headers={"Retry-After": "60"})
    return Principal.model_validate(principal)
