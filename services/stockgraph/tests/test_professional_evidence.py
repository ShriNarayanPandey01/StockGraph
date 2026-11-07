from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from stockgraph.adapters.api.evidence_routes import build_evidence_router
from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
from stockgraph.application.professional import EvidencePipeline, professional_context
from stockgraph.domain.platform_events import PlatformEvent


def publication(revision=1, contribution=None, version=None):
    now = datetime.now(UTC)
    contribution = contribution or str(uuid4())
    return PlatformEvent(event_id=uuid4(), kind="professional.published", entity_id=contribution,
        revision=revision, occurred_at=now, payload={"contribution_id": contribution,
        "version_id": version or str(uuid4()), "author_id": str(uuid4()), "author_name": "Analyst",
        "ticker": "TCS", "title": "Demand improving", "body": "Evidence indicates stronger demand",
        "direction": "BULLISH", "horizon": "next quarter", "event_at": now.isoformat(),
        "published_at": now.isoformat(), "expires_at": (now+timedelta(days=90)).isoformat(),
        "evidence": [{"url": "https://example.org/filing", "title": "Source", "locator": "page 2"}],
        "future_access": "PRO"})


class MemoryProjection:
    """Small recording driver for the revision protocol, not a Cypher emulator."""
    def __init__(self):
        self.current = {}
        self.queries = []
        self.exists = True

    def get_entity(self, kind, ticker):
        return {"ticker": ticker} if self.exists else None

    def _run(self, query, params):
        self.queries.append((query, params))
        if query.startswith("MATCH (c:Contribution"):
            return [[self.current.copy()]] if self.current else []
        if query.startswith("MERGE (c:Contribution"):
            self.current = {"revision": params["revision"]}
        return []


def test_retraction_tombstone_blocks_out_of_order_publication():
    repo = MemoryProjection()
    pipeline = EvidencePipeline(EvidenceRepository(repo))
    old = publication()
    retract = PlatformEvent(event_id=uuid4(), kind="professional.retracted", entity_id=old.entity_id,
        revision=2, occurred_at=datetime.now(UTC), payload={"ticker": "TCS", "reason": "Correction"})
    pipeline.process(retract)
    assert pipeline.process(old) is False
    assert not any("MERGE (p:ProfessionalEvidence" in q for q, _ in repo.queries)


def test_projection_is_idempotent_and_does_not_invent_canonical_stocks():
    repo = MemoryProjection()
    event = publication()
    repo.exists = False
    with pytest.raises(KeyError):
        EvidencePipeline(EvidenceRepository(repo)).process(event)
    assert repo.current == {}
    repo.exists = True
    assert EvidencePipeline(EvidenceRepository(repo)).process(event) is True
    writes = len(repo.queries)
    assert EvidencePipeline(EvidenceRepository(repo)).process(event) is False
    assert len(repo.queries) == writes + 1
    assert any("SUPERSEDES" in q for q, _ in repo.queries)


def test_evidence_read_is_authorized_with_bounded_weight_and_opposing_evidence_policy():
    class Repo:
        def get_entity(self, kind, ticker):
            return {"ticker": ticker}
        def _run(self, query, params):
            assert "p.retracted=false" in query and "p.valid_to_ts>=$end" in query
            return [[{"id": "view", "direction": "BULLISH", "evidence_json": "[]"}]]
    from stockgraph.adapters.api.internal_auth import install_internal_boundary
    from stockgraph.runtime.settings import settings
    app = FastAPI()
    install_internal_boundary(app, settings)
    app.include_router(build_evidence_router(Repo()))
    with TestClient(app, headers={"X-Internal-Service-Key": "test-internal-key", "X-MarketGraph-Evidence-Scope": "professional"}) as client:
        response = client.get("/api/v1/stocks/TCS/professional-evidence")
        assert response.status_code == 200
        result = response.json()
        assert result["items"][0]["priority_weight"] > 1
        assert result["policy"]["subscription_enforced"] is True
        assert "opposing evidence" in result["policy"]["instruction"]
        assert client.get("/api/v1/stocks/TCS/professional-evidence?as_of_ts=1").status_code == 422


