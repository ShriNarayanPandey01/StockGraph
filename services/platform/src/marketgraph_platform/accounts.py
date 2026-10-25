"""Account credentials, single-use challenges and environment-owned developer access.

Raw passwords, codes and bearer tokens are used only in memory or SMTP delivery.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from asyncpg import UniqueViolationError

from marketgraph_platform.auth import issue_token, token_digest
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import PlatformError

_PASSWORDS = PasswordHasher(type=Type.ID)
_DUMMY_HASH = _PASSWORDS.hash(secrets.token_urlsafe(32))
PROFILE_COLUMNS = "id,name,email,email_verified,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        return bool(_PASSWORDS.verify(encoded or _DUMMY_HASH, password)) and bool(encoded)
    except (InvalidHashError, VerificationError):
        return False


def profile(row) -> dict:
    value = dict(row)
    if isinstance(value.get("roles"), str):
        value["roles"] = json.loads(value["roles"])
    return Principal.model_validate({key: value[key] for key in Principal.model_fields if key in value}).model_dump(mode="json")


class Accounts:
    def __init__(self, repository, settings=None):
        self.repository = repository
        self.settings = settings if settings is not None else repository.settings

    @property
    def pool(self):
        return self.repository.pool

    async def audit(self, conn, actor_id: UUID, action: str, target_user_id: UUID | None = None, details: dict | None = None):
        await conn.execute(
            "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) VALUES($1,$2,$3,$4::jsonb)",
            actor_id, target_user_id, action, json.dumps(details or {}, default=str),
        )

    async def bootstrap_developer(self):
        email = self.settings.admin_email.strip().casefold()
        password = self.settings.admin_password.get_secret_value()
        if bool(email) != bool(password):
            raise RuntimeError("Both developer email and password must be configured")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(780436153)")
            previous = await conn.fetchrow("SELECT * FROM platform_users WHERE is_developer FOR UPDATE")
            if not email:
                if previous:
                    await conn.execute("UPDATE platform_users SET disabled=true WHERE id=$1", previous["id"])
                    await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", previous["id"])
                return
            if len(password) < 12 or len(password) > 1024:
                raise RuntimeError("Developer password must contain 12 to 1024 characters")
            developer_id = previous["id"] if previous else uuid4()
            conflict = await conn.fetchval("SELECT id FROM platform_users WHERE lower(email)=$1 AND id<>$2", email, developer_id)
            if conflict:
                raise RuntimeError("Developer identity conflicts with an existing account")
            changed = previous is None or previous["email"] != email or not await asyncio.to_thread(
                verify_password, previous["password_hash"] if previous else None, password,
            ) or previous["disabled"]
            encoded = await asyncio.to_thread(_PASSWORDS.hash, password) if changed else previous["password_hash"]
            if previous is None:
                await conn.execute(
                    "INSERT INTO platform_users(id,name,email,password_hash,email_verified,is_developer,professional_verified,roles,plan,active_selection_initialized) "
                    "VALUES($1,$2,$3,$4,true,true,true,'[\"USER\",\"PROFESSIONAL\",\"REVIEWER\"]','PRO',true)",
                    developer_id, self.settings.admin_name, email, encoded,
                )
            else:
                await conn.execute(
                    "UPDATE platform_users SET name=$2,email=$3,password_hash=$4,email_verified=true,disabled=false,"
                    "roles='[\"USER\",\"PROFESSIONAL\",\"REVIEWER\"]',plan='PRO',plan_expires_at=NULL,"
                    "professional_verified=true,active_selection_initialized=true,auth_revision=auth_revision+$5 WHERE id=$1",
                    developer_id, self.settings.admin_name, email, encoded, int(changed),
                )
            if changed:
                await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", developer_id)
                await self.audit(conn, developer_id, "developer.credentials.synchronized", developer_id)

    def require_mail(self):
        s = self.settings
        if not s.smtp_host or not s.smtp_from or (s.smtp_ssl and s.smtp_starttls):
            raise PlatformError(503, "Email delivery is not configured; retry after SMTP setup")
        if s.smtp_username and not (s.smtp_ssl or s.smtp_starttls):
            raise PlatformError(503, "Authenticated email delivery requires TLS")

    def _send_code(self, email: str, purpose: str, code: str):
        s = self.settings
        message = EmailMessage()
        message["From"], message["To"] = s.smtp_from, email
        message["Subject"] = "MarketGraph account verification" if purpose in {"verify", "attach"} else "MarketGraph password recovery"
        message.set_content(
            f"Your single-use MarketGraph {purpose} code is:\n\n{code}\n\n"
            f"It expires in {s.auth_code_ttl_seconds // 60} minutes. If you did not request this, ignore this message."
        )
        cls = smtplib.SMTP_SSL if s.smtp_ssl else smtplib.SMTP
        options = {"timeout": s.smtp_timeout_seconds}
        if s.smtp_ssl:
            options["context"] = ssl.create_default_context()
        with cls(s.smtp_host, s.smtp_port, **options) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(message)

    async def throttle(self, action: str, email: str, address: str, *, email_limit: int = 5, ip_limit: int = 20):
        for category, identity, limit in (("email", email, email_limit), ("ip", address, ip_limit)):
            key = token_digest(f"{action}:{category}:{identity}")
            count = await self.pool.fetchval(
                "INSERT INTO platform_auth_rate_buckets(key,bucket,count) VALUES($1,floor(extract(epoch from now())/60)::bigint,1) "
                "ON CONFLICT(key,bucket) DO UPDATE SET count=platform_auth_rate_buckets.count+1 RETURNING count", key,
            )
            if count > limit:
                raise PlatformError(429, "Authentication request limit exceeded; retry later")

    async def issue_challenge(self, user_id: UUID, email: str, purpose: str, pending_password_hash: str | None = None):
        code, challenge_id = secrets.token_urlsafe(32), uuid4()
        async with self.pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", user_id)
            if owner is None or owner["disabled"] or owner["is_developer"]:
                return False
            if purpose == "attach" and (owner["email"] or owner["password_hash"]):
                raise PlatformError(409, "Account credentials already exist")
            recent = await conn.fetchval(
                "SELECT id FROM platform_auth_challenges WHERE user_id=$1 AND purpose=$2 "
                "AND created_at>now()-make_interval(secs=>$3) LIMIT 1", user_id, purpose, self.settings.auth_resend_seconds,
            )
            if recent:
                return False
            await conn.execute("UPDATE platform_auth_challenges SET consumed_at=now() WHERE user_id=$1 AND purpose=$2 AND consumed_at IS NULL", user_id, purpose)
            await conn.execute(
                "INSERT INTO platform_auth_challenges(id,user_id,email,purpose,digest,pending_password_hash,expires_at) "
                "VALUES($1,$2,$3,$4,$5,$6,now()+make_interval(secs=>$7))",
                challenge_id, user_id, email, purpose, token_digest(code), pending_password_hash, self.settings.auth_code_ttl_seconds,
            )
        try:
            await asyncio.to_thread(self._send_code, email, purpose, code)
        except (OSError, smtplib.SMTPException):
            await self.pool.execute("UPDATE platform_auth_challenges SET consumed_at=now() WHERE id=$1", challenge_id)
            raise PlatformError(503, "Email delivery unavailable; retry sending a new code") from None
        return True

    async def signup(self, email: str, name: str, password: str, address: str):
        self.require_mail()
        await self.throttle("signup", email, address, email_limit=2, ip_limit=10)
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO platform_users(id,name,email,password_hash) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING *",
                uuid4(), name, email, encoded,
            )
            if row is None:
                row = await conn.fetchrow("SELECT * FROM platform_users WHERE lower(email)=$1", email)
        if row and not row["email_verified"] and not row["disabled"] and not row["is_developer"]:
            try:
                await self.issue_challenge(row["id"], email, "verify")
            except PlatformError as exc:
                if exc.status != 503:
                    raise
                # A configured SMTP transport failing for an existing address must
                # not turn the public generic response into an account oracle.
        return {"detail": "If this address is eligible, a verification code has been sent"}

    async def request_code(self, email: str, purpose: str, address: str):
        self.require_mail()
        await self.throttle(purpose + "-request", email, address, email_limit=1, ip_limit=10)
        row = await self.pool.fetchrow("SELECT * FROM platform_users WHERE lower(email)=$1", email)
        eligible = row and not row["is_developer"] and not row["disabled"]
        if eligible and ((purpose == "verify" and not row["email_verified"]) or (purpose == "reset" and row["email_verified"])):
            try:
                await self.issue_challenge(row["id"], email, purpose)
            except PlatformError as exc:
                if exc.status != 503:
                    raise
                # Preserve indistinguishable recovery responses on mail outages.
        return {"detail": "If this address is eligible, an account code has been sent"}

    async def consume_code(self, email: str, purpose: str, code: str, address: str, password: str | None = None):
        await self.throttle(purpose + "-verify", email, address, email_limit=10, ip_limit=30)
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password) if password is not None else None
        success = False
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM platform_auth_challenges WHERE email=$1 AND purpose=$2 AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
                    email, purpose,
                )
                user = None
                if row:
                    # Match issuance/password-change lock ordering: user before challenge.
                    user = await conn.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", row["user_id"])
                    row = await conn.fetchrow("SELECT * FROM platform_auth_challenges WHERE id=$1 FOR UPDATE", row["id"])
                if row and row["consumed_at"] is None and row["expires_at"] > datetime.now(UTC) and row["attempts"] < self.settings.auth_code_max_attempts:
                    # Raise after committing this transaction so failed attempts persist.
                    await conn.execute("UPDATE platform_auth_challenges SET attempts=attempts+1 WHERE id=$1", row["id"])
                    if hmac.compare_digest(row["digest"], token_digest(code)):
                        if user and not user["disabled"] and not user["is_developer"]:
                            if purpose == "verify" and user["email"] == email and encoded and not user["email_verified"]:
                                # Mailbox proof activates the password selected by
                                # its owner, never an attacker's pre-registration.
                                await conn.execute(
                                    "UPDATE platform_users SET password_hash=$2,email_verified=true,auth_revision=auth_revision+1 WHERE id=$1",
                                    user["id"], encoded,
                                )
                                success = True
                            elif purpose == "reset" and user["email"] == email and encoded and user["email_verified"]:
                                await conn.execute("UPDATE platform_users SET password_hash=$2,auth_revision=auth_revision+1 WHERE id=$1", user["id"], encoded)
                                success = True
                            elif purpose == "attach" and row["pending_password_hash"] and user["email"] is None and user["password_hash"] is None:
                                conflict = await conn.fetchval("SELECT id FROM platform_users WHERE lower(email)=$1 AND id<>$2", email, user["id"])
                                if conflict is None:
                                    await conn.execute(
                                        "UPDATE platform_users SET email=$2,password_hash=$3,email_verified=true,auth_revision=auth_revision+1 WHERE id=$1",
                                        user["id"], email, row["pending_password_hash"],
                                    )
                                    success = True
                            if success:
                                await conn.execute("UPDATE platform_auth_challenges SET consumed_at=now(),pending_password_hash=NULL WHERE user_id=$1", user["id"])
                                if purpose in {"verify", "reset", "attach"}:
                                    await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user["id"])
        except UniqueViolationError:
            raise PlatformError(409, "Email is unavailable; request a new account code") from None
        if not success:
            raise PlatformError(400, "Invalid or expired account code")
        return {"detail": "Email verified" if purpose == "verify" else "Credentials updated; log in again"}

    async def login(self, email: str, password: str, address: str):
        await self.throttle("login", email, address, email_limit=10, ip_limit=30)
        row = await self.pool.fetchrow("SELECT * FROM platform_users WHERE lower(email)=$1", email)
        valid = await asyncio.to_thread(verify_password, row["password_hash"] if row else None, password)
        if not valid or row is None or row["disabled"]:
            raise PlatformError(401, "Invalid login credentials")
        if row["is_developer"] and (not self.settings.admin_password.get_secret_value() or email != self.settings.admin_email.strip().casefold()):
            raise PlatformError(401, "Invalid login credentials")
        if not row["email_verified"]:
            raise PlatformError(403, "Verify your email before logging in")
        token, digest = issue_token()
        async with self.pool.acquire() as conn, conn.transaction():
            current = await conn.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", row["id"])
            if current["disabled"] or current["password_hash"] != row["password_hash"]:
                raise PlatformError(401, "Invalid login credentials")
            if _PASSWORDS.check_needs_rehash(current["password_hash"]):
                encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
                await conn.execute("UPDATE platform_users SET password_hash=$2 WHERE id=$1", row["id"], encoded)
            expires = await conn.fetchval(
                "INSERT INTO platform_tokens(id,user_id,digest,expires_at) VALUES($1,$2,$3,now()+make_interval(secs=>$4)) RETURNING expires_at",
                uuid4(), row["id"], digest, self.settings.session_ttl_seconds,
            )
        return {"access_token": token, "token_type": "bearer", "expires_at": expires, "user": profile(current)}

    async def logout(self, digest: str):
        await self.pool.execute("UPDATE platform_tokens SET revoked_at=now() WHERE digest=$1 AND revoked_at IS NULL", digest)
        return {"detail": "Session revoked"}

    async def attach_credentials(self, user: Principal, email: str, password: str, address: str):
        if user.is_developer:
            raise PlatformError(403, "Developer credentials are managed through environment configuration")
        self.require_mail()
        await self.throttle("attach", email, address, email_limit=1, ip_limit=10)
        existing = await self.pool.fetchrow("SELECT email,password_hash FROM platform_users WHERE id=$1", user.id)
        if existing["email"] or existing["password_hash"]:
            raise PlatformError(409, "Account credentials already exist")
        if await self.pool.fetchval("SELECT id FROM platform_users WHERE lower(email)=$1", email):
            raise PlatformError(409, "Email is unavailable")
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
        await self.issue_challenge(user.id, email, "attach", encoded)
        return {"detail": "Verification code sent; verify it to activate these credentials"}

    async def change_password(self, user: Principal, current_password: str, password: str):
        if user.is_developer:
            raise PlatformError(403, "Developer credentials are managed through environment configuration")
        previous = await self.pool.fetchrow("SELECT password_hash FROM platform_users WHERE id=$1", user.id)
        if not previous or not await asyncio.to_thread(verify_password, previous["password_hash"], current_password):
            raise PlatformError(401, "Invalid current password")
        encoded = await asyncio.to_thread(_PASSWORDS.hash, password)
        async with self.pool.acquire() as conn, conn.transaction():
            current = await conn.fetchrow("SELECT password_hash FROM platform_users WHERE id=$1 FOR UPDATE", user.id)
            if current["password_hash"] != previous["password_hash"]:
                raise PlatformError(409, "Credentials changed; log in again")
            await conn.execute("UPDATE platform_users SET password_hash=$2,auth_revision=auth_revision+1 WHERE id=$1", user.id, encoded)
            await conn.execute("UPDATE platform_auth_challenges SET consumed_at=now(),pending_password_hash=NULL WHERE user_id=$1", user.id)
            await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user.id)
        return {"detail": "Password changed; log in again"}

    async def list_users(self, limit: int, offset: int):
        rows = await self.pool.fetch(f"SELECT {PROFILE_COLUMNS} FROM platform_users ORDER BY created_at,id LIMIT $1 OFFSET $2", limit, offset)
        return {"items": [profile(row) for row in rows], "limit": limit, "offset": offset}

    async def user_detail(self, user_id: UUID):
        row = await self.pool.fetchrow(f"SELECT {PROFILE_COLUMNS} FROM platform_users WHERE id=$1", user_id)
        if row is None:
            raise PlatformError(404, "Unknown user")
        return profile(row)

    async def update_user(self, actor: Principal, user_id: UUID, changes: dict):
        if not actor.is_developer:
            raise PlatformError(403, "Developer access required")
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", user_id)
            if row is None:
                raise PlatformError(404, "Unknown user")
            if row["is_developer"]:
                raise PlatformError(403, "Developer identity is managed through environment configuration")
            previous_roles = json.loads(row["roles"]) if isinstance(row["roles"], str) else row["roles"]
            roles = set(changes.get("roles", previous_roles)) | {"USER"}
            verified = changes.get("professional_verified", "PROFESSIONAL" in roles)
            if verified:
                roles.add("PROFESSIONAL")
            else:
                roles.discard("PROFESSIONAL")
            plan = changes.get("plan", row["plan"])
            expires = changes.get("plan_expires_at", None if "plan" in changes else row["plan_expires_at"])
            if plan == "FREE":
                expires = None
            disabled = changes.get("disabled", row["disabled"])
            verification_changed = bool(verified) != row["professional_verified"]
            updated = await conn.fetchrow(
                f"UPDATE platform_users SET name=$2,roles=$3::jsonb,professional_verified=$4,plan=$5,plan_expires_at=$6,disabled=$7,"
                f"verification_revision=verification_revision+$8 WHERE id=$1 RETURNING {PROFILE_COLUMNS}",
                user_id, changes.get("name", row["name"]), json.dumps(sorted(roles)), verified, plan, expires, disabled, int(verification_changed),
            )
            if verification_changed:
                await self.repository._event(conn, row, "professional.author-status", {"author_id": str(user_id), "verified": verified}, row["verification_revision"] + 1)
            if disabled:
                await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id)
            if disabled or (row["plan"] == "PRO" and plan == "FREE"):
                await conn.execute(
                    "UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,finished_at=now(),error='Account access changed' "
                    "WHERE user_id=$1 AND state IN ('pending','running')", user_id,
                )
            await self.audit(conn, actor.id, "user.updated", user_id, {key: value for key, value in changes.items()})
        return profile(updated)

    async def revoke_sessions(self, actor: Principal, user_id: UUID):
        if not actor.is_developer:
            raise PlatformError(403, "Developer access required")
        async with self.pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval("SELECT id FROM platform_users WHERE id=$1 FOR UPDATE", user_id):
                raise PlatformError(404, "Unknown user")
            await conn.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id)
            await self.audit(conn, actor.id, "user.sessions.revoked", user_id)
        return {"detail": "All user sessions and legacy tokens revoked"}
