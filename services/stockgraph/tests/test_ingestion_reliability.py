from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from stockgraph.adapters.messaging.consumer import EventConsumer
from stockgraph.application.ingestion.pipeline import GraphPipeline
from stockgraph.application.processors.news_correlator import NewsCorrelator
from stockgraph.application.processors.news_eligibility import hard_rejection_reason
from stockgraph.runtime.settings import settings

from services.stockgraph.tests.test_graph_workflow import Broker, Chat, Repo, make_event


@pytest.fixture(autouse=True)
def inference_enabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)


class EmbeddedRepo(Repo):
    def merge_news_event(self, props, embedding=None):
        super().merge_news_event(props, embedding)
        if embedding is not None:
            self.news[props["id"]]["embedding"] = embedding
        return self.news[props["id"]]


class Embedder:
    def __init__(self):
        self.texts = []

    def embed_one(self, text):
        self.texts.append(text)
        return [1.0, 0.0]


@pytest.mark.parametrize(
    "headline",
    [
        "PVR INOX quarterly profit rises on strong film releases",
        "Trent reports quarterly earnings growth in its fashion business",
        "TCS profits match analyst estimates",
    ],
)
def test_graph_replay_financial_materiality_is_not_vetoed(headline):
    assert hard_rejection_reason(headline) is None


def test_canonical_upgrade_reembeds_and_routes_accepted_filing():
    repo, broker, embedder, chat = EmbeddedRepo(), Broker(), Embedder(), Chat()
    pipeline = GraphPipeline(repo, broker, chat, embedder)
    first = make_event(entity_id="RSS:first")
    pipeline.process(first)
    incoming = {
        **first.payload,
        "source": "REG30",
        "summary": "Official filing corrects the supply figure",
    }
    pipeline.process(
        first.model_copy(
            update={"event_id": uuid4(), "entity_id": "REG30:filing", "payload": incoming}
        )
    )
    canonical = next(iter(repo.news.values()))
    assert canonical["source"] == "REG30"
    assert canonical["summary"] == incoming["summary"]
    assert embedder.texts[-1].endswith(incoming["summary"])
    assert any(incoming["summary"] in prompt for prompt in chat.prompts)


def test_lower_priority_revision_cannot_route_unaccepted_content():
    repo, broker, embedder = EmbeddedRepo(), Broker(), Embedder()
    first = make_event(entity_id="REG30:filing")
    first = first.model_copy(
        update={"payload": {**first.payload, "source": "REG30", "summary": "Official disclosure"}}
    )
    GraphPipeline(repo, broker, Chat(), embedder).process(first)
    incoming = {
        **first.payload,
        "source": "RSS",
        "summary": "Conflicting unaccepted media copy",
        "source_url": "https://other.test/article",
    }
    chat = Chat()
    GraphPipeline(repo, broker, chat, embedder).process(
        first.model_copy(
            update={"event_id": uuid4(), "entity_id": "RSS:second", "payload": incoming}
        )
    )
    assert next(iter(repo.news.values()))["summary"] == "Official disclosure"
    assert not any(incoming["summary"] in prompt for prompt in chat.prompts)


def test_same_provider_correction_refreshes_canonical_embedding():
    repo, broker, embedder = EmbeddedRepo(), Broker(), Embedder()
    first = make_event()
    pipeline = GraphPipeline(repo, broker, Chat(), embedder)
    pipeline.process(first)
    second = first.model_copy(
        update={
            "event_id": uuid4(),
            "revision": 2,
            "payload": {**first.payload, "summary": "Corrected costs"},
        }
    )
    pipeline.process(second)
    assert next(iter(repo.news.values()))["summary"] == "Corrected costs"
    assert embedder.texts[-1].endswith("Corrected costs")


def test_headline_correction_reuses_source_canonical_identity_and_reconciles_old_edges():
    class ReconciledRepo(EmbeddedRepo):
        def reconcile_news_impacts(self, news_id, scope_tickers, stock_impacts, market_impacts):
            self.accepted = list(stock_impacts)

    class DirectionChat(Chat):
        def complete_json(self, prompt, schema, **kwargs):
            result = super().complete_json(prompt, schema, **kwargs)
            if schema.__name__ == "NewsImpactBatch" and "Corrected headline" in prompt:
                return schema(impacts=[])
            return result

    repo, broker = ReconciledRepo(), Broker()
    first = make_event()
    pipeline = GraphPipeline(repo, broker, DirectionChat(), Embedder())
    pipeline.process(first)
    initial_id = next(iter(repo.news))
    assert repo.accepted
    second = first.model_copy(
        update={
            "event_id": uuid4(),
            "revision": 2,
            "payload": {
                **first.payload,
                "headline": "Corrected headline: supply unaffected",
                "summary": "No cost change",
            },
        }
    )
    pipeline.process(second)
    assert list(repo.news) == [initial_id]
    assert repo.news[initial_id]["headline"].startswith("Corrected headline")
    assert repo.accepted == []


