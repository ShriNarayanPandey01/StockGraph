"""Opt-in PostgreSQL integration tests; target only a disposable local database."""

import asyncio
import hashlib
import io
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import asyncpg
import httpx
import pytest
import pytest_asyncio
from marketgraph_agents.models import ModelFinding
from marketgraph_agents.transport import HttpPlatformClient
from marketgraph_agents.worker import run_job
from marketgraph_platform.agent_api import (
    AgentResultV2,
    ModelReservationInput,
    ModelSettlementInput,
)
from marketgraph_platform.agent_budget import reserve, settle
from marketgraph_platform.agent_repository import (
    WorkConflict,
    complete_job,
    fingerprint,
    register_evidence,
)
from marketgraph_platform.api import create_app
from marketgraph_platform.auth import current_user
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import Repository
from marketgraph_platform.settings import Settings
from pydantic import SecretStr

from scripts import platform_data

DSN = os.getenv('STOCKGRAPH_TEST_AGENT_DSN', '')
pytestmark = pytest.mark.skipif(not DSN, reason='Requires a disposable isolated agent_test database')


@pytest_asyncio.fixture
async def repo():
    parsed = urlsplit(DSN)
    if parsed.hostname not in {'localhost', '127.0.0.1'} or parsed.path != '/agent_test' or parsed.port in (None, 5432):
        pytest.fail('Integration test target must be an isolated local agent_test database on a non-default port')
    settings = Settings(_env_file=None, database_dsn=DSN, agent_model_id='test-model',
                        agent_input_usd_per_million=100, agent_output_usd_per_million=100,
                        agent_monthly_usd_cap=0.30, agent_job_usd_cap=0.25)
    repository = Repository(settings)
    schema = 'platform_restore_test_' + uuid4().hex[:20]
    admin = await asyncpg.connect(DSN)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    repository.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=10,
                                                server_settings={'search_path': schema})
    repository.test_schema = schema
    await repository.migrate()
    try:
        yield repository
    finally:
        await repository.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


async def create_job(repo, *, kind='chat', monitor_id=None):
    user_id = await repo.pool.fetchval('SELECT id FROM platform_users WHERE is_developer')
    job_id, lease = uuid4(), uuid4()
    if user_id is None:
        user_id = uuid4()
        await repo.pool.execute(
            "INSERT INTO platform_users(id,name,is_developer,roles,plan,active_selection_initialized) "
            "VALUES($1,'Developer',true,'[\"USER\"]'::jsonb,'PRO',true)", user_id)
    if monitor_id:
        await repo.pool.execute(
            "INSERT INTO monitors(id,user_id,watchlist_id,question,interval_seconds,scope,active) "
            "VALUES($1,$2,NULL,'Monitor events',3600,'market',true)", monitor_id, user_id)
    data = {'question': 'Research', 'tickers': ['AAA'], 'window': 'LAST_6M'}
    if monitor_id:
        data.update(monitor_id=str(monitor_id), scope='market')
    await repo.pool.execute(
        "INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint,state,attempts,lease_token,lease_until,required_plan,contract_version) "
        "VALUES($1,$2,$3,$4::jsonb,$5,$6,'running',1,$7,now()+interval '5 minutes','PRO',2)",
        job_id, user_id, kind, json.dumps(data), str(uuid4()), str(uuid4()), lease)
    return user_id, job_id, lease


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_exceed_monthly_cap(repo):
    _, first, first_lease = await create_job(repo)
    _, second, second_lease = await create_job(repo)
    bodies = [ModelReservationInput(request_key=uuid4(), model='test-model', input_tokens=1000, output_tokens=1000)
              for _ in range(2)]
    outcomes = await asyncio.gather(
        reserve(repo.pool, first, first_lease, bodies[0], repo.settings),
        reserve(repo.pool, second, second_lease, bodies[1], repo.settings), return_exceptions=True)
    assert sum(isinstance(item, WorkConflict) for item in outcomes) == 1
    accepted = next(item for item in outcomes if isinstance(item, dict))
    winner, lease, body = (first, first_lease, bodies[0]) if accepted['job_id'] == first else (second, second_lease, bodies[1])
    assert (await reserve(repo.pool, winner, lease, body, repo.settings))['id'] == accepted['id']
    settled = await settle(repo.pool, winner, lease, accepted['id'], ModelSettlementInput(input_tokens=100, output_tokens=100))
    assert str(settled['charged_usd']) == '0.020000000'
    with pytest.raises(WorkConflict, match='different usage'):
        await settle(repo.pool, winner, lease, accepted['id'], ModelSettlementInput(input_tokens=101, output_tokens=100))


