"""Job lifecycle rechecks access and allocates durable alerts without paid services."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from marketgraph_platform import agent_repository as jobs
from marketgraph_platform.entitlements import Access
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import PlatformError
from marketgraph_platform.settings import Settings


def access_for(user_id, *, pro=False, developer=False, initialized=True, disabled=False):
    user = Principal(id=user_id, name='Researcher', plan='PRO' if pro else 'FREE',
                     is_developer=developer, active_selection_initialized=initialized, disabled=disabled)
    features = dict.fromkeys(('research_chat', 'monitoring', 'opportunity_alerts'), True)
    features.update(discovery=pro, market_monitoring=pro, professional_evidence=pro)
    return Access(user, {'features': features, 'monthly_alert_limit': None if pro else 10}, ('TCS',))


def job_for(user_id, **changes):
    return {'id': uuid4(), 'user_id': user_id, 'actor_id': None, 'kind': 'chat', 'state': 'running',
            'required_plan': 'FREE', 'lease_token': uuid4(), 'attempts': 1,
            'lease_until': datetime.now(UTC) + timedelta(minutes=5),
            'input': {'question': 'Evidence?', 'tickers': ['TCS'], 'window': 'LAST_6M'}, **changes}


def alert_for(event):
    return {'ticker': 'TCS', 'event_id': event, 'material_version': 'v1', 'direction': 'BULLISH',
            'summary': 'Reported demand increased', 'evidence': []}


def answer(alerts):
    return {'answer': 'Source-backed response', 'status': 'supported', 'evidence': [],
            'alerts': alerts, 'reported_tokens': 5}


class Database:
    def __init__(self, *records, used=0):
        self.jobs = {row['id']: row for row in records}
        self.used = used
        self.alerts = set()
        self.writes = []
        self.monitors = {}
        self.lock = asyncio.Lock()
        self.pending_count = 0

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        # Models the user-row serialization boundary without requiring a live DB.
        async with self.lock:
            yield self

    async def fetch(self, sql, *args):
        if 'FROM monitors' in sql:
            return [{'id': row['id'], 'user_id': row['user_id']} for row in self.monitors.values()]
        if 'FROM agent_jobs' in sql:
            return [{'id': row['id'], 'user_id': row['user_id']} for row in self.jobs.values()
                    if row['state'] == 'pending']
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if sql.startswith('SELECT user_id FROM agent_jobs'):
            row = self.jobs.get(args[0])
            return {'user_id': row['user_id']} if row else None
        if sql.startswith('SELECT * FROM agent_jobs WHERE user_id'):
            return next((row.copy() for row in self.jobs.values()
                         if row['user_id'] == args[0] and row.get('request_key') == args[1]), None)
        if sql.startswith('SELECT * FROM agent_jobs WHERE id'):
            return self.jobs[args[0]].copy()
        if sql.startswith('INSERT INTO agent_jobs'):
            row = job_for(args[1], id=args[0], kind=args[2], input=json.loads(args[3]),
                          request_key=args[4], fingerprint=args[5], required_plan=args[6], actor_id=args[7])
            self.jobs[row['id']] = row
            self.writes.append((sql, args))
            return row.copy()
        if sql.startswith('UPDATE agent_jobs'):
            row = self.jobs[args[0]]
            if "state='completed'" in sql:
                row.update(state='completed', result=json.loads(args[1]), result_fingerprint=args[2])
            elif "state='running'" in sql:
                row.update(state='running', lease_token=args[1], attempts=row['attempts'] + 1)
            self.writes.append((sql, args))
            return row.copy()
        if sql.startswith('SELECT m.*'):
            return self.monitors.get(args[0])
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql.startswith('SELECT id FROM platform_users'):
            return args[0]
        if sql.startswith('SELECT count(*) FROM opportunity_alerts'):
            return self.used
        if sql.startswith('SELECT count(*) FROM agent_jobs'):
            return self.pending_count
        if sql.startswith('SELECT EXISTS(SELECT 1 FROM opportunity_alerts'):
            return args[1] in self.alerts
        if sql.startswith('INSERT INTO opportunity_alerts'):
            if args[7] in self.alerts:
                return None
            self.alerts.add(args[7])
            self.used += 1
            self.writes.append((sql, args))
            return args[0]
        if sql.startswith('INSERT INTO agent_jobs'):
            self.writes.append((sql, args))
            return args[0]
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.writes.append((sql, args))
        if sql.startswith('UPDATE agent_jobs SET required_plan'):
            self.jobs[args[0]]['required_plan'] = 'PRO'
        if sql.startswith("UPDATE agent_jobs SET state='cancelled'"):
            self.jobs[args[0]]['state'] = 'cancelled'


def install_access(monkeypatch, *accesses):
    by_user = {access.user.id: access for access in accesses}

    async def load(conn, user_id, *, lock=False):
        return by_user[user_id]

    monkeypatch.setattr('marketgraph_platform.entitlements.load_access', load)
    return by_user


@pytest.mark.asyncio
async def test_quota_suppression_completes_research_and_retries_original_request(monkeypatch):
    user_id = uuid4()
    row = job_for(user_id)
    db = Database(row, used=9)
    install_access(monkeypatch, access_for(user_id))
    monkeypatch.setattr(jobs, 'validate_result_evidence', AsyncMock())
    duplicate, new, excess = (alert_for(value) for value in ('already-sent', 'new', 'excess'))
    db.alerts.add(jobs.fingerprint({key: duplicate[key] for key in ('ticker', 'event_id', 'material_version')}))
    request = answer([duplicate, new, excess, excess])
    completed = await jobs.complete_job(db, row['id'], row['lease_token'], request)
    assert db.used == 10
    assert completed['result']['alerts'] == [new]
    assert completed['result']['alerts_created'] == 1
    assert completed['result']['alerts_suppressed'] == 1
    assert completed['result_fingerprint'] == jobs.fingerprint(request)
    writes = len(db.writes)
    assert await jobs.complete_job(db, row['id'], row['lease_token'], request) == completed
    assert len(db.writes) == writes


@pytest.mark.asyncio
async def test_current_access_blocks_completed_premium_results_after_downgrade(monkeypatch):
    user_id = uuid4()
    request = answer([])
    row = job_for(user_id, state='completed', required_plan='PRO', result_fingerprint=jobs.fingerprint(request))
    db = Database(row)
    install_access(monkeypatch, access_for(user_id))
    with pytest.raises(PlatformError, match='Pro'):
        await jobs.complete_job(db, row['id'], row['lease_token'], request)
    assert not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize('developer,pro', [(True, False), (False, True)])
async def test_developer_and_pro_do_not_have_free_alert_ceiling(monkeypatch, developer, pro):
    user_id = uuid4()
    row = job_for(user_id)
    db = Database(row, used=100)
    install_access(monkeypatch, access_for(user_id, developer=developer, pro=pro))
    monkeypatch.setattr(jobs, 'validate_result_evidence', AsyncMock())
    completed = await jobs.complete_job(db, row['id'], row['lease_token'], answer([alert_for('one'), alert_for('two')]))
    assert completed['result']['alerts_created'] == 2
    assert completed['result']['alerts_suppressed'] == 0


@pytest.mark.asyncio
async def test_free_jobs_cannot_register_professional_sources_and_pro_jobs_stay_tainted(monkeypatch):
    user_id = uuid4()
    row = job_for(user_id)
    db = Database(row)
    accesses = install_access(monkeypatch, access_for(user_id))
    entry = {'kind': 'professional', 'id': str(uuid4()), 'ticker': 'TCS', 'source': {},
             'quote_text': 'Reviewed professional view'}
    with pytest.raises(PlatformError, match='Pro'):
        await jobs.register_evidence(db, row['id'], row['lease_token'], [entry])
    assert not db.writes
    accesses[user_id] = access_for(user_id, pro=True)
    offered = await jobs.register_evidence(db, row['id'], row['lease_token'], [entry])
    assert len(offered) == 1 and db.jobs[row['id']]['required_plan'] == 'PRO'


@pytest.mark.asyncio
async def test_claim_cancels_work_no_longer_permitted(monkeypatch):
    user_id = uuid4()
    row = job_for(user_id, kind='discovery', state='pending', required_plan='PRO')
    db = Database(row)
    install_access(monkeypatch, access_for(user_id))
    assert await jobs.claim_job(db, Settings(_env_file=None)) is None
    assert db.jobs[row['id']]['state'] == 'cancelled'


@pytest.mark.asyncio
async def test_developer_admission_bypasses_owner_queue_limit_and_preserves_owner(monkeypatch):
    owner, developer = uuid4(), uuid4()
    db = Database()
    db.pending_count = 1000
    install_access(monkeypatch, access_for(owner), access_for(developer, developer=True))
    row = await jobs.create_job(db, owner, 'discovery', {'tickers': []}, 'dev-request', actor_id=developer)
    assert row['user_id'] == owner and row['actor_id'] == developer and row['required_plan'] == 'PRO'
    assert any('platform_admin_audit' in sql for sql, _ in db.writes)
    with pytest.raises(PlatformError, match='Pro'):
        await jobs.create_job(db, owner, 'discovery', {'tickers': []}, 'ordinary-request')


@pytest.mark.asyncio
async def test_monitor_uses_only_current_free_selection_and_pauses_uninitialized_owner(monkeypatch):
    owner = uuid4()
    db = Database()
    monitor = {'id': uuid4(), 'user_id': owner, 'actor_id': None, 'scope': 'watchlist',
               'tickers': ['TCS', 'INFY'], 'question': 'Material changes?',
               'next_run_at': datetime.now(UTC), 'interval_seconds': 3600}
    db.monitors[monitor['id']] = monitor
    accesses = install_access(monkeypatch, access_for(owner))
    assert await jobs.schedule_due_monitors(db, Settings(_env_file=None)) == 1
    inserts = [(sql, args) for sql, args in db.writes if sql.startswith('INSERT INTO agent_jobs')]
    assert json.loads(inserts[0][1][2])['tickers'] == ['TCS']
    accesses[owner] = access_for(owner, initialized=False)
    db.writes.clear()
    assert await jobs.schedule_due_monitors(db, Settings(_env_file=None)) == 0
    assert any('pause_reason=' in sql for sql, _ in db.writes)
    assert not any(sql.startswith('INSERT INTO agent_jobs') for sql, _ in db.writes)


@pytest.mark.asyncio
async def test_serialized_completions_share_the_last_monthly_alert_slot(monkeypatch):
    owner = uuid4()
    first, second = job_for(owner), job_for(owner)
    db = Database(first, second, used=9)
    install_access(monkeypatch, access_for(owner))
    monkeypatch.setattr(jobs, 'validate_result_evidence', AsyncMock())
    completed = await asyncio.gather(
        jobs.complete_job(db, first['id'], first['lease_token'], answer([alert_for('first')])),
        jobs.complete_job(db, second['id'], second['lease_token'], answer([alert_for('second')])))
    assert db.used == 10
    assert sum(row['result']['alerts_created'] for row in completed) == 1
    assert sum(row['result']['alerts_suppressed'] for row in completed) == 1
    assert all(row['state'] == 'completed' for row in completed)


@pytest.mark.asyncio
async def test_revoked_developer_initiator_cannot_complete_on_behalf_of_owner(monkeypatch):
    owner, developer = uuid4(), uuid4()
    row = job_for(owner, actor_id=developer, required_plan='PRO')
    db = Database(row)
    install_access(monkeypatch, access_for(owner), access_for(developer, developer=True, disabled=True))
    with pytest.raises(PlatformError, match='initiator'):
        await jobs.complete_job(db, row['id'], row['lease_token'], answer([]))
    assert not db.writes
