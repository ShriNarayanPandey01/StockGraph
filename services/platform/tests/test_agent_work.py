"""Leases and evidence are enforced independently of subscription access."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from marketgraph_platform.agent_api import AgentResult, context_sources
from marketgraph_platform.agent_repository import (
    WorkConflict,
    complete_job,
    fingerprint,
    leased_job,
    validate_result_evidence,
)
from marketgraph_platform.api import create_app
from marketgraph_platform.settings import Settings
from pydantic import ValidationError


def running_job():
    return {'id':uuid4(),'user_id':uuid4(),'state':'running','lease_token':uuid4(),
            'lease_until':datetime.now(UTC)+timedelta(minutes=5),'attempts':1,
            'kind':'chat','required_plan':'FREE',
            'input':{'tickers':['RELIANCE'],'window':'LAST_6M'}}


def reference(**changes):
    return {'kind':'news','id':'news-1','locator':None,'quote':'Demand increased',**changes}


def evidence_row(**changes):
    return {'ticker':'RELIANCE','evidence_id':'news-1','quote_text':'Demand increased by 10%.',
            'material_version':'version-1',**changes}


def result(**changes):
    return {'answer':'Demand improved according to the report.','status':'supported',
            'evidence':[reference()],'alerts':[],'reported_tokens':10,**changes}


def test_abstention_is_explicit_and_cannot_generate_alerts():
    assert AgentResult(answer='No eligible evidence was available.',status='insufficient_evidence').evidence == []
    with pytest.raises(ValidationError):
        AgentResult(answer='Buy now.',status='supported')
    with pytest.raises(ValidationError):
        AgentResult.model_validate(result(evidence=[reference(quote='')]))
    with pytest.raises(ValidationError):
        AgentResult.model_validate(result(status='insufficient_evidence',alerts=[{
            'ticker':'RELIANCE','event_id':'news-1','material_version':'version-1',
            'direction':'BULLISH','summary':'Demand improved','evidence':[reference()]}]))


@pytest.mark.asyncio
async def test_machine_routes_require_separate_service_credential():
    repo = AsyncMock()
    app = create_app(Settings(agent_service_key='machine-only'),repo,AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response = await client.post('/internal/v1/agent/jobs/claim',headers={'Authorization':'Bearer user-token'})
        assert response.status_code == 401
        response = await client.post('/internal/v1/agent/jobs/claim',headers={'X-Agent-Key':'wrong'})
        assert response.status_code == 401
    repo.authenticate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('state,expired,token_matches',[
    ('running',True,True),('pending',False,True),('running',False,False),('failed',False,True)])
async def test_stale_or_foreign_agent_cannot_use_lease(state,expired,token_matches):
    job = running_job()
    job['state'] = state
    if expired:
        job['lease_until'] = datetime.now(UTC)-timedelta(seconds=1)
    conn = AsyncMock()
    conn.fetchrow.return_value = job
    with pytest.raises(WorkConflict):
        await leased_job(conn,job['id'],job['lease_token'] if token_matches else uuid4())


@pytest.mark.asyncio
async def test_citations_require_server_supplied_exact_quotes_and_current_professional_publication():
    conn, job = AsyncMock(), running_job()
    conn.fetchrow.return_value = None
    with pytest.raises(WorkConflict,match='not supplied'):
        await validate_result_evidence(conn,job,job['lease_token'],result())
    conn.fetchrow.return_value = evidence_row()
    with pytest.raises(WorkConflict,match='exact excerpt'):
        await validate_result_evidence(conn,job,job['lease_token'],result(evidence=[reference(quote='Fabricated assertion')]))
    conn.fetchval.return_value = None
    with pytest.raises(WorkConflict,match='withdrawn'):
        await validate_result_evidence(conn,job,job['lease_token'],result(evidence=[reference(kind='professional',id=str(uuid4()))]))
    await validate_result_evidence(conn,job,job['lease_token'],result())


@pytest.mark.asyncio
async def test_alert_requires_canonical_source_identity_and_same_stock():
    job, conn = running_job(), AsyncMock()
    conn.fetchrow.return_value = evidence_row()
    alert = {'ticker':'RELIANCE','event_id':'fabricated-event','material_version':'version-1',
             'direction':'BULLISH','summary':'Demand improved','evidence':[reference()]}
    with pytest.raises(WorkConflict,match='identity'):
        await validate_result_evidence(conn,job,job['lease_token'],result(alerts=[alert]))
    alert['event_id'] = 'news-1'
    conn.fetchrow.return_value = evidence_row(ticker='TCS')
    with pytest.raises(WorkConflict,match='stock scope'):
        await validate_result_evidence(conn,job,job['lease_token'],result(alerts=[alert]))


class Pool:
    def __init__(self,conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class Conn:
    def __init__(self,job):
        self.job, self.writes = job, []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self,*args):
        query = args[0]
        if 'SELECT user_id FROM agent_jobs' in query:
            return {'user_id': self.job['user_id']}
        if 'FROM platform_users' in query:
            return {'id': self.job['user_id'], 'name':'Researcher', 'email':None,
                    'professional_verified':False,'is_developer':False,
                    'disabled':False,'roles':['USER'],'plan':'PRO','plan_expires_at':None,
                    'active_selection_initialized':False}
        if 'FROM platform_plan_policies' in query:
            return {'plan':'PRO','active_stock_limit':None,'monthly_alert_limit':None,
                    'features':{'professional_evidence':True,'research_chat':True,
                                'discovery':True,'opportunity_alerts':True,
                                'stock_connections':True,'monitoring':True,
                                'market_monitoring':True},'revision':1}
        return self.job

    async def fetch(self,*args):
        return []

    async def fetchval(self,*args):
        return self.job['user_id']

    async def execute(self,*args):
        self.writes.append(args)


@pytest.mark.asyncio
async def test_duplicate_completion_returns_original_without_writing_or_consuming_again():
    job = running_job()
    job.update(state='completed',result_fingerprint=fingerprint(result()))
    conn = Conn(job)
    assert (await complete_job(Pool(conn),job['id'],job['lease_token'],result()))['id'] == job['id']
    assert not conn.writes
    with pytest.raises(WorkConflict,match='different result'):
        await complete_job(Pool(conn),job['id'],job['lease_token'],result(answer='Changed answer'))


def test_context_source_collection_does_not_turn_unattributed_numbers_into_evidence():
    financials = {'daily_metrics':[{'close_price':42},{'vendor_id':'upstox','vendor_as_of':'2026-10-24T10:00:00Z','close_price':43}]}
    sources = context_sources('RELIANCE',{'direct_news':[{'id':'news-1','headline':'Demand increased'}]},[],financials)
    assert [source['kind'] for source in sources] == ['news','financial']
    assert 'vendor_id' in sources[1]['quote_text']
