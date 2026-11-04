"""Transactional application records and durable, at-least-once graph publication."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

import asyncpg

from marketgraph_platform.models import ContributionInput, Principal
from marketgraph_platform.settings import Settings


class PlatformError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            self.settings.database_dsn.get_secret_value(), min_size=1,
            max_size=self.settings.db_pool_size, command_timeout=30,
        )
        await self.migrate()

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def migrate(self):
        async with self.pool.acquire() as con, con.transaction():
            await con.execute("SELECT pg_advisory_xact_lock(780436152)")
            await con.execute("""CREATE TABLE IF NOT EXISTS platform_schema_migrations(
                name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())""")
            for path in sorted(files("marketgraph_platform").joinpath("migrations").iterdir(), key=lambda x: x.name):
                if not path.name.endswith(".sql"):
                    continue
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                previous = await con.fetchval("SELECT checksum FROM platform_schema_migrations WHERE name=$1", path.name)
                if previous is not None:
                    if previous != checksum:
                        raise RuntimeError(f"Applied migration changed: {path.name}")
                    continue
                await con.execute(sql)
                await con.execute("INSERT INTO platform_schema_migrations(name,checksum) VALUES($1,$2)", path.name, checksum)

    async def provision_user(self, name: str, digest: str, professional_verified: bool = False) -> UUID:
        user_id = uuid4()
        async with self.pool.acquire() as con, con.transaction():
            await con.execute("INSERT INTO platform_users(id,name,professional_verified,roles) VALUES($1,$2,$3,$4::jsonb)",
                              user_id, name, professional_verified,
                              json.dumps(["USER", "PROFESSIONAL"] if professional_verified else ["USER"]))
            await con.execute("INSERT INTO platform_tokens(id,user_id,digest) VALUES($1,$2,$3)", uuid4(), user_id, digest)
        return user_id

    async def authenticate(self, digest: str):
        row = await self.pool.fetchrow("""SELECT u.id,u.name,u.email,u.professional_verified,
            u.is_developer,u.disabled,u.roles,u.plan,u.plan_expires_at,u.active_selection_initialized
            FROM platform_users u JOIN platform_tokens t ON t.user_id=u.id
            WHERE t.digest=$1 AND t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>now())""", digest)
        return {**dict(row), "roles": json_value(row["roles"])} if row else None

    async def rotate_token(self, user_id: UUID, digest: str):
        async with self.pool.acquire() as con, con.transaction():
            if not await con.fetchval("SELECT id FROM platform_users WHERE id=$1 FOR UPDATE", user_id):
                raise PlatformError(404, "Unknown user")
            await con.execute("UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id)
            await con.execute("INSERT INTO platform_tokens(id,user_id,digest) VALUES($1,$2,$3)", uuid4(), user_id, digest)

    async def set_verified(self, user_id: UUID, verified: bool):
        async with self.pool.acquire() as con, con.transaction():
            previous = await con.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", user_id)
            if previous is None:
                raise PlatformError(404, "Unknown user")
            if previous["professional_verified"] == verified:
                return
            revision = await con.fetchval("""UPDATE platform_users SET professional_verified=$2,
                roles=CASE WHEN $2 THEN CASE WHEN roles ? 'PROFESSIONAL' THEN roles
                ELSE roles || '["PROFESSIONAL"]'::jsonb END ELSE roles - 'PROFESSIONAL' END,
                verification_revision=verification_revision+1 WHERE id=$1 RETURNING verification_revision""", user_id, verified)
            await self._event(con, previous, "professional.author-status",
                              {"author_id": str(user_id), "verified": verified}, revision)

    async def allow_request(self, user_id: UUID) -> bool:
        # Atomic counter, shared by API replicas; this is operational load protection.
        count = await self.pool.fetchval("""INSERT INTO platform_request_buckets(user_id,bucket,count)
            VALUES($1,floor(extract(epoch from now())/60)::bigint,1)
            ON CONFLICT(user_id,bucket) DO UPDATE SET count=platform_request_buckets.count+1 RETURNING count""", user_id)
        return count <= self.settings.operational_requests_per_minute

    async def measure(self, user_id: UUID, feature: str, units: int = 1):
        await self.pool.execute("""INSERT INTO platform_usage(user_id,feature,month,units)
            VALUES($1,$2,date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata')::date,$3)
            ON CONFLICT(user_id,feature,month) DO UPDATE SET units=platform_usage.units+EXCLUDED.units""", user_id, feature, units)

    async def usage(self, user_id: UUID):
        rows = await self.pool.fetch("""SELECT feature,month,units FROM platform_usage WHERE user_id=$1
            UNION ALL SELECT metric AS feature,date_trunc('month',created_at AT TIME ZONE 'Asia/Kolkata')::date AS month,
            sum(amount)::bigint AS units FROM agent_usage WHERE user_id=$1 GROUP BY metric,month
            ORDER BY month DESC,feature LIMIT 200""", user_id)
        return [dict(row) for row in rows]

    async def _locked(self, con, contribution_id: UUID, user: Principal | None, expected_revision: int):
        row = await con.fetchrow("SELECT * FROM platform_contributions WHERE id=$1 FOR UPDATE", contribution_id)
        if row is None or (user is not None and not user.is_developer and row["author_id"] != user.id):
            raise PlatformError(404, "Contribution not found")
        if row["revision"] != expected_revision:
            raise PlatformError(409, "Contribution changed; reload its revision")
        if user is not None and user.is_developer:
            await self.audit_developer(con, user.id, "contribution.mutate", row["author_id"])
        return row

    async def audit_developer(self, con, actor_id, action, target_id=None):
        await con.execute(
            "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) VALUES($1,$2,$3,'{}')",
            actor_id, target_id, action)

    async def _insert_version(self, con, contribution_id: UUID, data: ContributionInput, number: int):
        version_id = uuid4()
        await con.execute("""INSERT INTO platform_contribution_versions(
            id,contribution_id,version_number,ticker,content,event_at,expires_at) VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)""",
            version_id, contribution_id, number, data.ticker,
            data.model_dump_json(), data.event_at, data.expires_at)
        return version_id

    async def create_contribution(self, user: Principal, data: ContributionInput, request_key: str | None = None):
        contribution_id, initial_version = uuid4(), uuid4()
        request_key = request_key or str(uuid4())
        fingerprint = hashlib.sha256(json.dumps(data.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        async with self.pool.acquire() as con, con.transaction():
            await con.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"{user.id}:{request_key}")
            previous = await con.fetchrow("SELECT * FROM platform_contribution_requests WHERE user_id=$1 AND request_key=$2", user.id, request_key)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise PlatformError(409, "Idempotency key was already used for different content")
                contribution_id = previous["contribution_id"]
            else:
                # Both FK directions are checked at transaction commit.
                await con.execute("""INSERT INTO platform_contributions(id,author_id,status,current_version_id)
                    VALUES($1,$2,'DRAFT',$3)""", contribution_id, user.id, initial_version)
                await con.execute("""INSERT INTO platform_contribution_versions(
                    id,contribution_id,version_number,ticker,content,event_at,expires_at)
                    VALUES($1,$2,1,$3,$4::jsonb,$5,$6)""", initial_version, contribution_id,
                    data.ticker, data.model_dump_json(), data.event_at, data.expires_at)
                await con.execute("""INSERT INTO platform_contribution_requests(user_id,request_key,fingerprint,contribution_id)
                    VALUES($1,$2,$3,$4)""", user.id, request_key, fingerprint, contribution_id)
        return await self.detail(contribution_id, user)

    async def add_version(self, contribution_id: UUID, user: Principal, data: ContributionInput, expected_revision: int):
        async with self.pool.acquire() as con, con.transaction():
            row = await self._locked(con, contribution_id, user, expected_revision)
            if row["status"] in ("SUBMITTED", "RETRACTED"):
                raise PlatformError(409, "Submitted or retracted contributions cannot be edited")
            number = await con.fetchval("SELECT max(version_number)+1 FROM platform_contribution_versions WHERE contribution_id=$1", contribution_id)
            version_id = await self._insert_version(con, contribution_id, data, number)
            await con.execute("""UPDATE platform_contributions SET current_version_id=$2,status='DRAFT',
                revision=revision+1,updated_at=now() WHERE id=$1""", contribution_id, version_id)
        return await self.detail(contribution_id, user)

    async def detail(self, contribution_id: UUID, user: Principal):
        # Drafts/review material stay private to their author. Reviewers use the submitted queue.
        row = await self.pool.fetchrow("SELECT * FROM platform_contributions WHERE id=$1 AND (author_id=$2 OR $3)",
                                       contribution_id, user.id, user.is_developer)
        if not row:
            raise PlatformError(404, "Contribution not found")
        if user.is_developer:
            await self.audit_developer(self.pool, user.id, "contribution.read", row["author_id"])
        versions = await self.pool.fetch("""SELECT v.*,s.submitted_at,p.published_at FROM platform_contribution_versions v
            LEFT JOIN platform_submissions s ON s.version_id=v.id LEFT JOIN platform_publications p ON p.version_id=v.id
            WHERE v.contribution_id=$1 ORDER BY version_number""", contribution_id)
        reviews = await self.pool.fetch("""SELECT r.* FROM platform_reviews r JOIN platform_contribution_versions v ON v.id=r.version_id
            WHERE v.contribution_id=$1 ORDER BY r.reviewed_at""", contribution_id)
        return {**dict(row), "versions": [{**dict(v), "content": json_value(v["content"])} for v in versions],
                "reviews": [dict(r) for r in reviews]}

    async def list_mine(self, user: Principal):
        rows = await self.pool.fetch("SELECT * FROM platform_contributions WHERE author_id=$1 OR $2 ORDER BY updated_at DESC LIMIT 200", user.id, user.is_developer)
        return [dict(row) for row in rows]

    async def submit(self, contribution_id: UUID, user: Principal, expected_revision: int):
        async with self.pool.acquire() as con, con.transaction():
            row = await self._locked(con, contribution_id, user, expected_revision)
            if row["status"] != "DRAFT":
                raise PlatformError(409, "Only a draft can be submitted")
            version = await con.fetchrow("SELECT * FROM platform_contribution_versions WHERE id=$1", row["current_version_id"])
            if version["expires_at"] <= datetime.now(UTC):
                raise PlatformError(422, "Cannot submit expired evidence")
            await con.execute("INSERT INTO platform_submissions(version_id) VALUES($1)", version["id"])
            await con.execute("UPDATE platform_contributions SET status='SUBMITTED',revision=revision+1,updated_at=now() WHERE id=$1", contribution_id)
        return await self.detail(contribution_id, user)

    async def review_queue(self, user: Principal):
        rows = await self.pool.fetch("""SELECT c.id,c.revision,c.author_id,u.name AS author_name,u.professional_verified,
            v.id AS version_id,v.content,v.known_at,s.submitted_at FROM platform_contributions c
            JOIN platform_users u ON u.id=c.author_id JOIN platform_contribution_versions v ON v.id=c.current_version_id
            JOIN platform_submissions s ON s.version_id=v.id WHERE c.status='SUBMITTED' AND (c.author_id<>$1 OR $2)
            ORDER BY s.submitted_at LIMIT 100""", user.id, user.is_developer)
        return [{**dict(row), "content": json_value(row["content"])} for row in rows]

    async def _event(self, con, row, kind: str, payload: dict, revision: int):
        event_id = uuid4()
        event = {"schema_version": 1, "event_id": str(event_id), "kind": kind,
                 "entity_id": str(row["id"]), "revision": revision,
                 "occurred_at": datetime.now(UTC).isoformat(), "payload": payload}
        await con.execute("INSERT INTO platform_outbox(event_id,event) VALUES($1,$2::jsonb)", event_id, json.dumps(event, default=str))

    async def review(self, contribution_id: UUID, user: Principal, expected_revision: int, decision: str, reason: str):
        async with self.pool.acquire() as con, con.transaction():
            row = await self._locked(con, contribution_id, None, expected_revision)
            if row["author_id"] == user.id and not user.is_developer:
                raise PlatformError(403, "Independent review requires a different person")
            if row["status"] != "SUBMITTED":
                raise PlatformError(409, "Contribution is not awaiting review")
            version = await con.fetchrow("SELECT * FROM platform_contribution_versions WHERE id=$1", row["current_version_id"])
            author = await con.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR SHARE", row["author_id"])
            if decision == "APPROVE" and not author["professional_verified"] and not user.is_developer:
                raise PlatformError(409, "Professional credentials must be verified before publication")
            now = datetime.now(UTC)
            if decision == "APPROVE" and version["expires_at"] <= now:
                raise PlatformError(422, "Cannot approve expired evidence")
            if user.is_developer:
                await self.audit_developer(con, user.id, "contribution.review-override", row["author_id"])
            await con.execute("""INSERT INTO platform_reviews(id,version_id,reviewer_id,decision,reason)
                VALUES($1,$2,$3,$4,$5)""", uuid4(), version["id"], user.id, decision, reason)
            status = "PUBLISHED" if decision == "APPROVE" else "REJECTED"
            await con.execute("UPDATE platform_contributions SET status=$2,revision=revision+1,updated_at=now() WHERE id=$1", contribution_id, status)
            if decision == "APPROVE":
                await con.execute("INSERT INTO platform_publications(version_id,published_at) VALUES($1,$2)", version["id"], now)
                await con.execute("UPDATE platform_contributions SET published_version_id=$2 WHERE id=$1", contribution_id, version["id"])
                content = json_value(version["content"])
                payload = {**content, "contribution_id": str(contribution_id), "version_id": str(version["id"]),
                           "author_id": str(author["id"]), "author_name": author["name"],
                           "published_at": now.isoformat(), "known_at": version["known_at"].isoformat(), "future_access": "PRO"}
                await self._event(con, row, "professional.published", payload, row["revision"] + 1)
        return {"id": contribution_id, "version_id": version["id"], "status": status, "revision": row["revision"] + 1}

    async def retract(self, contribution_id: UUID, user: Principal, expected_revision: int, reason: str):
        async with self.pool.acquire() as con, con.transaction():
            row = await self._locked(con, contribution_id, user, expected_revision)
            if row["published_version_id"] is None or row["retracted_at"] is not None:
                raise PlatformError(409, "Only a published contribution can be retracted")
            version = await con.fetchrow("SELECT * FROM platform_contribution_versions WHERE id=$1", row["published_version_id"])
            await con.execute("""INSERT INTO platform_retractions(id,contribution_id,actor_id,version_id,reason)
                VALUES($1,$2,$3,$4,$5)""", uuid4(), contribution_id, user.id, version["id"], reason)
            await con.execute("UPDATE platform_contributions SET status='RETRACTED',retracted_at=now(),revision=revision+1,updated_at=now() WHERE id=$1", contribution_id)
            await self._event(con, row, "professional.retracted", {"contribution_id": str(contribution_id),
                "version_id": str(version["id"]), "ticker": version["ticker"], "reason": reason}, row["revision"] + 1)
        return {"id": contribution_id, "status": "RETRACTED", "revision": row["revision"] + 1}

    async def published(self, ticker: str, limit: int = 50, offset: int = 0):
        rows = await self.pool.fetch("""SELECT c.id,c.revision,u.id AS author_id,u.name AS author_name,
            u.professional_verified,v.id AS version_id,v.content,v.known_at,p.published_at
            FROM platform_contributions c JOIN platform_contribution_versions v ON v.id=c.published_version_id
            JOIN platform_users u ON u.id=c.author_id JOIN platform_publications p ON p.version_id=v.id
            WHERE v.ticker=$1 AND c.retracted_at IS NULL AND v.expires_at>now()
            ORDER BY p.published_at DESC,c.id LIMIT $2 OFFSET $3""", ticker, limit, offset)
        return [{**dict(row), "content": json_value(row["content"]), "future_access": "PRO",
                 "weight": self.settings.professional_weight if row["professional_verified"] else self.settings.ordinary_weight,
                 "weight_policy_version": "professional-priority-v1", "contradictions_retained": True} for row in rows]

    async def claim_outbox(self):
        lease_id = uuid4()
        rows = await self.pool.fetch("""WITH candidates AS (
            SELECT event_id FROM platform_outbox WHERE published_at IS NULL AND next_attempt_at<=now()
            AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at,event_id
            FOR UPDATE SKIP LOCKED LIMIT $1)
            UPDATE platform_outbox o SET lease_id=$2,lease_until=now()+$3*interval '1 second',attempts=o.attempts+1
            FROM candidates c WHERE o.event_id=c.event_id RETURNING o.event_id,o.event,o.lease_id,o.attempts""",
            self.settings.outbox_batch_size, lease_id, self.settings.outbox_lease_seconds)
        return [{**dict(row), "event": json_value(row["event"])} for row in rows]

    async def finish_outbox(self, event_id: UUID, lease_id: UUID):
        await self.pool.execute("""UPDATE platform_outbox SET published_at=now(),lease_id=NULL,lease_until=NULL,error=NULL
            WHERE event_id=$1 AND lease_id=$2""", event_id, lease_id)

    async def retry_outbox(self, event_id: UUID, lease_id: UUID, attempts: int):
        await self.pool.execute("""UPDATE platform_outbox SET lease_id=NULL,lease_until=NULL,error='Transport unavailable',
            next_attempt_at=now()+$3*interval '1 second' WHERE event_id=$1 AND lease_id=$2""", event_id, lease_id, min(300, 2 ** min(attempts, 8)))

    async def housekeeping(self):
        await self.pool.execute("DELETE FROM platform_request_buckets WHERE bucket<floor(extract(epoch from now())/60)::bigint-2")
        await self.pool.execute("DELETE FROM platform_auth_rate_buckets WHERE bucket<floor(extract(epoch from now())/60)::bigint-1440")
