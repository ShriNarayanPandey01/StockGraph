"""Database-backed authorization snapshots and serialized account selections."""
import json
from uuid import UUID

from marketgraph_platform.application.ports import AccessRepositoryPort
from marketgraph_platform.domain.access import AccessSnapshot
from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import Principal
from marketgraph_platform.policy import access_policy, effective_plan

Access = AccessSnapshot

USER_FIELDS = "id,name,email,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


async def load_access(conn, user_id: UUID, *, lock=False):
    row = await conn.fetchrow(
        f"SELECT {USER_FIELDS} FROM platform_users WHERE id=$1" + (" FOR UPDATE" if lock else ""), user_id)
    if row is None:
        raise PlatformError(403, "Account is unavailable")
    values = dict(row)
    values["roles"] = decode(values["roles"])
    user = Principal.model_validate(values)
    policy = await conn.fetchrow("SELECT * FROM platform_plan_policies WHERE plan=$1", effective_plan(user))
    if policy is None:
        raise PlatformError(503, "Access policy is unavailable")
    stocks = await conn.fetch("SELECT ticker FROM platform_active_stocks WHERE user_id=$1 ORDER BY ticker", user_id)
    return Access(user, dict(policy), tuple(r["ticker"] for r in stocks))


async def audit_admin(conn, actor, action, target=None, details=None):
    await conn.execute(
        "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) VALUES($1,$2,$3,$4::jsonb)",
        actor, target, action, json.dumps(details or {}, default=str))


async def load_job_access(conn, job, *, lock=False):
    owner = await load_access(conn, job["user_id"], lock=lock)
    actor_id = job.get("actor_id")
    if actor_id is None or actor_id == job["user_id"]:
        return owner
    actor = await load_access(conn, actor_id)
    if not actor.developer or actor.user.disabled:
        raise PlatformError(403, "Developer initiator is unavailable")
    return actor


class EntitlementService:
    def __init__(self, repository: AccessRepositoryPort):
        self._repository = repository

    async def access(self, user_id):
        return await self._repository.load_access_snapshot(user_id)

    async def check(self, user, feature=None, tickers=(), single=False):
        return (await self.access(user.id)).require(feature, tickers, single)

    async def selection(self, user):
        access = await self.access(user.id)
        return {"tickers": access.tickers, "initialized": access.user.active_selection_initialized,
                "access": access_policy(access.user, access.policy)}

    async def select(self, user, tickers):
        await self._repository.replace_active_stocks(user.id, tuple(tickers))
        return await self.selection(user)

    async def usage(self, user):
        access = await self.access(user.id)
        summary = await self._repository.usage_summary(user.id)
        return {"items": await self._repository.usage(user.id), "active_stocks": len(access.tickers),
                **summary,
                "access": access_policy(access.user, access.policy)}


Entitlements = EntitlementService

