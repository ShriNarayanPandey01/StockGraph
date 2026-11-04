"""Offline behavior tests for the bounded LangGraph workflows."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from marketgraph_agents.models import ModelFinding
from marketgraph_agents.transport import PlatformCallError
from marketgraph_agents.worker import run_job
from marketgraph_agents.workflows import build_graph


def offered(kind, identity, ticker='AAA', quote='A supported fact'):
    return {'kind': kind, 'id': identity, 'ticker': ticker, 'locator': None,
            'quote_text': quote, 'material_version': 'a' * 64}


def reference(item, quote=None):
    return {**{key: item[key] for key in ('kind', 'id', 'ticker', 'locator', 'material_version')},
            'quote': quote or item['quote_text']}


class Client:
    def __init__(self, candidates=None, baseline=None):
        self.items = candidates if candidates is not None else [self.candidate('AAA')]
        self.old = baseline or {}

    @staticmethod
    def candidate(ticker):
        return {'ticker': ticker, 'event_id': f'news-{ticker}', 'event_ts': int(datetime.now(UTC).timestamp()),
                'material_version': 'a' * 64, 'path_kind': 'direct', 'headline': 'An event'}

    async def candidates(self, job_id, lease, offset=0):
        return {'items': self.items[offset:offset + 100], 'as_of_ts': int(datetime.now(UTC).timestamp()),
                'total': len(self.items), 'truncated': False,
                'next_offset': offset + 100 if len(self.items) > offset + 100 else None}

    async def baseline(self, job_id, lease):
        return {'coverage': self.old}

    async def history(self, job_id, lease):
        return {'items': [{'role': 'user', 'content': 'Earlier question'}]}

    async def context(self, job_id, lease, ticker, as_of_ts=None):
        refs = [offered('news', f'news-{ticker}', ticker), offered('graph', f'edge-{ticker}', ticker),
                offered('financial', f'financial-{ticker}', ticker)]
        edge = {'id': f'edge-{ticker}', 'source': f'NewsEvent:news-{ticker}',
                'target': f'Stock:{ticker}', 'relation': 'DIRECTLY_IMPACTS', 'confidence': 0.9}
        return {'available_evidence': refs, 'graph': {'edges': [edge]}}

    async def documents(self, job_id, lease, ticker, question):
        return {'available_evidence': []}


class Model:
    def __init__(self, finding):
        self.finding = ModelFinding.model_validate(finding)
        self.calls = 0
        self.reported_tokens = 0

    async def complete(self, prompt):
        self.calls += 1
        return self.finding


def opportunity(quote=None):
    news = reference(offered('news', 'news-AAA'), quote)
    edge = reference(offered('graph', 'edge-AAA'))
    financial = reference(offered('financial', 'financial-AAA'))
    return {'ticker': 'AAA', 'direction': 'BULLISH', 'horizon_sessions': 10, 'title': 'Catalyst',
            'thesis': 'A supported thesis', 'why_now': 'Recent event', 'risks': 'Demand may weaken',
            'invalidation': 'Demand falls', 'catalyst': news, 'connections': [edge],
            'corroboration': [financial], 'counter_evidence': [], 'material_change': False, 'change_summary': ''}


def job(kind='discovery', tickers=None):
    return {'id': 'job-1', 'attempts': 1, 'kind': kind,
            'input': {'question': 'What changed?', 'tickers': tickers or ['AAA'], 'window': 'LAST_6M'}}


async def invoke(kind, client, finding, tickers=None):
    model = Model(finding)
    graph = build_graph(kind, client, job(kind, tickers), 'lease', model)
    result = await graph.ainvoke({'kind': kind}, {'configurable': {'thread_id': 'test'}, 'recursion_limit': 30})
    return result['result'], model


@pytest.mark.asyncio
async def test_discovery_uses_shared_analysis_and_challenge_with_citations():
    finding = {'answer': 'A supported opportunity', 'status': 'supported', 'evidence': [],
               'opportunities': [opportunity()]}
    result, model = await invoke('discovery', Client(), finding)
    assert model.calls == 2
    assert result['opportunities'][0]['ticker'] == 'AAA'
    assert result['coverage']['evaluated_tickers'] == ['AAA']


@pytest.mark.asyncio
async def test_unoffered_quote_becomes_insufficient_evidence():
    finding = {'answer': 'A claim', 'status': 'supported', 'evidence': [],
               'opportunities': [opportunity('Fabricated quote')]}
    result, _ = await invoke('discovery', Client(), finding)
    assert result['status'] == 'insufficient_evidence'
    assert result['opportunities'] == []


@pytest.mark.asyncio
async def test_empty_candidate_feed_never_calls_model():
    result, model = await invoke('discovery', Client(candidates=[]),
                                 {'answer': 'unused', 'status': 'no_opportunity'})
    assert result['status'] == 'no_opportunity'
    assert model.calls == 0


@pytest.mark.asyncio
async def test_research_answer_is_assembled_from_individually_cited_claims():
    evidence = reference(offered('news', 'news-AAA'))
    finding = {'answer': 'Unverified extra text', 'status': 'supported', 'evidence': [],
               'claims': [{'text': 'A supported fact', 'evidence': [evidence]}]}
    result, _ = await invoke('chat', Client(), finding)
    assert result['answer'] == 'A supported fact'
    assert result['evidence'] == [evidence]


@pytest.mark.asyncio
async def test_monitor_covers_more_than_five_stocks_across_runs():
    candidates = [Client.candidate(f'STOCK{i}') for i in range(7)]
    finding = {'answer': 'No opportunity', 'status': 'no_opportunity'}
    first, _ = await invoke('monitor', Client(candidates), finding, [item['ticker'] for item in candidates])
    second, _ = await invoke('monitor', Client(candidates, first['coverage']), finding,
                             [item['ticker'] for item in candidates])
    assert len(first['coverage']['evaluated_tickers']) == 5
    assert first['coverage']['partial'] is True
    assert len(second['coverage']['evaluated_tickers']) == 2
    assert second['coverage']['partial'] is False
    assert len(second['coverage']['evaluated_candidates']) == 7


@pytest.mark.asyncio
async def test_monitor_insufficient_evidence_preserves_completed_checkpoint():
    candidate = Client.candidate('AAA')
    baseline = {'evaluated_candidates': [], 'last_complete_ts': 123, 'next_ticker_offset': 0}
    finding = {'answer': 'No eligible evidence', 'status': 'insufficient_evidence'}
    result, _ = await invoke('monitor', Client([candidate], baseline), finding)
    assert result['coverage']['evaluated_candidates'] == []
    assert result['coverage']['last_complete_ts'] == 123
    assert result['coverage']['partial'] is True


@pytest.mark.asyncio
async def test_lost_lease_cancels_graph_without_completion(monkeypatch):
    cancelled = asyncio.Event()
    class Graph:
        async def ainvoke(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
    class LeaseClient:
        completed = False
        async def heartbeat(self, *args):
            raise PlatformCallError(409, 'Lease lost')
        async def complete(self, *args):
            self.completed = True
    monkeypatch.setattr('marketgraph_agents.worker.AGENTS', {'chat': lambda *args: Graph()})
    client = LeaseClient()
    await run_job(client, SimpleNamespace(heartbeat_seconds=0.01, deadline_seconds=2),
                  {'id': 'job', 'lease_token': 'lease', 'kind': 'chat', 'attempts': 1})
    assert cancelled.is_set()
    assert client.completed is False