def test_revoked_author_keeps_evidence_but_loses_professional_priority():
    class Repo:
        def professional_page(self, *args):
            return [{"id": "view", "author_verified": False}]
    result = professional_context(Repo(), "TCS", 0, 100)
    assert result["items"][0]["priority_weight"] == 1.0
    assert result["policy"]["professional_weight"] > 1.0


def test_guidance_embeddings_use_native_vectors_and_preserve_source_locator():
    repo = MemoryProjection()
    now = datetime.now(UTC)
    document_id = str(uuid4())
    event = PlatformEvent(event_id=uuid4(), kind="document.extracted", entity_id=document_id,
        revision=1, occurred_at=now, payload={"ticker": "TCS", "version_id": str(uuid4()),
        "document_id": document_id, "content_hash": "a" * 64, "title": "Concall",
        "source_url": "https://example.org/concall", "document_kind": "GUIDANCE",
        "chunks": [{"id": "chunk:0", "text": "Demand expected to improve", "page": 2,
                    "ordinal": 0, "locator": "page 2, characters 1-26"}]})
    class Embedder:
        def embed_one(self, text):
            assert text == "Demand expected to improve"
            return [1.0, 0.0]
    EvidencePipeline(EvidenceRepository(repo), Embedder()).process(event)
    assert any("vecf32($embedding)" in q for q, _ in repo.queries)
    chunk = next(params["props"] for q, params in repo.queries if "DocumentChunk:GuidanceChunk" in q)
    assert chunk["locator"].startswith("page 2")
    assert chunk["source_url"] == event.payload["source_url"]


def test_evidence_consumer_retries_failed_projection_and_acknowledges_once(monkeypatch):
    from contextlib import contextmanager

    from stockgraph.adapters.messaging import platform_consumer
    from stockgraph.adapters.messaging.platform_consumer import PlatformConsumer
    event = publication()
    @contextmanager
    def lock(_redis):
        yield lambda: None
    monkeypatch.setattr(platform_consumer, "renewable_lock", lock)
    class Redis:
        def __init__(self):
            self.states = {}
            self.acked = []
        def xautoclaim(self, *args, **kwargs):
            return ["0-0", [("1-0", {"event": event.model_dump_json()})]]
        def hget(self, key, field):
            return self.states.get(key, {}).get(field)
        def hset(self, key, mapping):
            self.states[key] = mapping
        def xack(self, *args):
            self.acked.append(args[-1])
    class Repo:
        def set_write_guard(self, guard):
            pass
    class Pipeline:
        _repo = Repo()
        failed = True
        calls = 0
        def process(self, event):
            self.calls += 1
            if self.failed:
                raise RuntimeError("Upstream projection not available")
    redis, pipeline = Redis(), Pipeline()
    consumer = PlatformConsumer(redis, pipeline)
    assert consumer.run_once() == 0
    assert redis.acked == []
    redis.states[consumer._retry_key("1-0")]["next_attempt_at"] = 0
    pipeline.failed = False
    assert consumer.run_once() == 1
    assert consumer.run_once() == 1
    assert pipeline.calls == 2


@pytest.mark.parametrize("error_type", [KeyError, ValueError])
def test_pending_evidence_does_not_starve_new_work_and_canonical_gaps_remain_retryable(monkeypatch, error_type):
    from contextlib import contextmanager

    from stockgraph.adapters.messaging import platform_consumer
    from stockgraph.adapters.messaging.platform_consumer import PlatformConsumer
    pending, fresh = publication(), publication()
    @contextmanager
    def lock(_redis):
        yield lambda: None
    monkeypatch.setattr(platform_consumer, "renewable_lock", lock)
    class Redis:
        def __init__(self):
            self.states, self.quarantine, self.acks = {}, [], []
        def xautoclaim(self, *args, **kwargs):
            return ["0-0", [("1-0", {"event": pending.model_dump_json()})]]
        def xreadgroup(self, *args, **kwargs):
            assert "block" not in kwargs  # Recovered work must not delay admission.
            return [("stream", [("2-0", {"event": fresh.model_dump_json()})])]
        def hget(self, key, field):
            return self.states.get(key, {}).get(field)
        def hset(self, key, mapping):
            self.states.setdefault(key, {}).update(mapping)
        def xadd(self, stream, fields):
            self.quarantine.append((stream, fields))
        def xack(self, *args):
            self.acks.append(args[-1])
    class Repo:
        def set_write_guard(self, guard):
            pass
    class Pipeline:
        _repo = Repo()
        processed = []
        def process(self, event):
            if event.event_id == pending.event_id:
                raise error_type("Canonical stock pending" if error_type is KeyError else "Invalid contribution")
            self.processed.append(event.event_id)
    redis, pipeline = Redis(), Pipeline()
    consumer = PlatformConsumer(redis, pipeline)
    for _ in range(3):
        consumer.run_once()
        redis.states[consumer._retry_key("1-0")]["next_attempt_at"] = 0
    assert fresh.event_id in pipeline.processed
    assert bool(redis.quarantine) is (error_type is ValueError)
    assert ("1-0" in redis.acks) is (error_type is ValueError)


