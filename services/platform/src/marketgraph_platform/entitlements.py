"""Database-backed authorization snapshots and serialized account selections."""
import json
from dataclasses import dataclass
from uuid import UUID

from marketgraph_platform.models import Principal
from marketgraph_platform.policy import access_policy, effective_plan
from marketgraph_platform.repository import PlatformError

USER_FIELDS = "id,name,email,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class Access:
    user: Principal
    policy: dict
    tickers: tuple[str, ...]

    @property
    def developer(self):
        return self.user.is_developer

    @property
    def pro(self):
        return effective_plan(self.user) == "PRO"

    def allows(self, feature):
        return self.developer or bool(decode(self.policy["features"]).get(feature, False))

    def require(self, feature=None, tickers=(), single=False):
        if self.user.disabled:
            raise PlatformError(403, "Account is disabled")
        if feature and not self.allows(feature):
            raise PlatformError(403, "Feature requires Pro access: " + feature)
        limit = self.policy.get("active_stock_limit")
        if not self.developer and limit is not None and len(self.tickers) > limit:
            raise PlatformError(403, f"Reduce active stocks to the configured limit of {limit}")
        if not self.developer and not self.pro:
            if single and len(tickers) != 1:
                raise PlatformError(403, "Free research requires exactly one active stock")
            if tickers and (not self.user.active_selection_initialized or set(tickers) - set(self.tickers)):
                raise PlatformError(403, "Select these stocks in your active-stock selection first")
        return self

    def require_job(self, job):
        kind, payload = job["kind"], decode(job["input"])
        feature = "discovery" if kind == "discovery" else (
            "market_monitoring" if payload.get("scope") == "market" else
            "monitoring" if kind == "monitor" else "research_chat"
        )
        self.require(feature, payload.get("tickers", []), single=kind == "chat")
        if job.get("required_plan") == "PRO" and not self.pro and not self.developer:
            raise PlatformError(403, "This job requires Pro access")
        return self


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


class Entitlements:
    def __init__(self, repository):
        self.repository = repository

    async def access(self, user_id):
        return await load_access(self.repository.pool, user_id)

    async def check(self, user, feature=None, tickers=(), single=False):
        return (await self.access(user.id)).require(feature, tickers, single)

    async def selection(self, user):
        access = await self.access(user.id)
        return {"tickers": access.tickers, "initialized": access.user.active_selection_initialized,
                "access": access_policy(access.user, access.policy)}

    async def select(self, user, tickers):
        async with self.repository.pool.acquire() as conn, conn.transaction():
            access = await load_access(conn, user.id, lock=True)
            access.require()
            limit = access.policy["active_stock_limit"]
            if not access.developer and limit is not None and len(tickers) > limit:
                raise PlatformError(403, f"Active-stock limit is {limit}")
            await conn.execute("DELETE FROM platform_active_stocks WHERE user_id=$1", user.id)
            for ticker in tickers:
                await conn.execute("INSERT INTO platform_active_stocks(user_id,ticker) VALUES($1,$2)", user.id, ticker)
            await conn.execute("UPDATE platform_users SET active_selection_initialized=true WHERE id=$1", user.id)
            # Any leased context may no longer be authorized. Re-submit under the new selection.
            await conn.execute(
                "UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,finished_at=now(),"
                "error='Stock selection changed; resubmit' WHERE user_id=$1 AND state IN ('pending','running')",
                user.id)
            await conn.execute("UPDATE monitors SET pause_reason=NULL WHERE user_id=$1", user.id)
        return await self.selection(user)

    async def usage(self, user):
        access = await self.access(user.id)
        used = await self.repository.pool.fetchval(
            "SELECT count(*) FROM opportunity_alerts WHERE user_id=$1 AND created_at>="
            "(date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata')", user.id)
        reset = await self.repository.pool.fetchval(
            "SELECT (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata')+interval '1 month') AT TIME ZONE 'Asia/Kolkata'")
        return {"items": await self.repository.usage(user.id), "active_stocks": len(access.tickers),
                "opportunity_alerts_this_month": used, "resets_at": reset,
                "access": access_policy(access.user, access.policy)}

