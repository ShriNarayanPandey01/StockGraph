"""Offline access/publication safety checks and opt-in isolated PostgreSQL workflow."""

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import httpx
import pytest
from marketgraph_platform.api import CanonicalClient, create_app
from marketgraph_platform.auth import issue_token, token_digest
from marketgraph_platform.models import ContributionInput, Principal
from marketgraph_platform.policy import access_policy
from marketgraph_platform.repository import PlatformError, Repository
from marketgraph_platform.settings import Settings
from marketgraph_platform.worker import relay_once
from pydantic import ValidationError


def contribution(**overrides):
    now = datetime.now(UTC)
    return ContributionInput.model_validate({
        "ticker": "RELIANCE", "title": "Demand outlook", "body": "Demand may improve; contrary evidence remains relevant.",
        "direction": "BULLISH", "horizon": "Next quarter", "event_at": now,
        "expires_at": now + timedelta(days=90), "disclosures": "No position held",
        "evidence": [{"url": "https://example.org/report", "title": "Quarterly report", "locator": "Page 2"}],
        **overrides,
    })


def user(verified=False):
    return Principal(id=uuid4(), name="Researcher", professional_verified=verified)


def test_all_features_are_free_without_plan_or_role_checks():
    policy = access_policy()
    assert all(feature["allowed"] for feature in policy["features"].values())
    assert not policy["billing_enabled"] and not policy["rbac_enabled"] and not policy["quota_enforcement"]
    assert policy["future_free_limits"]["opportunity_alerts_per_month"] == 10
    assert policy["future_free_limits"]["reset_timezone"] == "Asia/Kolkata"


def test_token_digest_is_not_a_bearer_and_tokens_are_unique():
    first, digest = issue_token()
    second, _ = issue_token()
    assert first != second and first != digest
    assert len(first) >= 64 and len(digest) == 64 and token_digest(first) == digest


def test_evidence_requires_aware_time_expiry_and_citations():
    with pytest.raises(ValidationError):
        contribution(event_at=datetime.now())
    with pytest.raises(ValidationError):
        contribution(expires_at=datetime.now(UTC) - timedelta(days=1))
    with pytest.raises(ValidationError):
        contribution(evidence=[])
    with pytest.raises(ValidationError):
        contribution(evidence=[{"url": "https://key:secret@example.org", "title": "Private", "locator": "Page 1"}])


@pytest.mark.asyncio
async def test_api_authentication_operational_budget_and_free_access():
    principal = user()
    repository = AsyncMock()
    repository.authenticate.return_value = principal.model_dump()
    repository.allow_request.return_value = True
    canonical = AsyncMock()
    app = create_app(Settings(), repository, canonical)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/me")).status_code == 401
        result = await client.get("/api/v1/access-policy", headers={"Authorization": "Bearer opaque"})
        assert result.status_code == 200
        assert result.json()["features"]["professional_evidence"]["allowed"]
        repository.allow_request.return_value = False
        assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer opaque"})).status_code == 429


@pytest.mark.asyncio
async def test_api_published_evidence_preserves_opposing_items_and_counts_reads():
    principal = user()
    repository = AsyncMock()
    repository.authenticate.return_value = principal.model_dump()
    repository.allow_request.return_value = True
    repository.published.return_value = [{"direction": "BULLISH"}, {"direction": "BEARISH"}]
    canonical = AsyncMock()
    app = create_app(Settings(), repository, canonical)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/v1/stocks/RELIANCE/professional-evidence", headers={"Authorization": "Bearer opaque"})
    assert result.status_code == 200
    assert result.json()["contradictions_retained"] and len(result.json()["items"]) == 2
    repository.measure.assert_awaited_once_with(principal.id, "professional_evidence_reads")


@pytest.mark.asyncio
async def test_unknown_entity_is_rejected_before_creating_draft():
    principal = user()
    repository = AsyncMock()
    repository.authenticate.return_value = principal.model_dump()
    repository.allow_request.return_value = True
    canonical = CanonicalClient(Settings())
    await canonical.client.aclose()
    canonical.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"entities": []})), base_url="http://data")
    app = create_app(Settings(), repository, canonical)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.post("/api/v1/contributions", json=contribution().model_dump(mode="json"), headers={"Authorization": "Bearer opaque", "Idempotency-Key": "draft-1"})
        assert result.status_code == 422
        repository.create_contribution.assert_not_awaited()
    finally:
        await canonical.close()