def test_inference_failure_does_not_replace_previous_accepted_edges():
    class ReconciledRepo(EmbeddedRepo):
        def reconcile_news_impacts(self, *args, **kwargs):
            self.replacement = args

    class MarketFailure(Chat):
        def complete_json(self, prompt, schema, **kwargs):
            if schema.__name__ == "NewsMarketImpactBatch":
                raise RuntimeError("model unavailable")
            return super().complete_json(prompt, schema, **kwargs)

    repo = ReconciledRepo()
    with pytest.raises(RuntimeError, match="inference failed"):
        GraphPipeline(repo, Broker(), MarketFailure(), Embedder()).process(make_event())
    assert not hasattr(repo, "replacement") and not repo.impacts
    GraphPipeline(repo, Broker(), Chat(), Embedder()).process(make_event())
    assert repo.replacement[1] == ["STOCK0"]
    assert repo.replacement[2][0]["impact_type"] == "INDIRECTLY_IMPACTS"


def test_correlation_query_failure_is_retryable_and_not_empty_success():
    class FailingRepo:
        def find_correlation_candidates(self, *args, **kwargs):
            raise ConnectionError("database unavailable")

    with pytest.raises(RuntimeError, match="candidate query failed"):
        NewsCorrelator(Chat()).correlate(FailingRepo(), "news", "headline", "summary", 1, 1)


class StreamBroker(Broker):
    def __init__(self):
        super().__init__()
        self.quarantine = []

    def xadd(self, stream, fields):
        self.quarantine.append((stream, fields))
        return "100-0"


@pytest.fixture
def no_lease(monkeypatch):
    import stockgraph.adapters.messaging.consumer as module

    @contextmanager
    def unlocked(_redis):
        yield True

    monkeypatch.setattr(module, "renewable_lock", unlocked)


def test_malformed_events_are_replayable_quarantined_and_acknowledged(caplog):
    broker = StreamBroker()
    consumer = EventConsumer(broker, SimpleNamespace())
    wire = '{"bad":"secret-provider-token"}'
    assert consumer.handle("1-0", {"event": wire})
    assert broker.acks == ["1-0"]
    assert broker.quarantine[0][1]["event"] == wire
    assert "secret-provider-token" not in caplog.text


def test_permanent_failures_have_bounded_attempts(no_lease):
    broker = StreamBroker()

    class Pipeline:
        _repo = Repo()

        def process(self, event):
            raise ValueError("Permanent invalid canonical identity")

    consumer, event = EventConsumer(broker, Pipeline()), make_event()
    for index in range(3):
        assert consumer.handle("1-0", {"event": event.model_dump_json()}) is (index == 2)
    assert broker.acks == ["1-0"] and len(broker.quarantine) == 1
    assert broker.hashes[f"stockgraph:event:{event.event_id}"]["state"] == "quarantined"


def test_dependency_outages_stay_retryable_beyond_permanent_attempt_limit(no_lease):
    broker = StreamBroker()

    class Pipeline:
        _repo = Repo()

        def process(self, event):
            raise ConnectionError("recoverable outage")

    consumer, event = EventConsumer(broker, Pipeline()), make_event()
    for _ in range(5):
        assert not consumer.handle("1-0", {"event": event.model_dump_json()})
    assert not broker.acks and not broker.quarantine


def test_pending_retries_and_new_entries_receive_fair_intake():
    broker = StreamBroker()
    broker.xautoclaim = lambda *args, **kwargs: ["0-0", [("1-0", {})], []]
    broker.xreadgroup = lambda *args, **kwargs: [("stream", [("2-0", {})])]
    consumer = EventConsumer(broker, SimpleNamespace())
    seen = []
    consumer.handle = lambda message_id, fields: seen.append(message_id) or True
    assert consumer.run_once() == 2
    assert seen == ["1-0", "2-0"]