@pytest.mark.asyncio
async def test_monitor_completion_deduplicates_and_persists_evaluation(repo):
    monitor_id = uuid4()
    user_id, job_id, lease = await create_job(repo, kind='monitor', monitor_id=monitor_id)
    now = int(datetime.now(UTC).timestamp())
    entries = [
        {'kind': 'news', 'id': 'news-1', 'ticker': 'AAA', 'quote_text': 'Event reported', 'source': {'event_ts': now}},
        {'kind': 'graph', 'id': 'edge-1', 'ticker': 'AAA', 'quote_text': 'Direct impact',
         'source': {'source': 'NewsEvent:news-1', 'target': 'Stock:AAA', 'relation': 'DIRECTLY_IMPACTS', 'confidence': 0.9}},
        {'kind': 'financial', 'id': 'financial-1', 'ticker': 'AAA', 'quote_text': 'Financial source', 'source': {'vendor_id': 'vendor'}},
    ]

    async def complete(current_job, current_lease):
        evidence = await register_evidence(repo.pool, current_job, current_lease, entries)
        refs = [{**{k: item[k] for k in ('kind', 'id', 'ticker', 'locator', 'material_version')},
                 'quote': item['quote_text']} for item in evidence]
        candidate = {'ticker': 'AAA', 'event_id': 'news-1', 'material_version': refs[0]['material_version']}
        await repo.pool.execute('INSERT INTO agent_candidate_snapshots(job_id,as_of_ts,items) VALUES($1,$2,$3::jsonb)',
                                current_job, now, json.dumps([candidate]))
        key = fingerprint(['AAA', 'news-1', refs[0]['material_version']])
        body = AgentResultV2.model_validate({'answer': 'Opportunity', 'status': 'supported',
            'opportunities': [{'ticker': 'AAA', 'direction': 'BULLISH', 'horizon_sessions': 10,
                'title': 'Catalyst', 'thesis': 'Supported thesis', 'why_now': 'Recent event',
                'risks': 'Demand may fall', 'invalidation': 'Demand falls', 'catalyst': refs[0],
                'connections': [refs[1]], 'corroboration': [refs[2]], 'counter_evidence': []}],
            'coverage': {'as_of_ts': now, 'candidates_total': 1, 'evaluated_tickers': ['AAA'],
                         'evaluated_candidates': [key], 'partial': False, 'last_complete_ts': now}})
        raw = body.model_dump(mode='json')
        return await complete_job(repo.pool, current_job, current_lease, raw, repo.settings), raw

    first, first_body = await complete(job_id, lease)
    assert first['result']['alerts_created'] == 1
    assert (await complete_job(repo.pool, job_id, lease, first_body, repo.settings))['id'] == job_id
    second, second_lease = uuid4(), uuid4()
    original_input = await repo.pool.fetchval('SELECT input FROM agent_jobs WHERE id=$1', job_id)
    await repo.pool.execute(
        "INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint,state,attempts,lease_token,lease_until,required_plan,contract_version) "
        "VALUES($1,$2,'monitor',$3::jsonb,$4,$5,'running',1,$6,now()+interval '5 minutes','PRO',2)",
        second, user_id, original_input, str(uuid4()), str(uuid4()), second_lease)
    repeated, _ = await complete(second, second_lease)
    assert repeated['result']['alerts_created'] == 0
    assert await repo.pool.fetchval('SELECT count(*) FROM opportunity_alerts WHERE user_id=$1', user_id) == 1
    assert await repo.pool.fetchval('SELECT count(*) FROM agent_monitor_evaluations WHERE monitor_id=$1', monitor_id) == 2


