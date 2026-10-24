"""Leases and evidence are enforced independently of subscription access."""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import httpx
import pytest
from marketgraph_platform.agent_api import AgentResult, context_sources
from marketgraph_platform.agent_repository import (
    WorkConflict,
    claim_job,
    complete_job,
    create_job,
    fail_job,
    fingerprint,
    leased_job,
    register_evidence,
    reserve_tool_call,
    validate_result_evidence,
)
from marketgraph_platform.api import create_app
from marketgraph_platform.auth import token_digest
from marketgraph_platform.repository import Repository
from marketgraph_platform.settings import Settings
from pydantic import ValidationError


def running_job():
    return {'id':uuid4(),'user_id':uuid4(),'state':'running','lease_token':uuid4(),
            'lease_until':datetime.now(UTC)+timedelta(minutes=5),'attempts':1,
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
        return self.job

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


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('PLATFORM_TEST_DATABASE_DSN'),reason='Set PLATFORM_TEST_DATABASE_DSN for live queue/transaction checks')
async def test_postgres_lease_ownership_alert_dedup_and_completion_idempotence():
    dsn, schema = os.environ['PLATFORM_TEST_DATABASE_DSN'], 'agent_test_'+uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    repo = Repository(Settings())
    try:
        repo.pool = await asyncpg.create_pool(dsn,min_size=1,max_size=3,server_settings={'search_path':schema})
        await repo.migrate()
        owner = await repo.provision_user('Owner',token_digest('owner'))
        outsider = await repo.provision_user('Other',token_digest('other'))
        conversation = uuid4()
        await repo.pool.execute('INSERT INTO conversations(id,user_id,title) VALUES($1,$2,$3)',conversation,owner,'Research')
        with pytest.raises(WorkConflict,match='owned'):
            await create_job(repo.pool,outsider,'chat',{'tickers':['RELIANCE'],'conversation_id':str(conversation)},'foreign')
        payload = {'tickers':['RELIANCE'],'question':'Demand?','window':'LAST_6M'}
        created = await create_job(repo.pool,owner,'discovery',payload,'request-1')
        duplicate = await create_job(repo.pool,owner,'discovery',payload,'request-1')
        assert duplicate['id'] == created['id']
        claimed = await claim_job(repo.pool,Settings())
        with pytest.raises(WorkConflict):
            await complete_job(repo.pool,claimed['id'],uuid4(),result())
        offered = await register_evidence(repo.pool,claimed['id'],claimed['lease_token'],[
            {'kind':'news','id':'news-1','ticker':'RELIANCE','source':{'id':'news-1'},'quote_text':'Demand increased by 10%.'}])
        alert = {'ticker':'RELIANCE','event_id':'news-1','material_version':offered[0]['material_version'],
                 'direction':'BULLISH','summary':'Demand improved','evidence':[reference()]}
        completed = result(alerts=[alert])
        await complete_job(repo.pool,claimed['id'],claimed['lease_token'],completed)
        await complete_job(repo.pool,claimed['id'],claimed['lease_token'],completed)
        assert await repo.pool.fetchval('SELECT count(*) FROM opportunity_alerts WHERE user_id=$1',owner) == 1
        assert await repo.pool.fetchval('SELECT count(*) FROM opportunity_alerts WHERE user_id=$1',outsider) == 0
        assert await repo.pool.fetchval("SELECT amount FROM agent_usage WHERE job_id=$1 AND metric='completed_jobs'",claimed['id']) == 1
        # A separate job finding the same material cannot redeliver the opportunity.
        await create_job(repo.pool,owner,'discovery',payload,'request-2')
        second = await claim_job(repo.pool,Settings())
        await register_evidence(repo.pool,second['id'],second['lease_token'],[
            {'kind':'news','id':'news-1','ticker':'RELIANCE','source':{'id':'news-1'},'quote_text':'Demand increased by 10%.'}])
        await complete_job(repo.pool,second['id'],second['lease_token'],completed)
        assert await repo.pool.fetchval('SELECT count(*) FROM opportunity_alerts') == 1
        # Atomic tool budget is unchanged by plan tier.
        await create_job(repo.pool,owner,'discovery',payload,'request-3')
        third = await claim_job(repo.pool,Settings())
        for _ in range(100):
            await reserve_tool_call(repo.pool,third['id'],third['lease_token'],'test-agent')
        with pytest.raises(WorkConflict,match='budget'):
            await reserve_tool_call(repo.pool,third['id'],third['lease_token'],'test-agent')
        await fail_job(repo.pool,third['id'],third['lease_token'],True,3,'test-agent')
        reclaimed = await claim_job(repo.pool,Settings())
        assert reclaimed['lease_token'] != third['lease_token']
        with pytest.raises(WorkConflict):
            await leased_job(repo.pool,third['id'],third['lease_token'])
    finally:
        await repo.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
