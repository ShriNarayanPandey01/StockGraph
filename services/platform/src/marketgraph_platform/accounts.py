"""Account application use cases over explicit persistence operations."""

from __future__ import annotations

import asyncio
import json
import secrets
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from marketgraph_platform.application.ports import AccountRepositoryPort
from marketgraph_platform.auth import issue_token, token_digest
from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import Principal

_PASSWORDS = PasswordHasher(type=Type.ID)
_DUMMY_HASH = _PASSWORDS.hash(secrets.token_urlsafe(32))


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        return bool(_PASSWORDS.verify(encoded or _DUMMY_HASH, password)) and bool(encoded)
    except (InvalidHashError, VerificationError):
        return False


def profile(row) -> dict:
    value = dict(row)
    if isinstance(value.get("roles"), str):
        value["roles"] = json.loads(value["roles"])
    return Principal.model_validate(
        {key: value[key] for key in Principal.model_fields if key in value}
    ).model_dump(mode="json")


class AccountService:
    def __init__(self, repository: AccountRepositoryPort, settings):
        self._repository = repository
        self._settings = settings

    async def bootstrap_developer(self):
        email = self._settings.admin_email.strip().casefold()
        password = self._settings.admin_password.get_secret_value()
        if bool(email) != bool(password):
            raise RuntimeError("Both developer email and password must be configured")
        await self._repository.synchronize_developer(
            self._settings.admin_name, email, password, verify_password, _PASSWORDS.hash
        )

    async def throttle(self, action: str, email: str, address: str,
                       *, email_limit: int = 5, ip_limit: int = 20):
        for category, identity, limit in (
            ("email", email, email_limit), ("ip", address, ip_limit)
        ):
            key = token_digest(f"{action}:{category}:{identity}")
            await self._repository.count_auth_attempt(key, limit)

    async def signup(self, email: str, name: str, password: str, address: str):
        await self.throttle("signup", email, address, email_limit=2, ip_limit=10)
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
        await self._repository.create_account(email, name, encoded)
        return {"detail": "If this address is eligible, the account is ready. Sign in to continue"}

    async def login(self, email: str, password: str, address: str):
        await self.throttle("login", email, address, email_limit=10, ip_limit=30)
        candidate = await self._repository.login_candidate(email)
        valid = await asyncio.to_thread(
            verify_password, candidate["password_hash"] if candidate else None, password
        )
        if not valid or candidate is None or candidate["disabled"]:
            raise PlatformError(401, "Invalid login credentials")
        if candidate["is_developer"] and (
            not self._settings.admin_password.get_secret_value()
            or email != self._settings.admin_email.strip().casefold()
        ):
            raise PlatformError(401, "Invalid login credentials")
        token, digest = issue_token()
        replacement_hash = None
        if _PASSWORDS.check_needs_rehash(candidate["password_hash"]):
            replacement_hash = await asyncio.to_thread(_PASSWORDS.hash, password)
        current, expires = await self._repository.create_login_session(
            candidate["id"], candidate["password_hash"], digest,
            self._settings.session_ttl_seconds, replacement_hash,
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires,
            "user": profile(current),
        }

    async def logout(self, digest: str):
        await self._repository.revoke_session(digest)
        return {"detail": "Session revoked"}

    async def change_password(self, user: Principal, current_password: str, password: str):
        if user.is_developer:
            raise PlatformError(403, "Developer credentials are managed through environment configuration")
        previous_hash = await self._repository.account_password_hash(user.id)
        if not previous_hash or not await asyncio.to_thread(
            verify_password, previous_hash, current_password
        ):
            raise PlatformError(401, "Invalid current password")
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
        await self._repository.change_account_password(user.id, previous_hash, encoded)
        return {"detail": "Password changed; log in again"}

    async def audit_action(self, actor_id: UUID, action: str,
                           target_user_id: UUID | None = None, details: dict | None = None):
        await self._repository.audit_action(actor_id, action, target_user_id, details)

    async def list_users(self, limit: int, offset: int):
        rows = await self._repository.list_account_rows(limit, offset)
        return {"items": [profile(row) for row in rows], "limit": limit, "offset": offset}

    async def user_detail(self, user_id: UUID):
        row = await self._repository.account_row(user_id)
        if row is None:
            raise PlatformError(404, "Unknown user")
        return profile(row)

    async def update_user(self, actor: Principal, user_id: UUID, changes: dict):
        return profile(await self._repository.update_account(actor, user_id, changes))

    async def revoke_sessions(self, actor: Principal, user_id: UUID):
        return await self._repository.revoke_account_sessions(actor, user_id)


Accounts = AccountService
