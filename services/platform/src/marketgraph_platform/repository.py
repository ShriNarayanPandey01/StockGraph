"""Transactional application records and durable, at-least-once graph publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

import asyncpg

from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import ContributionInput, Principal
from marketgraph_platform.settings import Settings


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

    async def health_check(self) -> bool:
        """Check database readiness without exposing the pool to API code."""
        return self.pool is not None and await self.pool.fetchval("SELECT 1") == 1

    async def load_access_snapshot(self, user_id: UUID):
        from marketgraph_platform.entitlements import load_access

        return await load_access(self.pool, user_id)

    async def replace_active_stocks(self, user_id: UUID, tickers: tuple[str, ...]):
        from marketgraph_platform.entitlements import load_access

        async with self.pool.acquire() as conn, conn.transaction():
            access = await load_access(conn, user_id, lock=True)
            access.require()
            limit = access.policy["active_stock_limit"]
            if not access.developer and limit is not None and len(tickers) > limit:
                raise PlatformError(403, f"Active-stock limit is {limit}")
            await conn.execute("DELETE FROM platform_active_stocks WHERE user_id=$1", user_id)
            for ticker in tickers:
                await conn.execute(
                    "INSERT INTO platform_active_stocks(user_id,ticker) VALUES($1,$2)",
                    user_id, ticker,
                )
            await conn.execute(
                "UPDATE platform_users SET active_selection_initialized=true WHERE id=$1", user_id
            )
            # Access changes invalidate pending work while holding the account lock.
            await conn.execute(
                "UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,finished_at=now(),"
                "error='Stock selection changed; resubmit' WHERE user_id=$1 AND state IN ('pending','running')",
                user_id,
            )
            await conn.execute("UPDATE monitors SET pause_reason=NULL WHERE user_id=$1", user_id)

    async def usage_summary(self, user_id: UUID) -> dict:
        used = await self.pool.fetchval(
            "SELECT count(*) FROM opportunity_alerts WHERE user_id=$1 AND created_at >= "
            "(date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata')",
            user_id,
        )
        reset = await self.pool.fetchval(
            "SELECT (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata')+interval '1 month') "
            "AT TIME ZONE 'Asia/Kolkata'"
        )
        return {"opportunity_alerts_this_month": used, "resets_at": reset}

    async def broker_status(self, user_id: UUID) -> dict:
        row = await self.pool.fetchrow(
            "SELECT status,revision,validated_at FROM platform_broker_connections WHERE user_id=$1",
            user_id,
        )
        return dict(row) if row else {
            "status": "disconnected", "revision": 0, "validated_at": None
        }

    async def save_broker_credential(self, user_id: UUID, encrypted: bytes) -> dict:
        async with self.pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchrow(
                "SELECT disabled FROM platform_users WHERE id=$1 FOR UPDATE", user_id
            )
            if owner is None or owner["disabled"]:
                raise PlatformError(403, "Account is unavailable")
            await conn.execute(
                "INSERT INTO platform_broker_connections(user_id,encrypted_token,status,validated_at) "
                "VALUES($1,$2,'connected',now()) ON CONFLICT(user_id) DO UPDATE SET "
                "encrypted_token=EXCLUDED.encrypted_token,revision=platform_broker_connections.revision+1,"
                "status='connected',validated_at=now(),updated_at=now()",
                user_id, encrypted,
            )
        return await self.broker_status(user_id)

    async def read_broker_credential(self, user_id: UUID) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT status,revision,encrypted_token FROM platform_broker_connections WHERE user_id=$1",
            user_id,
        )
        return dict(row) if row else None

    async def disconnect_broker(self, user_id: UUID) -> dict:
        await self.pool.execute(
            "UPDATE platform_broker_connections SET encrypted_token=NULL,revision=revision+1,"
            "status='disconnected',validated_at=NULL,updated_at=now() WHERE user_id=$1", user_id
        )
        return await self.broker_status(user_id)

    async def require_broker_reconnect(self, user_id: UUID, revision: int) -> None:
        await self.pool.execute(
            "UPDATE platform_broker_connections SET status='reconnect_required',updated_at=now() "
            "WHERE user_id=$1 AND revision=$2", user_id, revision
        )

    async def audit_action(self, actor_id: UUID, action: str,
                           target_id: UUID | None = None, details: dict | None = None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) "
                "VALUES($1,$2,$3,$4::jsonb)",
                actor_id, target_id, action, json.dumps(details or {}, default=str),
            )

    async def admin_records(self, owner_id: UUID, resource: str, limit: int, offset: int):
        tables = {
            "watchlists": ("watchlists", "user_id"),
            "conversations": ("conversations", "user_id"),
            "messages": ("research_messages", "user_id"),
            "monitors": ("monitors", "user_id"),
            "jobs": ("agent_jobs", "user_id"),
            "alerts": ("opportunity_alerts", "user_id"),
            "contributions": ("platform_contributions", "author_id"),
        }
        table, column = tables[resource]
        rows = await self.pool.fetch(
            f"SELECT * FROM {table} WHERE {column}=$1 ORDER BY id LIMIT $2 OFFSET $3",
            owner_id, limit, offset,
        )
        return [
            {key: value for key, value in dict(row).items()
             if key not in ("lease_token", "fingerprint", "result_fingerprint")}
            for row in rows
        ]

    async def admin_audit(self, limit: int, offset: int):
        rows = await self.pool.fetch(
            "SELECT * FROM platform_admin_audit ORDER BY id DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
        return [dict(row) for row in rows]

    async def plan_policies(self):
        rows = await self.pool.fetch("SELECT * FROM platform_plan_policies ORDER BY plan")
        return [{**dict(row), "features": json_value(row["features"])} for row in rows]

    async def update_plan_policy(self, plan: str, expected_revision: int,
                                 active_stock_limit: int | None,
                                 monthly_alert_limit: int | None,
                                 features: dict[str, bool], actor_id: UUID):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "UPDATE platform_plan_policies SET active_stock_limit=$2,monthly_alert_limit=$3,features=$4::jsonb,"
                "revision=revision+1 WHERE plan=$1 AND revision=$5 RETURNING *",
                plan, active_stock_limit, monthly_alert_limit, json.dumps(features), expected_revision,
            )
            if row is None:
                raise PlatformError(409, "Plan changed; reload its revision")
            await conn.execute(
                "INSERT INTO platform_admin_audit(actor_id,action,details) VALUES($1,'plan.policy',$2::jsonb)",
                actor_id, json.dumps({"plan": plan, "revision": row["revision"]}),
            )
            return {**dict(row), "features": json_value(row["features"])}

    async def conversation_owner(self, conversation_id: UUID, user: Principal) -> UUID:
        row = await self.pool.fetchrow(
            "SELECT id,user_id FROM conversations WHERE id=$1 AND (user_id=$2 OR $3)",
            conversation_id, user.id, user.is_developer,
        )
        if row is None:
            raise PlatformError(404, "Record not found")
        if user.is_developer:
            await self.audit_action(user.id, "conversations.access", row["user_id"],
                                    {"record_id": str(conversation_id)})
        return row["user_id"]

    async def create_research_job(self, owner_id: UUID, kind: str, payload: dict,
                                  key: str, max_pending: int, actor_id: UUID | None = None):
        from marketgraph_platform.agent_repository import create_job

        return await create_job(self.pool, owner_id, kind, payload, key, max_pending, actor_id)

    async def reserve_tool_call(self, job_id: UUID, lease: UUID, actor: str):
        from marketgraph_platform.agent_repository import reserve_tool_call

        return await reserve_tool_call(self.pool, job_id, lease, actor)

    async def register_evidence(self, job_id: UUID, lease: UUID, entries: list[dict]):
        from marketgraph_platform.agent_repository import register_evidence

        return await register_evidence(self.pool, job_id, lease, entries)

    async def current_professional_evidence(self, version_id: UUID) -> bool:
        return bool(await self.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM platform_contributions c "
            "JOIN platform_contribution_versions v ON v.id=c.published_version_id "
            "JOIN platform_users u ON u.id=c.author_id WHERE v.id=$1 AND c.retracted_at IS NULL "
            "AND v.expires_at>now() AND u.professional_verified=true)",
            version_id,
        ))

    async def schedule_due_monitors(self, settings: Settings) -> None:
        from marketgraph_platform.agent_repository import schedule_due_monitors

        await schedule_due_monitors(self.pool, settings)

    async def count_auth_attempt(self, key: str, limit: int) -> None:
        count = await self.pool.fetchval(
            "INSERT INTO platform_auth_rate_buckets(key,bucket,count) "
            "VALUES($1,floor(extract(epoch from now())/60)::bigint,1) "
            "ON CONFLICT(key,bucket) DO UPDATE SET count=platform_auth_rate_buckets.count+1 RETURNING count",
            key,
        )
        if count > limit:
            raise PlatformError(429, "Authentication request limit exceeded; retry later")

    async def create_account(self, email: str, name: str, password_hash: str) -> None:
        await self.pool.execute(
            "INSERT INTO platform_users(id,name,email,password_hash) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            uuid4(), name, email, password_hash,
        )

    async def login_candidate(self, email: str):
        return await self.pool.fetchrow("SELECT * FROM platform_users WHERE lower(email)=$1", email)

    async def create_login_session(self, user_id: UUID, expected_hash: str,
                                   digest: str, ttl_seconds: int,
                                   replacement_hash: str | None = None):
        async with self.pool.acquire() as conn, conn.transaction():
            current = await conn.fetchrow(
                "SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", user_id
            )
            if (current is None or current["disabled"]
                    or current["password_hash"] != expected_hash):
                raise PlatformError(401, "Invalid login credentials")
            if replacement_hash:
                await conn.execute(
                    "UPDATE platform_users SET password_hash=$2 WHERE id=$1", user_id, replacement_hash
                )
            expires = await conn.fetchval(
                "INSERT INTO platform_tokens(id,user_id,digest,expires_at) "
                "VALUES($1,$2,$3,now()+make_interval(secs=>$4)) RETURNING expires_at",
                uuid4(), user_id, digest, ttl_seconds,
            )
        return current, expires

    async def revoke_session(self, digest: str) -> None:
        await self.pool.execute(
            "UPDATE platform_tokens SET revoked_at=now() WHERE digest=$1 AND revoked_at IS NULL", digest
        )

    async def account_password_hash(self, user_id: UUID):
        row = await self.pool.fetchrow("SELECT password_hash FROM platform_users WHERE id=$1", user_id)
        return row["password_hash"] if row else None

    async def change_account_password(self, user_id: UUID, expected_hash: str,
                                      replacement_hash: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            current = await conn.fetchrow(
                "SELECT password_hash FROM platform_users WHERE id=$1 FOR UPDATE", user_id
            )
            if current is None or current["password_hash"] != expected_hash:
                raise PlatformError(409, "Credentials changed; log in again")
            await conn.execute(
                "UPDATE platform_users SET password_hash=$2,auth_revision=auth_revision+1 WHERE id=$1",
                user_id, replacement_hash,
            )
            await conn.execute(
                "UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id
            )

    async def list_account_rows(self, limit: int, offset: int):
        columns = "id,name,email,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"
        return await self.pool.fetch(
            f"SELECT {columns} FROM platform_users ORDER BY created_at,id LIMIT $1 OFFSET $2",
            limit, offset,
        )

    async def account_row(self, user_id: UUID):
        columns = "id,name,email,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"
        return await self.pool.fetchrow(
            f"SELECT {columns} FROM platform_users WHERE id=$1", user_id
        )

    async def update_account(self, actor: Principal, user_id: UUID, changes: dict):
        if not actor.is_developer:
            raise PlatformError(403, "Developer access required")
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM platform_users WHERE id=$1 FOR UPDATE", user_id)
            if row is None:
                raise PlatformError(404, "Unknown user")
            if row["is_developer"]:
                raise PlatformError(403, "Developer identity is managed through environment configuration")
            previous_roles = json_value(row["roles"])
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
            columns = "id,name,email,professional_verified,is_developer,disabled,roles,plan,plan_expires_at,active_selection_initialized"
            updated = await conn.fetchrow(
                f"UPDATE platform_users SET name=$2,roles=$3::jsonb,professional_verified=$4,plan=$5,plan_expires_at=$6,disabled=$7,"
                f"verification_revision=verification_revision+$8 WHERE id=$1 RETURNING {columns}",
                user_id, changes.get("name", row["name"]), json.dumps(sorted(roles)),
                verified, plan, expires, disabled, int(verification_changed),
            )
            if verification_changed:
                await self.write_outbox_event(
                    conn, row, "professional.author-status",
                    {"author_id": str(user_id), "verified": verified},
                    row["verification_revision"] + 1,
                )
            if disabled:
                await conn.execute(
                    "UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL",
                    user_id,
                )
            if disabled or (row["plan"] == "PRO" and plan == "FREE"):
                await conn.execute(
                    "UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,finished_at=now(),"
                    "error='Account access changed' WHERE user_id=$1 AND state IN ('pending','running')", user_id,
                )
            await conn.execute(
                "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) "
                "VALUES($1,$2,'user.updated',$3::jsonb)",
                actor.id, user_id, json.dumps(changes, default=str),
            )
        return updated

    async def revoke_account_sessions(self, actor: Principal, user_id: UUID):
        if not actor.is_developer:
            raise PlatformError(403, "Developer access required")
        async with self.pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval(
                "SELECT id FROM platform_users WHERE id=$1 FOR UPDATE", user_id
            ):
                raise PlatformError(404, "Unknown user")
            await conn.execute(
                "UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id
            )
            await conn.execute(
                "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) "
                "VALUES($1,$2,'user.sessions.revoked','{}')", actor.id, user_id
            )
        return {"detail": "All user sessions and legacy tokens revoked"}

    async def synchronize_developer(self, name: str, email: str, password: str,
                                    verify_password, hash_password):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(780436153)")
            previous = await conn.fetchrow("SELECT * FROM platform_users WHERE is_developer FOR UPDATE")
            if not email:
                if previous:
                    await conn.execute("UPDATE platform_users SET disabled=true WHERE id=$1", previous["id"])
                    await conn.execute(
                        "UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL",
                        previous["id"],
                    )
                return
            if len(password) < 12 or len(password) > 1024:
                raise RuntimeError("Developer password must contain 12 to 1024 characters")
            developer_id = previous["id"] if previous else uuid4()
            conflict = await conn.fetchval(
                "SELECT id FROM platform_users WHERE lower(email)=$1 AND id<>$2", email, developer_id
            )
            if conflict:
                raise RuntimeError("Developer identity conflicts with an existing account")
            changed = (
                previous is None or previous["email"] != email
                or not await asyncio.to_thread(
                    verify_password, previous["password_hash"] if previous else None, password
                )
                or previous["disabled"]
            )
            encoded = await asyncio.to_thread(hash_password, password) if changed else previous["password_hash"]
            if previous is None:
                await conn.execute(
                    "INSERT INTO platform_users(id,name,email,password_hash,is_developer,professional_verified,roles,plan,active_selection_initialized) "
                    "VALUES($1,$2,$3,$4,true,true,'[\"USER\",\"PROFESSIONAL\",\"REVIEWER\"]','PRO',true)",
                    developer_id, name, email, encoded,
                )
            else:
                await conn.execute(
                    "UPDATE platform_users SET name=$2,email=$3,password_hash=$4,disabled=false,"
                    "roles='[\"USER\",\"PROFESSIONAL\",\"REVIEWER\"]',plan='PRO',plan_expires_at=NULL,"
                    "professional_verified=true,active_selection_initialized=true,auth_revision=auth_revision+$5 WHERE id=$1",
                    developer_id, name, email, encoded, int(changed),
                )
            if changed:
                await conn.execute(
                    "UPDATE platform_tokens SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL",
                    developer_id,
                )
                await conn.execute(
                    "INSERT INTO platform_admin_audit(actor_id,target_user_id,action,details) "
                    "VALUES($1,$1,'developer.credentials.synchronized','{}')", developer_id,
                )

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
            await self.write_outbox_event(con, previous, "professional.author-status",
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

    async def write_outbox_event(self, con, row, kind: str, payload: dict, revision: int):
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
                await self.write_outbox_event(con, row, "professional.published", payload, row["revision"] + 1)
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
            await self.write_outbox_event(con, row, "professional.retracted", {"contribution_id": str(contribution_id),
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