class Connection:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.writes = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, *args):
        return next(self.rows)

    async def execute(self, *args):
        self.writes.append(args)


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,status", [("self_review", 403), ("unverified", 409), ("expired", 422), ("stale", 409)])
async def test_review_rejects_unsafe_publication_without_writes(scenario, status):
    author, reviewer = user(), user()
    row = {"id": uuid4(), "author_id": author.id, "revision": 2, "status": "SUBMITTED", "current_version_id": uuid4()}
    version = {"expires_at": datetime.now(UTC) + timedelta(days=1)}
    if scenario == "expired":
        version["expires_at"] = datetime.now(UTC) - timedelta(days=1)
    con = Connection([row, version, {"professional_verified": scenario != "unverified"}])
    repository = Repository(Settings())
    repository.pool = Pool(con)
    with pytest.raises(PlatformError) as exc:
        await repository.review(row["id"], author if scenario == "self_review" else reviewer,
                                1 if scenario == "stale" else 2, "APPROVE", "Reviewed")
    assert exc.value.status == status and con.writes == []


@pytest.mark.asyncio
async def test_outbox_retries_preserve_event_identity_after_lost_ack():
    event = {"event_id": str(uuid4()), "kind": "professional.published", "revision": 3}
    row = {"event_id": uuid4(), "lease_id": uuid4(), "event": event, "attempts": 1}
    repository, redis = AsyncMock(), AsyncMock()
    repository.claim_outbox.return_value = [row]
    repository.finish_outbox.side_effect = [RuntimeError("ack lost"), None]
    assert await relay_once(repository, redis, Settings()) == 0
    assert await relay_once(repository, redis, Settings()) == 1
    first, second = redis.xadd.await_args_list
    assert json.loads(first.args[1]["event"]) == json.loads(second.args[1]["event"])
    repository.retry_outbox.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("PLATFORM_TEST_DATABASE_DSN"), reason="Set PLATFORM_TEST_DATABASE_DSN for isolated live PostgreSQL checks")
async def test_postgres_publication_correction_retraction_and_immutability():
    dsn = os.environ["PLATFORM_TEST_DATABASE_DSN"]
    schema = "platform_test_" + uuid4().hex
    admin = await asyncpg.connect(dsn)
    repository = Repository(Settings())
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    try:
        repository.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, server_settings={"search_path": schema})
        await repository.migrate()
        author_id = await repository.provision_user("Author", token_digest("author"), True)
        reviewer_id = await repository.provision_user("Reviewer", token_digest("reviewer"))
        author, reviewer = Principal(id=author_id, name="Author", professional_verified=True), Principal(id=reviewer_id, name="Reviewer")
        initial = contribution()
        draft = await repository.create_contribution(author, initial, "draft-retry")
        retried = await repository.create_contribution(author, initial, "draft-retry")
        assert retried["id"] == draft["id"]
        with pytest.raises(PlatformError):
            await repository.create_contribution(author, contribution(direction="BEARISH"), "draft-retry")
        with pytest.raises(PlatformError) as denied:
            await repository.detail(draft["id"], reviewer)
        assert denied.value.status == 404
        submitted = await repository.submit(draft["id"], author, 1)
        with pytest.raises(PlatformError):
            await repository.review(draft["id"], author, submitted["revision"], "APPROVE", "Self review")
        approved = await repository.review(draft["id"], reviewer, submitted["revision"], "APPROVE", "Evidence checked")
        assert len(await repository.published("RELIANCE")) == 1
        correction = await repository.add_version(draft["id"], author, contribution(direction="BEARISH"), approved["revision"])
        assert (await repository.published("RELIANCE"))[0]["content"]["direction"] == "BULLISH"
        submitted = await repository.submit(draft["id"], author, correction["revision"])
        approved = await repository.review(draft["id"], reviewer, submitted["revision"], "APPROVE", "Correction checked")
        assert (await repository.published("RELIANCE"))[0]["content"]["direction"] == "BEARISH"
        await repository.retract(draft["id"], author, approved["revision"], "Source withdrawn")
        assert await repository.published("RELIANCE") == []
        assert await repository.pool.fetchval("SELECT count(*) FROM platform_outbox") == 3
        assert await repository.pool.fetchval("SELECT count(*) FROM platform_contribution_versions") == 2
        await repository.set_verified(author_id, False)
        await repository.set_verified(author_id, False)
        status_event = await repository.pool.fetchval(
            "SELECT event FROM platform_outbox WHERE event->>'kind'='professional.author-status'")
        status_event = json.loads(status_event) if isinstance(status_event, str) else status_event
        assert status_event['revision'] == 2 and status_event['payload']['verified'] is False
        assert await repository.pool.fetchval("SELECT count(*) FROM platform_outbox") == 4
        with pytest.raises(asyncpg.RaiseError):
            await repository.pool.execute("UPDATE platform_contribution_versions SET content='{}'")
    finally:
        await repository.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
