"""Offline account lifecycle checks; SQL and SMTP are isolated fakes."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from marketgraph_platform import accounts as module
from marketgraph_platform.account_api import (
    AdminUserInput,
    CodeInput,
    SignupInput,
    build_account_router,
)
from marketgraph_platform.accounts import Accounts, profile, verify_password
from marketgraph_platform.auth import current_user, require_developer, require_role, token_digest
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import PlatformError
from marketgraph_platform.settings import Settings
from pydantic import ValidationError


class Memory:
    """Small stateful boundary fake, with rollback and serialized transactions."""

    def __init__(self):
        self.users, self.codes, self.tokens, self.rates, self.audit = {}, {}, {}, {}, []
        self.cancelled = []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before = copy.deepcopy((self.users, self.codes, self.tokens, self.rates, self.audit, self.cancelled))
            try:
                yield
            except Exception:
                self.users, self.codes, self.tokens, self.rates, self.audit, self.cancelled = before
                raise

    def user(self, identity=None, **overrides):
        identity = identity or uuid4()
        row = dict(id=identity, name='Reader', email=None, password_hash=None, email_verified=False,
                   professional_verified=False, is_developer=False, disabled=False, roles=['USER'],
                   plan='FREE', plan_expires_at=None, active_selection_initialized=False,
                   auth_revision=1, verification_revision=1)
        row.update(overrides)
        self.users[identity] = row
        return row

    async def fetchrow(self, sql, *args):
        if sql.startswith('SELECT * FROM platform_auth_challenges WHERE email'):
            return next((c.copy() for c in reversed(list(self.codes.values())) if c['email']==args[0] and c['purpose']==args[1] and c['consumed_at'] is None), None)
        if sql.startswith('SELECT * FROM platform_auth_challenges WHERE id'):
            row = self.codes.get(args[0])
            return row.copy() if row else None
        if sql.startswith('SELECT') and 'FROM platform_users' in sql:
            if 'WHERE is_developer' in sql:
                row = next((u for u in self.users.values() if u['is_developer']), None)
            elif 'WHERE lower(email)' in sql:
                row = next((u for u in self.users.values() if u['email']==args[0]), None)
            else:
                row = self.users.get(args[0])
            return row.copy() if row else None
        if sql.startswith('INSERT INTO platform_users'):
            if any(u['email']==args[2] for u in self.users.values()):
                return None
            return self.user(args[0], name=args[1], email=args[2], password_hash=args[3]).copy()
        if sql.startswith('UPDATE platform_users SET name=$2,roles='):
            row=self.users[args[0]]
            row.update(name=args[1], roles=json.loads(args[2]), professional_verified=args[3], plan=args[4],plan_expires_at=args[5],disabled=args[6])
            row['verification_revision'] += args[7]
            return row.copy()
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql.startswith('SELECT id FROM platform_users WHERE lower(email)'):
            return next((u['id'] for u in self.users.values() if u['email']==args[0] and (len(args)==1 or u['id']!=args[1])), None)
        if sql.startswith('SELECT id FROM platform_users WHERE id'):
            return args[0] if args[0] in self.users else None
        if sql.startswith('INSERT INTO platform_auth_rate_buckets'):
            self.rates[args[0]]=self.rates.get(args[0],0)+1
            return self.rates[args[0]]
        if sql.startswith('SELECT id FROM platform_auth_challenges'):
            return next((c['id'] for c in self.codes.values() if c['user_id']==args[0] and c['purpose']==args[1] and c['created_at']>datetime.now(UTC)-timedelta(seconds=args[2])), None)
        if sql.startswith('INSERT INTO platform_tokens'):
            expires=datetime.now(UTC)+timedelta(seconds=args[3])
            self.tokens[args[2]]={'user_id':args[1],'expires_at':expires,'revoked_at':None}
            return expires
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith('SELECT pg_advisory'):
            return
        if sql.startswith('INSERT INTO platform_users'):
            self.user(args[0],name=args[1],email=args[2],password_hash=args[3],email_verified=True,is_developer=True,
                      professional_verified=True,roles=['USER','PROFESSIONAL','REVIEWER'],plan='PRO',active_selection_initialized=True)
        elif sql.startswith('UPDATE platform_users SET name=$2,email='):
            row=self.users[args[0]]
            row.update(name=args[1],email=args[2],password_hash=args[3],disabled=False,email_verified=True,plan='PRO',plan_expires_at=None,
                       professional_verified=True,roles=['USER','PROFESSIONAL','REVIEWER'],active_selection_initialized=True)
            row['auth_revision']+=args[4]
        elif sql.startswith('UPDATE platform_users SET disabled='):
            self.users[args[0]]['disabled']=True
        elif sql.startswith('UPDATE platform_users SET email_verified='):
            self.users[args[0]]['email_verified']=True
        elif sql.startswith('UPDATE platform_users SET email='):
            self.users[args[0]].update(email=args[1],password_hash=args[2],email_verified=True)
        elif sql.startswith('UPDATE platform_users SET password_hash='):
            self.users[args[0]]['password_hash']=args[1]
            if 'email_verified=true' in sql:
                self.users[args[0]]['email_verified']=True
        elif sql.startswith('UPDATE platform_tokens'):
            for digest, token in self.tokens.items():
                if ('WHERE digest=' in sql and digest==args[0]) or ('WHERE user_id=' in sql and token['user_id']==args[0]):
                    token['revoked_at']=datetime.now(UTC)
        elif sql.startswith('INSERT INTO platform_admin_audit'):
            self.audit.append(dict(actor=args[0],target=args[1],action=args[2],details=args[3]))
        elif sql.startswith('INSERT INTO platform_auth_challenges'):
            self.codes[args[0]]=dict(id=args[0],user_id=args[1],email=args[2],purpose=args[3],digest=args[4],pending_password_hash=args[5],
                                      expires_at=datetime.now(UTC)+timedelta(seconds=args[6]),created_at=datetime.now(UTC),consumed_at=None,attempts=0)
        elif sql.startswith('UPDATE platform_auth_challenges SET attempts='):
            self.codes[args[0]]['attempts']+=1
        elif sql.startswith('UPDATE platform_auth_challenges SET consumed_at='):
            for row in self.codes.values():
                matches = row['id']==args[0] if 'WHERE id=' in sql else row['user_id']==args[0]
                if 'AND purpose=' in sql:
                    matches=matches and row['purpose']==args[1]
                if matches:
                    row['consumed_at']=datetime.now(UTC)
                    if 'pending_password_hash=NULL' in sql:
                        row['pending_password_hash']=None
        elif sql.startswith('UPDATE agent_jobs'):
            self.cancelled.append(args[0])
        else:
            raise AssertionError(sql)


@pytest.fixture
def setup_accounts(monkeypatch):
    monkeypatch.setattr(module, '_PASSWORDS', PasswordHasher(time_cost=1,memory_cost=1024,parallelism=1))
    settings=Settings(_env_file=None,smtp_host='smtp.example.test',smtp_from='accounts@example.test')
    repository=SimpleNamespace(pool=Memory(),settings=settings,_event=AsyncMock())
    account=Accounts(repository)
    sent=[]
    monkeypatch.setattr(account,'_send_code',lambda email,purpose,code:sent.append((email,purpose,code)))
    return account,repository,sent


def test_password_hashing_role_inputs_and_profile_never_return_credentials(setup_accounts):
    _,_,_=setup_accounts
    encoded=module._PASSWORDS.hash('safe long password')
    assert encoded.startswith('$argon2id$')
    assert verify_password(encoded,'safe long password')
    assert not verify_password(encoded,'wrong') and not verify_password('malformed','wrong')
    with pytest.raises(ValidationError):
        SignupInput(name='Reader',email='r@example.test',password='safe long password',roles=['REVIEWER'])
    with pytest.raises(ValidationError):
        AdminUserInput(plan_expires_at=datetime.now())
    value=profile(dict(id=uuid4(),name='Reader',password_hash=encoded,roles='["USER"]'))
    assert 'password_hash' not in value and value['plan']=='FREE'


@pytest.mark.asyncio
async def test_signup_verification_login_and_logout(setup_accounts):
    account,repo,sent=setup_accounts
    result=await account.signup('reader@example.test','Reader','safe long password','test-ip')
    assert 'eligible' in result['detail'] and len(sent)==1
    user=next(iter(repo.pool.users.values()))
    assert user['roles']==['USER'] and user['plan']=='FREE' and not user['email_verified']
    assert user['password_hash']!='safe long password'
    with pytest.raises(PlatformError) as denied:
        await account.login(user['email'],'safe long password','test-ip')
    assert denied.value.status==403
    code=sent[-1][2]
    assert next(iter(repo.pool.codes.values()))['digest']==token_digest(code)
    assert code not in str(repo.pool.codes)
    await account.consume_code(user['email'],'verify',code,'test-ip','safe long password')
    with pytest.raises(PlatformError):
        await account.consume_code(user['email'],'verify',code,'test-ip','safe long password')
    session=await account.login(user['email'],'safe long password','test-ip')
    digest=token_digest(session['access_token'])
    assert digest in repo.pool.tokens and session['access_token'] not in str(repo.pool.tokens)
    assert datetime.now(UTC)+timedelta(hours=11)<session['expires_at']<datetime.now(UTC)+timedelta(hours=13)
    await account.logout(digest)
    assert repo.pool.tokens[digest]['revoked_at'] is not None


@pytest.mark.asyncio
async def test_failed_code_attempts_commit_and_code_expires(setup_accounts):
    account,repo,sent=setup_accounts
    user=repo.pool.user(email='reader@example.test')
    await account.issue_challenge(user['id'],user['email'],'verify')
    for _ in range(5):
        with pytest.raises(PlatformError):
            await account.consume_code(user['email'],'verify','wrong','test-ip')
    challenge=next(iter(repo.pool.codes.values()))
    assert challenge['attempts']==5
    with pytest.raises(PlatformError):
        await account.consume_code(user['email'],'verify',sent[-1][2],'test-ip')
    challenge.update(attempts=0,expires_at=datetime.now(UTC)-timedelta(seconds=1))
    with pytest.raises(PlatformError):
        await account.consume_code(user['email'],'verify',sent[-1][2],'test-ip')
    assert not user['email_verified']


@pytest.mark.asyncio
async def test_recovery_is_generic_and_password_reset_revokes_existing_tokens(setup_accounts):
    account,repo,sent=setup_accounts
    user=repo.pool.user(email='reader@example.test',email_verified=True,password_hash=module._PASSWORDS.hash('old safe password'))
    repo.pool.tokens['old']={'user_id':user['id'],'revoked_at':None}
    known=await account.request_code(user['email'],'reset','ip-a')
    unknown=await account.request_code('unknown@example.test','reset','ip-b')
    assert known==unknown and len(sent)==1
    await account.consume_code(user['email'],'reset',sent[-1][2],'ip-a','new safe password')
    assert verify_password(repo.pool.users[user['id']]['password_hash'],'new safe password')
    assert repo.pool.tokens['old']['revoked_at'] is not None


@pytest.mark.asyncio
async def test_legacy_attach_does_not_change_identity_before_verification(setup_accounts):
    account,repo,sent=setup_accounts
    row=repo.pool.user()
    user=Principal.model_validate(profile(row))
    repo.pool.tokens['legacy']={'user_id':user.id,'revoked_at':None}
    await account.attach_credentials(user,'reader@example.test','safe long password','ip-a')
    assert row['email'] is None and repo.pool.tokens['legacy']['revoked_at'] is None
    await account.consume_code('reader@example.test','attach',sent[-1][2],'ip-a')
    assert repo.pool.users[user.id]['email_verified']
    assert repo.pool.tokens['legacy']['revoked_at'] is not None


@pytest.mark.asyncio
async def test_developer_bootstrap_is_stable_rotates_sessions_and_cannot_take_over_account(setup_accounts):
    account,repo,_=setup_accounts
    from pydantic import SecretStr
    account.settings.admin_email='admin@marketgraph.local'
    account.settings.admin_password=SecretStr('developer long password')
    await asyncio.gather(account.bootstrap_developer(),account.bootstrap_developer())
    assert len(repo.pool.users)==1
    dev=next(iter(repo.pool.users.values()))
    assert dev['is_developer'] and dev['professional_verified'] and dev['plan']=='PRO'
    repo.pool.tokens['dev-session']={'user_id':dev['id'],'revoked_at':None}
    await account.bootstrap_developer()
    assert repo.pool.tokens['dev-session']['revoked_at'] is None
    account.settings.admin_password=SecretStr('rotated developer password')
    await account.bootstrap_developer()
    assert repo.pool.tokens['dev-session']['revoked_at'] is not None
    assert len(repo.pool.users)==1
    conflict=repo.pool.user(email='taken@example.test')
    account.settings.admin_email=conflict['email']
    with pytest.raises(RuntimeError,match='conflicts'):
        await account.bootstrap_developer()
    assert not repo.pool.users[conflict['id']]['is_developer']


@pytest.mark.asyncio
async def test_admin_verification_emits_event_and_downgrade_cancels_jobs(setup_accounts):
    account,repo,_=setup_accounts
    dev=Principal(id=uuid4(),name='Developer',is_developer=True)
    user=repo.pool.user(plan='PRO')
    result=await account.update_user(dev,user['id'],{'professional_verified':True,'roles':['REVIEWER'],'plan':'FREE'})
    assert set(result['roles'])=={'USER','PROFESSIONAL','REVIEWER'}
    repo._event.assert_awaited_once()
    assert repo.pool.cancelled==[user['id']] and repo.pool.audit[-1]['actor']==dev.id
    with pytest.raises(HTTPException):
        require_developer(Principal(id=user['id'],name='Reader'))
    assert require_role(dev,'REVIEWER') is dev


@pytest.mark.asyncio
async def test_missing_mail_and_login_budget_fail_without_returning_secrets(setup_accounts):
    account,repo,_=setup_accounts
    account.settings.smtp_host=''
    with pytest.raises(PlatformError) as unavailable:
        await account.signup('r@example.test','Reader','safe long password','ip')
    assert unavailable.value.status==503 and not repo.pool.users
    await account.throttle('test','r@example.test','ip',email_limit=1)
    with pytest.raises(PlatformError) as limited:
        await account.throttle('test','r@example.test','ip',email_limit=1)
    assert limited.value.status==429


def test_admin_routes_are_not_available_to_ordinary_users(setup_accounts):
    account,repo,_=setup_accounts
    app=FastAPI()
    app.state.accounts,app.state.repository=account,repo
    async def reader():
        return Principal(id=uuid4(),name='Reader')
    app.include_router(build_account_router(reader))
    client=TestClient(app)
    response=client.patch('/api/v1/admin/users/'+str(uuid4()),json={'roles':['REVIEWER']})
    assert response.status_code==403


@pytest.mark.asyncio
async def test_developer_bypasses_operational_request_quota_but_disabled_accounts_do_not_authenticate():
    user=Principal(id=uuid4(),name='Developer',is_developer=True)
    repository=SimpleNamespace(authenticate=AsyncMock(return_value=user.model_dump()),allow_request=AsyncMock(return_value=False))
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository)),state=SimpleNamespace())
    assert (await current_user(request,'Bearer fixture-token')).is_developer
    assert request.state.user.id==user.id
    repository.allow_request.assert_not_awaited()
    repository.authenticate.return_value=user.model_copy(update={'disabled':True}).model_dump()
    with pytest.raises(HTTPException) as denied:
        await current_user(request,'Bearer fixture-token')
    assert denied.value.status_code==401


@pytest.mark.asyncio
async def test_mail_failure_invalidates_unsent_code_and_can_be_retried(setup_accounts, monkeypatch):
    account,repo,_=setup_accounts
    user=repo.pool.user(email='reader@example.test')
    def unavailable(*args):
        raise OSError('private transport details must not escape')
    monkeypatch.setattr(account,'_send_code',unavailable)
    with pytest.raises(PlatformError) as failure:
        await account.issue_challenge(user['id'],user['email'],'verify')
    assert failure.value.status==503
    assert 'private' not in failure.value.detail
    assert next(iter(repo.pool.codes.values()))['consumed_at'] is not None


@pytest.mark.asyncio
async def test_password_change_revokes_tokens_and_developer_password_is_environment_managed(setup_accounts):
    account,repo,_=setup_accounts
    row=repo.pool.user(email='reader@example.test',email_verified=True,password_hash=module._PASSWORDS.hash('old safe password'))
    user=Principal.model_validate(profile(row))
    repo.pool.tokens['legacy']={'user_id':user.id,'revoked_at':None}
    with pytest.raises(PlatformError):
        await account.change_password(user,'incorrect','new safe password')
    await account.change_password(user,'old safe password','new safe password')
    assert verify_password(repo.pool.users[user.id]['password_hash'],'new safe password')
    assert repo.pool.tokens['legacy']['revoked_at'] is not None
    with pytest.raises(PlatformError) as denied:
        await account.change_password(user.model_copy(update={'is_developer':True}),'new safe password','third safe password')
    assert denied.value.status==403


@pytest.mark.asyncio
async def test_missing_developer_configuration_disables_environment_account(setup_accounts):
    account,repo,sent=setup_accounts
    dev=repo.pool.user(email='admin@marketgraph.local',is_developer=True,email_verified=True)
    repo.pool.tokens['admin-session']={'user_id':dev['id'],'revoked_at':None}
    await account.bootstrap_developer()
    assert repo.pool.users[dev['id']]['disabled']
    assert repo.pool.tokens['admin-session']['revoked_at'] is not None
    await account.request_code(dev['email'],'reset','ip')
    assert not sent


@pytest.mark.asyncio
async def test_email_owner_cannot_activate_a_pre_registered_attackers_password(setup_accounts):
    account,repo,sent=setup_accounts
    await account.signup('owner@example.test','Attacker','attacker known password','attacker-ip')
    await account.signup('owner@example.test','Owner','owner secure password','owner-ip')
    # Even if resends are throttled, a mailbox proof activates the password
    # supplied by the person possessing the verification code.
    user=next(iter(repo.pool.users.values()))
    code=sent[-1][2]
    await account.consume_code(user['email'],'verify',code,'owner-ip','owner secure password')
    with pytest.raises(PlatformError) as denied:
        await account.login(user['email'],'attacker known password','other-ip')
    assert denied.value.status==401
    assert (await account.login(user['email'],'owner secure password','owner-ip'))['user']['email_verified']
    with pytest.raises(ValidationError):
        CodeInput(email=user['email'],code=code)


@pytest.mark.asyncio
async def test_password_change_invalidates_previously_issued_recovery_codes(setup_accounts):
    account,repo,sent=setup_accounts
    row=repo.pool.user(email='owner@example.test',email_verified=True,password_hash=module._PASSWORDS.hash('old secure password'))
    await account.request_code(row['email'],'reset','owner-ip')
    code=sent[-1][2]
    await account.change_password(Principal.model_validate(profile(row)),'old secure password','new secure password')
    with pytest.raises(PlatformError):
        await account.consume_code(row['email'],'reset',code,'owner-ip','stolen reset password')
    assert verify_password(repo.pool.users[row['id']]['password_hash'],'new secure password')


@pytest.mark.asyncio
async def test_recovery_response_is_generic_even_when_configured_smtp_fails(setup_accounts,monkeypatch):
    account,repo,_=setup_accounts
    row=repo.pool.user(email='owner@example.test',email_verified=True,password_hash=module._PASSWORDS.hash('owner password'))
    def outage(*args):
        raise OSError('private SMTP failure')
    monkeypatch.setattr(account,'_send_code',outage)
    existing=await account.request_code(row['email'],'reset','ip-one')
    missing=await account.request_code('unknown@example.test','reset','ip-two')
    assert existing==missing
    assert all(code['consumed_at'] is not None for code in repo.pool.codes.values())


@pytest.mark.asyncio
async def test_ordinary_callers_cannot_mutate_account_privileges_directly(setup_accounts):
    account,repo,_=setup_accounts
    row=repo.pool.user()
    actor=Principal(id=row['id'],name='Reader')
    with pytest.raises(PlatformError) as denied:
        await account.update_user(actor,row['id'],{'roles':['REVIEWER'],'plan':'PRO'})
    assert denied.value.status==403 and row['roles']==['USER'] and not repo.pool.audit
    with pytest.raises(PlatformError):
        await account.revoke_sessions(actor,row['id'])


@pytest.mark.asyncio
async def test_reset_code_cannot_be_replayed_or_used_after_account_disable(setup_accounts):
    account,repo,sent=setup_accounts
    row=repo.pool.user(email='owner@example.test',email_verified=True,password_hash=module._PASSWORDS.hash('old secure password'))
    await account.request_code(row['email'],'reset','owner-ip')
    code=sent[-1][2]
    await account.consume_code(row['email'],'reset',code,'owner-ip','new secure password')
    with pytest.raises(PlatformError):
        await account.consume_code(row['email'],'reset',code,'owner-ip','replayed password')
    assert verify_password(repo.pool.users[row['id']]['password_hash'],'new secure password')
    # A previously issued code must not reactivate an administrator-disabled user.
    challenge=next(iter(repo.pool.codes.values()))
    challenge.update(consumed_at=None,attempts=0)
    repo.pool.users[row['id']]['disabled']=True
    with pytest.raises(PlatformError):
        await account.consume_code(row['email'],'reset',code,'owner-ip','disabled reset password')
    assert verify_password(repo.pool.users[row['id']]['password_hash'],'new secure password')