@pytest.mark.asyncio
async def test_discovery_graph_completes_through_leased_platform_http(repo, monkeypatch):
    _, job_id, _ = await create_job(repo, kind='discovery')
    await repo.pool.execute("UPDATE agent_jobs SET state='pending',attempts=0,lease_token=NULL,lease_until=NULL WHERE id=$1", job_id)
    now = int(datetime.now(UTC).timestamp())
    news = {'id': 'news-1', 'headline': 'Event reported', 'event_ts': now}
    edge = {'id': 'edge-1', 'source': 'NewsEvent:news-1', 'target': 'Stock:AAA',
            'relation': 'DIRECTLY_IMPACTS', 'confidence': 0.9, 'rationale': 'Direct impact'}
    material = fingerprint({'kind': 'news', 'id': 'news-1', 'ticker': 'AAA', 'text': 'Event reported', 'locator': ''})

    async def graph_post(request, path, payload):
        return {'items': [{'ticker': 'AAA', 'event_id': 'news-1', 'event_ts': now,
                           'material_version': material, 'path_kind': 'direct'}], 'truncated': False}

    async def graph_get(request, path, params):
        if path.endswith('/documents/search'):
            return {'items': []}
        return {'direct_news': [news], 'indirect_news': [], 'edges': [edge]}

    class DataClient:
        async def get(self, path, params=None):
            return {'daily_metrics': [{'vendor_id': 'test', 'vendor_as_of': '2026-10-31', 'close_price': 100}]}

    class Model:
        reported_tokens = 0
        def __init__(self, *args):
            pass
        async def complete(self, prompt):
            packet = json.loads(prompt.split('\n', 1)[1])
            refs = {item['kind']: {**{k: item[k] for k in ('kind', 'id', 'ticker', 'locator', 'material_version')},
                                    'quote': item['quote_text']} for item in packet['evidence']}
            return ModelFinding.model_validate({'answer': 'Supported idea', 'status': 'supported',
                'opportunities': [{'ticker': 'AAA', 'direction': 'BULLISH', 'horizon_sessions': 10,
                    'title': 'Catalyst', 'thesis': 'Supported thesis', 'why_now': 'Recent event',
                    'risks': 'Demand may fall', 'invalidation': 'Demand falls', 'catalyst': refs['news'],
                    'connections': [refs['graph']], 'corroboration': [refs['financial']], 'counter_evidence': []}]})

    monkeypatch.setattr('marketgraph_platform.connections_api.graph_post', graph_post)
    monkeypatch.setattr('marketgraph_platform.agent_api.graph_get', graph_get)
    monkeypatch.setattr('marketgraph_agents.worker.ReservedModel', Model)
    repo.settings.agent_service_key = SecretStr('isolated-test-key')
    app = create_app(repo.settings, repo, DataClient())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://platform',
                                 headers={'X-Agent-Key': 'isolated-test-key'}) as http:
        client = HttpPlatformClient('http://platform', 'isolated-test-key', client=http)
        claimed = (await client.claim())['job']
        assert claimed['id'] == str(job_id)
        await run_job(client, SimpleNamespace(heartbeat_seconds=0.1, deadline_seconds=30), claimed)
    record = await repo.pool.fetchrow('SELECT state,result FROM agent_jobs WHERE id=$1', job_id)
    result = json.loads(record['result'])
    assert record['state'] == 'completed'
    assert result['opportunities'][0]['ticker'] == 'AAA'
    assert result['coverage']['partial'] is False