def test_professional_event_calendar_date_uses_ist():
    repo = MemoryProjection()
    event = publication()
    event = event.model_copy(update={"payload": {**event.payload, "event_at": "2026-10-23T20:00:00+00:00"}})
    EvidencePipeline(EvidenceRepository(repo)).process(event)
    stored = next(params["props"] for query, params in repo.queries if "MERGE (p:ProfessionalEvidence" in query)
    assert stored["event_date"] == "2026-10-24"


def test_malformed_platform_envelope_is_quarantined_with_original_for_replay():
    from stockgraph.adapters.messaging.platform_consumer import PlatformConsumer
    class Redis:
        def __init__(self):
            self.states, self.quarantine, self.acks = {}, [], []
        def xautoclaim(self, *args, **kwargs):
            return ["0-0", [("broken-0", {"event": "malformed wire data"})]]
        def hget(self, key, field):
            return self.states.get(key, {}).get(field)
        def hset(self, key, mapping):
            self.states.setdefault(key, {}).update(mapping)
        def xadd(self, stream, fields):
            self.quarantine.append(fields)
        def xack(self, *args):
            self.acks.append(args[-1])
    redis = Redis()
    assert PlatformConsumer(redis, object()).run_once() == 1
    assert redis.acks == ["broken-0"]
    assert redis.quarantine[0]["event"] == "malformed wire data"


def test_out_of_order_guidance_does_not_replace_latest_prompt_context():
    from stockgraph.application.processors.stock_profile_provider import StockProfileProvider
    class Repo(MemoryProjection):
        def __init__(self):
            super().__init__()
            self.record = {}
            self.chunks = []
        def get_active_exposures(self, ticker):
            return []
        def get_entity(self, kind, ticker):
            return {"ticker": ticker, "latest_quarter_summary": "Current quarterly narrative",
                    "latest_guidance_highlights": ["Old profile guidance"]}
        def _run(self, query, params):
            if query.startswith("MATCH (d:DocumentRecord"):
                return [[self.record]] if self.record else []
            if query.startswith("MERGE (d:DocumentRecord"):
                self.record = {"revision": params["revision"], "version_id": params["version"], "known_at_ts": params["ts"]}
            if "DocumentChunk:GuidanceChunk" in query:
                self.chunks.append(params["props"])
            if "RETURN c.text" in query:
                return [[c["text"]] for c in self.chunks if c["is_latest"]]
            return []
    repo = Repo()
    document_id = str(uuid4())
    def document(revision, text):
        return PlatformEvent(event_id=uuid4(), kind="document.extracted", entity_id=document_id,
            revision=revision, occurred_at=datetime.now(UTC), payload={"ticker": "TCS",
            "version_id": str(uuid4()), "document_id": document_id, "content_hash": str(revision)*64,
            "title": "Concall", "source_url": "https://example.org/concall", "document_kind": "GUIDANCE",
            "chunks": [{"id": f"chunk:{revision}", "text": text, "page": 1, "ordinal": 0, "locator": "page 1"}]})
    pipeline = EvidencePipeline(EvidenceRepository(repo))
    pipeline.process(document(2, "New guidance"))
    pipeline.process(document(1, "Superseded guidance"))
    card = StockProfileProvider(repo, EvidenceRepository(repo)).build_context_card("TCS")
    assert card.latest_guidance_highlights == ["New guidance"]
    assert card.latest_quarter_summary == "Current quarterly narrative"
    assert repo.record["revision"] == 2
