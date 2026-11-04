"""Evidence and provenance checks for v2 agent results."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from marketgraph_platform.agent_api import AgentResultV2, context_sources
from marketgraph_platform.agent_budget import estimate
from marketgraph_platform.agent_repository import WorkConflict, fingerprint
from marketgraph_platform.agent_results import prepare_v2
from pydantic import ValidationError


def ref(kind, identity, ticker='AAA', version='a' * 64, quote='supported'):
    return {'kind': kind, 'id': identity, 'ticker': ticker, 'material_version': version,
            'quote': quote, 'locator': None}


def opportunity():
    return {'ticker': 'AAA', 'direction': 'BULLISH', 'horizon_sessions': 10, 'title': 'Catalyst',
            'thesis': 'Supported thesis', 'why_now': 'Recent event', 'risks': 'Risk',
            'invalidation': 'Thesis fails', 'catalyst': ref('news', 'news-1'),
            'connections': [ref('graph', 'edge-1')], 'corroboration': [ref('financial', 'financial-1')],
            'counter_evidence': [], 'material_change': False, 'change_summary': ''}


def payload(now):
    return AgentResultV2.model_validate({'contract_version': 2, 'answer': 'Supported', 'status': 'supported',
        'evidence': [], 'opportunities': [opportunity()], 'coverage': {'as_of_ts': now, 'candidates_total': 1,
        'evaluated_tickers': ['AAA'], 'partial': False}}).model_dump(mode='json')


class Connection:
    def __init__(self, now):
        self.rows = {
            ('news', 'news-1', '', 'AAA'): {'quote_text': 'supported', 'material_version': 'a' * 64,
                                               'source': {'event_ts': now}},
            ('graph', 'edge-1', '', 'AAA'): {'quote_text': 'supported', 'material_version': 'a' * 64,
                'source': {'source': 'NewsEvent:news-1', 'target': 'Stock:AAA',
                           'relation': 'DIRECTLY_IMPACTS', 'confidence': 0.9}},
            ('financial', 'financial-1', '', 'AAA'): {'quote_text': 'supported', 'material_version': 'a' * 64,
                                                         'source': {'vendor_id': 'vendor'}}}
        self.snapshot = {'as_of_ts': now, 'truncated': False, 'items': [
            {'ticker': 'AAA', 'event_id': 'news-1', 'material_version': 'a' * 64}]}

    async def fetchrow(self, sql, *args):
        if 'FROM job_evidence' in sql:
            return self.rows.get(tuple(args[1:5]))
        if 'FROM agent_candidate_snapshots' in sql:
            return self.snapshot
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        return None


def job():
    return {'id': uuid4(), 'kind': 'discovery', 'input': {'tickers': ['AAA']}}


@pytest.mark.asyncio
async def test_valid_opportunity_requires_a_cited_connected_graph_path():
    now = int(datetime.now(UTC).timestamp())
    conn = Connection(now)
    result = await prepare_v2(conn, job(), uuid4(), payload(now), 0.65, True)
    assert result['opportunities'][0]['ticker'] == 'AAA'
    assert result['alerts'] == []  # Discovery returns ideas; monitors create alerts.
    conn.rows[('graph', 'edge-1', '', 'AAA')]['source']['target'] = 'Stock:OTHER'
    with pytest.raises(WorkConflict, match='does not connect'):
        await prepare_v2(conn, job(), uuid4(), payload(now), 0.65, True)


@pytest.mark.asyncio
async def test_stale_or_fabricated_citations_are_rejected():
    now = int(datetime.now(UTC).timestamp())
    conn = Connection(now)
    data = payload(now)
    data['opportunities'][0]['catalyst']['quote'] = 'fabricated'
    with pytest.raises(WorkConflict, match='exact excerpt'):
        await prepare_v2(conn, job(), uuid4(), data, 0.65, True)
    conn.rows[('news', 'news-1', '', 'AAA')]['source']['event_ts'] = now - 72 * 3600 - 1
    with pytest.raises(WorkConflict, match='72-hour'):
        await prepare_v2(conn, job(), uuid4(), payload(now), 0.65, True)


def test_v2_rejects_same_news_as_corroboration_and_requires_matching_ticker():
    now = int(datetime.now(UTC).timestamp())
    data = payload(now)
    data['opportunities'][0]['corroboration'] = [ref('news', 'news-1')]
    with pytest.raises(ValidationError):
        AgentResultV2.model_validate(data)
    data = payload(now)
    data['opportunities'][0]['thesis'] = 'Enter near 100 and set a stop loss at 90.'
    with pytest.raises(ValidationError, match='Numerical trade'):
        AgentResultV2.model_validate(data)
    data = payload(now)
    data['opportunities'][0]['connections'][0]['ticker'] = 'OTHER'
    with pytest.raises(ValidationError):
        AgentResultV2.model_validate(data)


def test_source_registration_preserves_filing_provenance_and_graph_rationale():
    graph = {'edges': [{'id': 'edge-1', 'rationale': 'A cited connection'}]}
    financials = {'quarterly_financials': [{'source_id': 'BSE', 'source_as_of': '2026-10-01', 'revenue_cr': 42},
                                             {'revenue_cr': 99}]}
    sources = context_sources('AAA', graph, [], financials)
    assert [source['kind'] for source in sources] == ['graph', 'financial']
    assert json.loads(sources[1]['quote_text'])['source_id'] == 'BSE'
    assert fingerprint({'kind': 'news', 'id': 'x', 'ticker': 'AAA', 'text': 't', 'locator': ''})


def test_budget_estimate_rounds_up():
    assert estimate(1, 1, '0.001', '0.001') == Decimal('0.000000002')


@pytest.mark.asyncio
async def test_research_rejects_an_uncited_answer_and_revoked_professional():
    now = int(datetime.now(UTC).timestamp())
    conn = Connection(now)
    chat = {**job(), 'kind': 'chat'}
    citation = ref('news', 'news-1')
    data = AgentResultV2(answer='Unsupported extra text', status='supported',
                         evidence=[citation], claims=[{'text': 'A claim', 'evidence': [citation]}]).model_dump(mode='json')
    with pytest.raises(WorkConflict, match='individually cited'):
        await prepare_v2(conn, chat, uuid4(), data, 0.65, True)
    professional_id = str(uuid4())
    conn.rows[('professional', professional_id, '', 'AAA')] = {
        'quote_text': 'supported', 'material_version': 'a' * 64, 'source': {}}
    pro = ref('professional', professional_id)
    data = AgentResultV2(answer='A claim', status='supported',
                         evidence=[pro], claims=[{'text': 'A claim', 'evidence': [pro]}]).model_dump(mode='json')
    with pytest.raises(WorkConflict, match='withdrawn'):
        await prepare_v2(conn, chat, uuid4(), data, 0.65, True)