@pytest.mark.asyncio
async def test_pre_agent_backup_restores_into_new_schema(repo, tmp_path):
    """A reset backup made before migration 005 stays recoverable."""
    old_schema = 'platform_restore_test_' + uuid4().hex[:20]
    conn = await asyncpg.connect(DSN)
    await conn.execute(f'CREATE SCHEMA "{old_schema}"')
    await conn.execute(f'SET search_path TO "{old_schema}"')
    try:
        await conn.execute('CREATE TABLE platform_schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz DEFAULT now())')
        checksums = platform_data.migration_checksums()
        for path in sorted(platform_data.MIGRATIONS.glob('*.sql')):
            if path.name == '005_agent_runtime.sql':
                continue
            await conn.execute(path.read_text(encoding='utf-8'))
            await conn.execute('INSERT INTO platform_schema_migrations(name,checksum) VALUES($1,$2)', path.name, checksums[path.name])
        user_id, job_id = uuid4(), uuid4()
        await conn.execute("INSERT INTO platform_users(id,name) VALUES($1,'Backup fixture')", user_id)
        await conn.execute(
            "INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint) VALUES($1,$2,'chat','{}'::jsonb,'key','hash')",
            job_id, user_id)
        manifest = {'format': 1, 'database': 'marketgraph_platform',
                    'migrations': {k: v for k, v in checksums.items() if k != '005_agent_runtime.sql'}, 'tables': {}}
        path = tmp_path / 'legacy-platform.zip'
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for table in platform_data.TABLES:
                if table in platform_data.AGENT_RUNTIME_TABLES:
                    continue
                columns = await platform_data._columns(conn, table, old_schema)
                buffer = io.BytesIO()
                await conn.copy_from_table(table, schema_name=old_schema, output=buffer, format='binary')
                body = buffer.getvalue()
                archive.writestr(f'sql/{table}.copy', body)
                manifest['tables'][table] = {'columns': columns, 'sha256': hashlib.sha256(body).hexdigest(),
                                             'rows': await conn.fetchval(f'SELECT count(*) FROM "{old_schema}"."{table}"')}
            archive.writestr('manifest.json', json.dumps(manifest))
        async with repo.pool.acquire() as target:
            await platform_data.restore_connection(target, path, schema=repo.test_schema)
            assert await target.fetchval('SELECT name FROM platform_users WHERE id=$1', user_id) == 'Backup fixture'
            assert await target.fetchval('SELECT contract_version FROM agent_jobs WHERE id=$1', job_id) == 1
            assert await target.fetchval('SELECT count(*) FROM agent_model_reservations') == 0
    finally:
        await conn.execute('SET search_path TO public')
        await conn.execute(f'DROP SCHEMA "{old_schema}" CASCADE')
        await conn.close()


@pytest.mark.asyncio
async def test_withdrawn_professional_evidence_is_hidden_from_jobs_messages_and_alerts(repo):
    user_id, job_id, _ = await create_job(repo)
    conversation_id, message_id, alert_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    citation = {'kind': 'professional', 'id': str(version_id), 'locator': None, 'quote': 'Old professional view'}
    result = {'answer': 'Historical claim', 'status': 'supported', 'evidence': [citation]}
    await repo.pool.execute("UPDATE agent_jobs SET state='completed',result=$2::jsonb WHERE id=$1", job_id, json.dumps(result))
    await repo.pool.execute("INSERT INTO conversations(id,user_id,title) VALUES($1,$2,'History')", conversation_id, user_id)
    await repo.pool.execute("INSERT INTO research_messages(id,conversation_id,user_id,role,content,evidence,required_plan) "
                            "VALUES($1,$2,$3,'assistant','Historical claim',$4::jsonb,'PRO')",
                            message_id, conversation_id, user_id, json.dumps([citation]))
    await repo.pool.execute("INSERT INTO opportunity_alerts(id,user_id,job_id,ticker,direction,summary,evidence,dedupe_key,required_plan) "
                            "VALUES($1,$2,$3,'AAA','BULLISH','Historical claim',$4::jsonb,'stale','PRO')",
                            alert_id, user_id, job_id, json.dumps([citation]))
    app = create_app(repo.settings, repo, SimpleNamespace())
    async def developer():
        return Principal(id=user_id, name='Developer', is_developer=True, plan='PRO')
    app.dependency_overrides[current_user] = developer
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://platform') as client:
        job = (await client.get(f'/api/v1/agent-jobs/{job_id}')).json()
        messages = (await client.get(f'/api/v1/conversations/{conversation_id}/messages')).json()['items']
        alerts = (await client.get('/api/v1/alerts')).json()['items']
        assert job['evidence_stale'] is True and 'result' not in job
        assert messages[0]['evidence_stale'] is True and 'content' not in messages[0]
        assert alerts[0]['evidence_stale'] is True and 'summary' not in alerts[0]
        assert (await client.get(f'/api/v1/agent-jobs/{job_id}/evidence')).status_code == 409
