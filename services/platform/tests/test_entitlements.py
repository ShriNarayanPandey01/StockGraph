"""Offline checks for access snapshots, selection changes and policy boundaries."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from marketgraph_platform.entitlements import Access, Entitlements, load_access, load_job_access
from marketgraph_platform.models import Principal
from marketgraph_platform.policy import FEATURES, access_policy, effective_plan, require_permission
from marketgraph_platform.repository import PlatformError, Repository
from marketgraph_platform.settings import Settings


def principal(**changes):
    return Principal(id=uuid4(),name='Reader',active_selection_initialized=True,**changes)


def policy(plan='FREE', **changes):
    return {'plan':plan,'active_stock_limit':10 if plan=='FREE' else None,
            'monthly_alert_limit':10 if plan=='FREE' else None,'revision':3,
            'features':{feature:plan=='PRO' or tier=='FREE' for feature,tier in FEATURES.items()},**changes}


def test_free_research_is_single_selected_stock_and_not_lifetime_usage():
    free=Access(principal(),policy(),('INFY','TCS'))
    assert free.require('research_chat',('INFY',),single=True) is free
    for tickers in [(),('INFY','TCS'),('RELIANCE',)]:
        with pytest.raises(PlatformError) as denied:
            free.require('research_chat',tickers,single=True)
        assert denied.value.status==403
    for feature in ['discovery','professional_evidence','market_monitoring']:
        with pytest.raises(PlatformError):
            free.require(feature,('INFY',))
    assert free.require('monitoring',('INFY','TCS')) is free
    assert free.require('stock_connections',('TCS',)) is free


def test_uninitialized_selection_is_not_implicitly_activated_by_reads():
    free=Access(principal().model_copy(update={'active_selection_initialized':False}),policy(),('INFY',))
    with pytest.raises(PlatformError):
        free.require('stock_connections',('INFY',))
    assert free.require() is free


def test_pro_expiry_changes_effective_plan_at_the_boundary():
    now=datetime.now(UTC)
    user=principal(plan='PRO',plan_expires_at=now)
    assert effective_plan(user,now)== 'FREE'
    assert effective_plan(user,now-timedelta(seconds=1))=='PRO'
    assert effective_plan(user,now+timedelta(seconds=1))=='FREE'
    pro=Access(principal(plan='PRO',plan_expires_at=now+timedelta(days=1)),policy('PRO'),())
    assert pro.require('discovery',('NOT_SELECTED','INFY')) is pro
    assert pro.require('research_chat',('INFY','TCS'),single=True) is pro
    expired=Access(user,policy(),('INFY',))
    with pytest.raises(PlatformError):
        expired.require('research_chat',('INFY','TCS'),single=True)


def test_developer_overrides_feature_policy_selection_and_product_limits():
    dev=principal(is_developer=True,plan='FREE',plan_expires_at=datetime.now(UTC)-timedelta(days=1))
    locked=policy(features={name:False for name in FEATURES},active_stock_limit=1,monthly_alert_limit=1)
    access=Access(dev,locked,())
    assert access.require('professional_evidence',('UNSELECTED',)) is access
    assert access.require('research_chat',('INFY','TCS'),single=True) is access
    value=access_policy(dev,locked)
    assert value['plan']=='PRO' and not value['quota_enforcement']
    assert all(item['allowed'] for item in value['features'].values())
    assert value['limits']['active_stocks'] is None and value['limits']['opportunity_alerts_per_month'] is None
    with pytest.raises(PlatformError):
        Access(dev.model_copy(update={'disabled':True}),locked,()).require()


def test_role_permissions_are_independent_of_subscription():
    pro=principal(plan='PRO')
    with pytest.raises(PlatformError):
        require_permission(pro,'review')
    with pytest.raises(PlatformError):
        require_permission(pro,'author')
    require_permission(principal(roles=['USER','REVIEWER']),'review')
    require_permission(principal(roles=['USER','PROFESSIONAL'],professional_verified=True),'author')
    with pytest.raises(PlatformError):
        require_permission(principal(roles=['USER','PROFESSIONAL']),'author')
    require_permission(principal(is_developer=True),'admin')


def test_job_access_rechecks_kind_scope_and_pro_provenance():
    free=Access(principal(),policy(),('INFY',))
    assert free.require_job({'kind':'monitor','input':json.dumps({'tickers':['INFY'],'scope':'watchlist'}),'required_plan':'FREE'}) is free
    for job in [
        {'kind':'discovery','input':{'tickers':['INFY']}},
        {'kind':'monitor','input':{'tickers':['INFY'],'scope':'market'}},
        {'kind':'chat','input':{'tickers':['INFY']},'required_plan':'PRO'},
        {'kind':'chat','input':{'tickers':['TCS']},'required_plan':'FREE'},
    ]:
        with pytest.raises(PlatformError):
            free.require_job(job)


def test_policy_handles_jsonb_strings_and_configured_feature_revocation():
    configured=policy(features=json.dumps({name:False for name in FEATURES}),monthly_alert_limit=4)
    value=access_policy(principal(),configured)
    assert not any(item['allowed'] for item in value['features'].values())
    assert value['limits']['opportunity_alerts_per_month']==4
    assert value['limits']['reset_timezone']=='Asia/Kolkata'
    assert value['policy_revision']==3
    access=Access(principal(plan='PRO'),policy('PRO',features={'discovery':False}),())
    with pytest.raises(PlatformError):
        access.require('discovery')


def test_configured_active_stock_limit_requires_a_selection_reduction():
    access=Access(principal(plan='PRO'),policy('PRO',active_stock_limit=1),('INFY','TCS'))
    with pytest.raises(PlatformError,match='Reduce active stocks'):
        access.require('stock_connections',('INFY',))


class Pool:
    def __init__(self, *users):
        self.users={user.id:user.model_dump() for user in users}
        self.active={user.id:set() for user in users}
        self.policies={'FREE':policy(features=json.dumps(policy()['features'])),'PRO':policy('PRO')}
        self.cancelled=[]
        self.locked=[]
        self.mutated=[]
        self.lock=asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before=copy.deepcopy((self.users,self.active,self.cancelled,self.mutated))
            try:
                yield
            except Exception:
                self.users,self.active,self.cancelled,self.mutated=before
                raise

    async def fetchrow(self,sql,*args):
        if 'FROM platform_users' in sql:
            if 'FOR UPDATE' in sql:
                self.locked.append(args[0])
            row=self.users.get(args[0])
            return row.copy() if row else None
        if 'FROM platform_plan_policies' in sql:
            return self.policies.get(args[0])
        raise AssertionError(sql)

    async def fetch(self,sql,*args):
        assert 'FROM platform_active_stocks' in sql
        return [{'ticker':ticker} for ticker in sorted(self.active[args[0]])]

    async def execute(self,sql,*args):
        self.mutated.append(sql)
        if sql.startswith('DELETE FROM platform_active_stocks'):
            self.active[args[0]].clear()
        elif sql.startswith('INSERT INTO platform_active_stocks'):
            self.active[args[0]].add(args[1])
        elif sql.startswith('UPDATE platform_users'):
            self.users[args[0]]['active_selection_initialized']=True
        elif sql.startswith('UPDATE agent_jobs'):
            self.cancelled.append(args[0])
        elif sql.startswith('UPDATE monitors'):
            pass
        else:
            raise AssertionError(sql)


@pytest.mark.asyncio
async def test_selection_over_limit_preserves_previous_selection_and_valid_changes_cancel_work():
    user=principal()
    pool=Pool(user)
    pool.active[user.id]={'INFY'}
    repository=Repository(Settings(_env_file=None))
    repository.pool=pool
    entitlements=Entitlements(repository)
    with pytest.raises(PlatformError) as denied:
        await entitlements.select(user,[f'STOCK{i}' for i in range(11)])
    assert denied.value.status==403 and pool.active[user.id]=={'INFY'}
    assert not pool.mutated
    result=await entitlements.select(user,['TCS','RELIANCE'])
    assert set(result['tickers'])=={'TCS','RELIANCE'} and result['initialized']
    assert pool.cancelled==[user.id] and pool.locked==[user.id,user.id]


@pytest.mark.asyncio
async def test_developer_can_select_more_than_policy_limit_and_missing_accounts_fail_closed():
    dev=principal(is_developer=True)
    pool=Pool(dev)
    repository=Repository(Settings(_env_file=None))
    repository.pool=pool
    entitlements=Entitlements(repository)
    result=await entitlements.select(dev,[f'STOCK{i}' for i in range(25)])
    assert len(result['tickers'])==25
    with pytest.raises(PlatformError):
        await load_access(pool,uuid4())
    pool.policies.clear()
    with pytest.raises(PlatformError) as unavailable:
        await load_access(pool,dev.id)
    assert unavailable.value.status==503


@pytest.mark.asyncio
async def test_developer_initiated_job_loses_override_when_initiator_loses_authority():
    owner,dev=principal(),principal(is_developer=True)
    pool=Pool(owner,dev)
    job={'user_id':owner.id,'actor_id':dev.id}
    assert (await load_job_access(pool,job)).developer
    pool.users[dev.id]['is_developer']=False
    with pytest.raises(PlatformError):
        await load_job_access(pool,job)
