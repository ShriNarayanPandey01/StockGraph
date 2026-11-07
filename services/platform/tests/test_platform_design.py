"""Checks for immutable domain snapshots and explicit application service ports."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from marketgraph_platform.api import HttpGraphClient, create_app
from marketgraph_platform.application.contributions import ContributionService
from marketgraph_platform.application.research import AgentContextService, ResearchSubmissionService
from marketgraph_platform.auth import token_digest
from marketgraph_platform.domain.access import AccessSnapshot
from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import ContributionInput, Principal
from marketgraph_platform.settings import Settings
from pydantic import SecretStr, ValidationError


def _contribution():
    now = datetime.now(UTC)
    return ContributionInput(
        ticker="TCS", title="Demand outlook", body="Evidence-backed view.",
        direction="BULLISH", horizon="Next quarter", event_at=now,
        expires_at=now + timedelta(days=90), evidence=[{
            "url": "https://example.org/report", "title": "Filing", "locator": "Page 2",
        }], disclosures="No position held",
    )


def test_access_snapshot_detaches_all_nested_mutable_state():
    principal = Principal(id=uuid4(), name="Analyst", roles=["USER", "PROFESSIONAL"])
    policy = {
        "plan": "PRO", "active_stock_limit": 10, "monthly_alert_limit": 10,
        "features": {"research_chat": False, "discovery": True}, "revision": 3,
    }
    access = AccessSnapshot(principal, policy, ["TCS", "INFY", "TCS"])

    policy["features"]["research_chat"] = True
    returned_policy = access.policy
    returned_policy["features"]["discovery"] = False

    assert access.allows("research_chat") is False
    assert access.allows("discovery") is True
    assert access.tickers == ("INFY", "TCS")
    assert access.user.roles == ("USER", "PROFESSIONAL")
    with pytest.raises(ValidationError):
        access.user.is_developer = True


@pytest.mark.asyncio
async def test_contribution_service_validates_before_persisting_and_measures_after():
    user = Principal(id=uuid4(), name="Author", professional_verified=True,
                     roles=("USER", "PROFESSIONAL"))
    calls = []

    class DataClient:
        async def validate_ticker(self, ticker):
            calls.append(("ticker", ticker))

        async def validate_citations(self, content):
            calls.append(("citations", content.ticker))

    class Repository:
        async def create_contribution(self, actor, content, key):
            calls.append(("create", actor.id, content.ticker, key))
            return {"id": "draft"}

        async def measure(self, user_id, feature, units=1):
            calls.append(("measure", user_id, feature, units))

    service = ContributionService(Repository(), DataClient())
    result = await service.create(user, _contribution(), "request-1")
    assert result == {"id": "draft"}
    assert [call[0] for call in calls] == ["ticker", "citations", "create", "measure"]

    calls.clear()
    with pytest.raises(PlatformError) as denied:
        await service.create(Principal(id=uuid4(), name="Unverified"), _contribution(), "request-2")
    assert denied.value.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_research_submission_resolves_canonical_tickers_and_preserves_actor_scope():
    developer = Principal(id=uuid4(), name="Developer", is_developer=True)
    submitted = {}

    class Entitlements:
        async def check(self, user):
            return AccessSnapshot(user, {
                "plan": "PRO", "features": {"discovery": True}, "revision": 1,
            }, ())

    class DataClient:
        async def get(self, path, params=None, *, headers=None):
            return {"entities": [{"entity_id": "TCS"}, {"payload": {"ticker": "INFY"}}]}

    class Jobs:
        async def create_research_job(self, owner_id, kind, payload, key, max_pending, actor_id=None):
            submitted.update(owner_id=owner_id, kind=kind, payload=payload, key=key,
                             max_pending=max_pending, actor_id=actor_id)
            return {"id": "job-1", "lease_token": "private"}

        async def conversation_owner(self, conversation_id, user):
            raise AssertionError("Discovery does not require a conversation")

    class Audit:
        async def audit_action(self, actor_id, action, target_id=None, details=None):
            submitted["audit"] = (actor_id, action, target_id, details)

    settings = Settings(_env_file=None, operational_max_pending_jobs_per_user=17)
    service = ResearchSubmissionService(Entitlements(), DataClient(), Jobs(), settings, Audit())
    body = SimpleNamespace(tickers=[" tcs ", "INFY", "TCS"], model_dump=lambda: {"question": "Why?"})
    result = await service.submit(developer, body, "request-2", "discovery")

    assert result == {"id": "job-1"}
    assert submitted["owner_id"] == developer.id and submitted["actor_id"] == developer.id
    assert submitted["payload"] == {"question": "Why?", "tickers": ["TCS", "INFY"]}
    assert submitted["max_pending"] == 17
    assert submitted["audit"][1] == "research.submit"


@pytest.mark.asyncio
async def test_agent_document_context_registers_only_the_requested_stock_evidence():
    user = Principal(id=uuid4(), name="Agent owner", plan="PRO")
    access = AccessSnapshot(user, {
        "plan": "PRO", "features": {"professional_evidence": True}, "revision": 1,
    }, ("TCS",))
    calls = []

    class Jobs:
        async def reserve_tool_call(self, job_id, lease, actor):
            calls.append(("reserve", job_id, lease, actor))

        async def register_evidence(self, job_id, lease, entries):
            calls.append(("evidence", [item["id"] for item in entries]))
            return [{"id": item["id"], "kind": item["kind"]} for item in entries]

    class GraphClient:
        async def get(self, path, params=None, *, professional=False, developer=False):
            calls.append(("graph", path, params, professional, developer))
            return {"items": [
                {"id": "doc-tcs", "ticker": "TCS", "text": "TCS filing", "page": 3},
                {"id": "doc-infy", "ticker": "INFY", "text": "Other company"},
                {"id": "missing-text", "ticker": "TCS"},
            ]}

    service = AgentContextService(Jobs(), object(), object(), GraphClient())
    job_id, lease = uuid4(), uuid4()
    result = await service.search_documents(
        job={"state": "running", "input": {"tickers": ["TCS"]}},
        job_id=job_id, lease=lease, ticker="TCS", query="orders", access=access,
        actor="agent:test", limit=25, offset=0,
    )

    assert result["available_evidence"] == [{"id": "doc-tcs", "kind": "document"}]
    assert result["source_content_trust"] == "untrusted"
    assert calls == [
        ("reserve", job_id, lease, "agent:test"),
        ("graph", "/api/v1/stocks/TCS/documents/search",
         {"q": "orders", "offset": 0, "limit": 25}, True, False),
        ("evidence", ["doc-tcs"]),
    ]


@pytest.mark.asyncio
async def test_graph_client_reuses_trusted_transport_and_scopes_each_request():
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(_env_file=None, internal_service_key=SecretStr("service-key"))
    client = HttpGraphClient(settings, transport=httpx.MockTransport(handler))
    try:
        await client.get("/context", {"window": "LAST_6M"}, professional=True)
        await client.request("POST", "/manual", body={"ticker": "TCS"}, developer=True)
    finally:
        await client.close()

    assert len(seen) == 2
    assert seen[0].headers["X-Internal-Service-Key"] == "service-key"
    assert seen[0].headers["X-MarketGraph-Evidence-Scope"] == "professional"
    assert seen[0].headers["X-MarketGraph-Developer"] == "false"
    assert seen[1].headers["X-MarketGraph-Evidence-Scope"] == "ordinary"
    assert seen[1].headers["X-MarketGraph-Developer"] == "true"


@pytest.mark.asyncio
async def test_platform_http_workflows_reach_application_services_and_repositories():
    user = Principal(
        id=uuid4(), name="Verified author", professional_verified=True,
        roles=("USER", "PROFESSIONAL"), plan="PRO",
    )
    created = {}

    class Repository:
        async def authenticate(self, digest):
            return user.model_dump() if digest == token_digest("platform-e2e-token") else None

        async def allow_request(self, user_id):
            return user_id == user.id

        async def load_access_snapshot(self, user_id):
            assert user_id == user.id
            return AccessSnapshot(user, {
                "plan": "PRO", "active_stock_limit": None, "monthly_alert_limit": None,
                "features": {"research_chat": True, "discovery": True,
                             "professional_evidence": True}, "revision": 4,
            }, ("TCS",))

        async def create_research_job(self, owner_id, kind, payload, key, max_pending, actor_id=None):
            created["job"] = (owner_id, kind, payload, key, max_pending, actor_id)
            return {"id": "job-42", "state": "pending", "lease_token": "private"}

        async def conversation_owner(self, conversation_id, user):
            raise AssertionError("This discovery scan is not attached to a conversation")

        async def create_contribution(self, actor, content, key):
            created["contribution"] = (actor.id, content.ticker, key)
            return {"id": "draft-42", "status": "DRAFT"}

        async def measure(self, user_id, feature, units=1):
            created.setdefault("usage", []).append((user_id, feature, units))

        async def audit_action(self, *args, **kwargs):
            created["audit"] = (args, kwargs)

    class DataClient:
        async def get(self, path, params=None, *, headers=None):
            assert path == "/api/v1/entities" and params == {"kind": "Stock"}
            return {"entities": [{"entity_id": "TCS"}, {"payload": {"ticker": "INFY"}}]}

        async def validate_ticker(self, ticker):
            assert ticker == "TCS"

        async def validate_citations(self, content):
            assert content.ticker == "TCS"

    class GraphClient:
        async def get(self, *args, **kwargs):
            raise AssertionError("These workflows do not require a graph read")

        async def request(self, *args, **kwargs):
            raise AssertionError("These workflows do not require a graph write")

    settings = Settings(_env_file=None, operational_max_pending_jobs_per_user=17)
    app = create_app(settings, Repository(), DataClient(), GraphClient())
    headers = {"Authorization": "Bearer platform-e2e-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://platform.test"
    ) as client:
        discovery = await client.post(
            "/api/v1/discovery/scans",
            json={"question": "What changed for TCS?", "tickers": ["tcs", "TCS"]},
            headers={**headers, "Idempotency-Key": "scan-42"},
        )
        contribution = await client.post(
            "/api/v1/contributions",
            json=_contribution().model_dump(mode="json"),
            headers={**headers, "Idempotency-Key": "draft-42"},
        )

    assert discovery.status_code == 202
    assert discovery.json() == {"id": "job-42", "state": "pending"}
    assert created["job"] == (
        user.id, "discovery",
        {"question": "What changed for TCS?", "tickers": ["TCS"], "window": "LAST_6M"},
        "scan-42", 17, None,
    )
    assert contribution.status_code == 201 and contribution.json()["status"] == "DRAFT"
    assert created["contribution"] == (user.id, "TCS", "draft-42")
    assert created["usage"] == [(user.id, "contribution_drafts", 1)]
