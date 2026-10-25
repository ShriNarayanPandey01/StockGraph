"""Offline access and publication safety checks."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

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
    return Principal(id=uuid4(), name="Researcher", professional_verified=verified,
                     roles=["USER", "PROFESSIONAL"] if verified else ["USER"])


class EntitlementPool:
    def __init__(self, principal):
        self.principal = principal

    async def fetchrow(self, query, *args):
        if "FROM platform_users" in query:
            return self.principal.model_dump()
        if "FROM platform_plan_policies" in query:
            pro = self.principal.plan == "PRO" or self.principal.is_developer
            return {"plan": "PRO" if pro else "FREE", "active_stock_limit": None if pro else 10,
                    "monthly_alert_limit": None if pro else 10,
                    "features": {"professional_evidence": pro, "research_chat": True,
                                 "discovery": pro, "opportunity_alerts": True,
                                 "stock_connections": True, "monitoring": True,
                                 "market_monitoring": pro}, "revision": 1}
        return None

    async def fetch(self, query, *args):
        return []


def test_free_policy_enforces_phase_two_entitlements_without_billing():
    policy = access_policy()
    assert policy["phase"] == 2
    assert policy["features"]["research_chat"]["allowed"]
    assert not policy["features"]["professional_evidence"]["allowed"]
    assert policy["billing_enabled"] is False
    assert policy["rbac_enabled"] is True and policy["quota_enforcement"] is True
    assert policy["limits"]["active_stocks"] == 10
    assert policy["limits"]["opportunity_alerts_per_month"] == 10
    assert policy["limits"]["reset_timezone"] == "Asia/Kolkata"
    assert all(item["allowed"] for item in access_policy(Principal(
        id=uuid4(), name="Developer", is_developer=True))["features"].values())


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
    repository.pool = EntitlementPool(principal)
    canonical = AsyncMock()
    canonical.validate_ticker.return_value = None
    app = create_app(Settings(), repository, canonical)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/me")).status_code == 401
        result = await client.get("/api/v1/access-policy", headers={"Authorization": "Bearer opaque"})
        assert result.status_code == 200
        assert result.json()["features"]["research_chat"]["allowed"]
        assert not result.json()["features"]["professional_evidence"]["allowed"]
        repository.allow_request.return_value = False
        assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer opaque"})).status_code == 429


@pytest.mark.asyncio
async def test_api_published_evidence_preserves_opposing_items_and_counts_reads():
    principal = user()
    principal = principal.model_copy(update={"plan": "PRO"})
    repository = AsyncMock()
    repository.authenticate.return_value = principal.model_dump()
    repository.allow_request.return_value = True
    repository.pool = EntitlementPool(principal)
    repository.published.return_value = [{"direction": "BULLISH"}, {"direction": "BEARISH"}]
    canonical = AsyncMock()
    canonical.validate_ticker.return_value = None
    app = create_app(Settings(), repository, canonical)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/v1/stocks/RELIANCE/professional-evidence", headers={"Authorization": "Bearer opaque"})
    assert result.status_code == 200
    assert result.json()["contradictions_retained"] and len(result.json()["items"]) == 2
    repository.measure.assert_awaited_once_with(principal.id, "professional_evidence_reads")


@pytest.mark.asyncio
async def test_unknown_entity_is_rejected_before_creating_draft():
    principal = user(verified=True)
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
