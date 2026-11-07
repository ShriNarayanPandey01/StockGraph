"""Offline credential-vault and per-owner broker request checks."""

import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from marketgraph_platform.brokers import (
    BrokerConnections,
    BrokerVault,
    TokenInput,
    build_broker_router,
)
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import PlatformError, Repository
from marketgraph_platform.settings import Settings
from pydantic import SecretStr, ValidationError


def test_vault_encrypts_randomized_ciphertext_bound_to_its_owner():
    key=SecretStr(Fernet.generate_key().decode())
    vault=BrokerVault(key)
    owner=uuid4()
    token=SecretStr('private-upstox-credential')
    first,second=vault.encrypt(owner,token),vault.encrypt(owner,token)
    assert first!=second and token.get_secret_value().encode() not in first
    assert vault.decrypt(owner,first).get_secret_value()==token.get_secret_value()
    assert token.get_secret_value() not in repr(vault.decrypt(owner,first))
    for identity,encrypted in [(uuid4(),first),(owner,first[:-8]+b'tampered')]:
        with pytest.raises(PlatformError) as denied:
            vault.decrypt(identity,encrypted)
        assert denied.value.status==503
        assert token.get_secret_value() not in denied.value.detail
    with pytest.raises(PlatformError):
        BrokerVault(SecretStr(Fernet.generate_key().decode())).decrypt(owner,first)
    assert key.get_secret_value() not in repr(vault)


def test_missing_encryption_key_fails_closed_and_input_secrets_are_masked():
    vault=BrokerVault(SecretStr('not-a-valid-secret-key'))
    with pytest.raises(PlatformError) as unavailable:
        vault.encrypt(uuid4(),SecretStr('private-token'))
    assert unavailable.value.status==503
    assert 'not-a-valid' not in unavailable.value.detail
    body=TokenInput(access_token='private-token')
    assert 'private-token' not in repr(body)
    with pytest.raises(ValidationError):
        TokenInput(access_token='private-token',user_id=str(uuid4()))


class Pool:
    def __init__(self,*users):
        self.users={user.id:{'disabled':False} for user in users}
        self.rows={}
        self.lock=asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before=copy.deepcopy(self.rows)
            try:
                yield
            except Exception:
                self.rows=before
                raise

    async def fetchrow(self,sql,*args):
        if 'FROM platform_users' in sql:
            return self.users.get(args[0])
        if 'FROM platform_broker_connections' in sql:
            row=self.rows.get(args[0])
            if row is None:
                return None
            fields=['status','revision','encrypted_token'] if 'encrypted_token' in sql else ['status','revision','validated_at']
            return {key:row[key] for key in fields}
        raise AssertionError(sql)

    async def execute(self,sql,*args):
        if sql.startswith('INSERT INTO platform_broker_connections'):
            previous=self.rows.get(args[0])
            self.rows[args[0]]={'status':'connected','revision':previous['revision']+1 if previous else 1,
                                 'encrypted_token':args[1],'validated_at':datetime.now(UTC)}
        elif sql.startswith('UPDATE platform_broker_connections SET encrypted_token=NULL'):
            if args[0] in self.rows:
                self.rows[args[0]].update(status='disconnected',encrypted_token=None,validated_at=None,
                                         revision=self.rows[args[0]]['revision']+1)
        elif sql.startswith("UPDATE platform_broker_connections SET status='reconnect_required'"):
            row=self.rows.get(args[0])
            if row and row['revision']==args[1]:
                row['status']='reconnect_required'
        else:
            raise AssertionError(sql)


@pytest.fixture
def broker_setup():
    alice,bob=(Principal(id=uuid4(),name=name) for name in ['Alice','Bob'])
    pool=Pool(alice,bob)
    client=SimpleNamespace(post_internal=AsyncMock(return_value={'valid':True}),get=AsyncMock(return_value={'items':[]}))
    settings=Settings(_env_file=None,broker_encryption_key=SecretStr(Fernet.generate_key().decode()))
    repository=Repository(settings)
    repository.pool=pool
    brokers=BrokerConnections(repository,settings,client)
    return brokers,pool,client,alice,bob


@pytest.mark.asyncio
async def test_connect_replace_and_disconnect_advance_cache_revision_without_exposing_tokens(broker_setup):
    brokers,pool,client,alice,bob=broker_setup
    assert await brokers.headers_for(alice.id)=={}
    connected=await brokers.connect(alice,SecretStr('first-personal-token'))
    assert connected['status']=='connected' and connected['revision']==1
    assert set(connected)=={'status','revision','validated_at'}
    assert b'first-personal-token' not in pool.rows[alice.id]['encrypted_token']
    first=await brokers.headers_for(alice.id)
    assert first['X-Upstox-Access-Token']=='first-personal-token'
    client.post_internal.assert_awaited_once_with('/internal/v1/upstox/validate-credential',{'access_token':'first-personal-token'})
    await brokers.connect(alice,SecretStr('second-personal-token'))
    second=await brokers.headers_for(alice.id)
    assert second['X-Upstox-Access-Token']=='second-personal-token'
    assert second['X-MarketGraph-Credential-Scope']!=first['X-MarketGraph-Credential-Scope']
    assert await brokers.headers_for(bob.id)=={}
    disconnected=await brokers.disconnect(alice.id)
    assert disconnected['status']=='disconnected' and disconnected['revision']==3
    assert pool.rows[alice.id]['encrypted_token'] is None
    assert await brokers.headers_for(alice.id)=={}
    await brokers.connect(alice,SecretStr('third-personal-token'))
    assert (await brokers.headers_for(alice.id))['X-MarketGraph-Credential-Scope'].endswith(':4')


@pytest.mark.asyncio
async def test_two_users_with_identical_tokens_still_have_isolated_cache_scopes(broker_setup):
    brokers,_,_,alice,bob=broker_setup
    await brokers.connect(alice,SecretStr('identical-personal-token'))
    await brokers.connect(bob,SecretStr('identical-personal-token'))
    a,b=await brokers.headers_for(alice.id),await brokers.headers_for(bob.id)
    assert a['X-MarketGraph-Credential-Scope']!=b['X-MarketGraph-Credential-Scope']
    assert (await brokers.status(alice.id))['revision']==1
    assert (await brokers.status(bob.id))['revision']==1


@pytest.mark.asyncio
async def test_rejected_personal_token_requires_reconnect_without_shared_fallback(broker_setup):
    brokers,pool,client,alice,_=broker_setup
    await brokers.connect(alice,SecretStr('rejected-personal-token'))
    client.get.side_effect=PlatformError(401,'broker_reconnect_required')
    with pytest.raises(PlatformError) as rejected:
        await brokers.read(alice.id,'/api/v1/stocks/INFY')
    assert rejected.value.status==409 and rejected.value.detail=='broker_reconnect_required'
    assert client.get.await_count==1
    assert client.get.await_args.kwargs['headers']['X-Upstox-Access-Token']=='rejected-personal-token'
    assert pool.rows[alice.id]['status']=='reconnect_required'
    with pytest.raises(PlatformError):
        await brokers.read(alice.id,'/api/v1/stocks/INFY')
    assert client.get.await_count==1
    await brokers.disconnect(alice.id)
    client.get.side_effect=None
    assert await brokers.read(alice.id,'/api/v1/stocks/INFY')=={'items':[]}
    assert client.get.await_args.kwargs['headers']=={}


@pytest.mark.asyncio
async def test_service_auth_and_temporary_upstream_failures_do_not_invalidate_personal_credential(broker_setup):
    brokers,pool,client,alice,_=broker_setup
    await brokers.connect(alice,SecretStr('valid-personal-token'))
    for failure in [PlatformError(401,'Internal service authentication rejected'),PlatformError(503,'Provider unavailable')]:
        client.get.side_effect=failure
        with pytest.raises(PlatformError) as rejected:
            await brokers.read(alice.id,'/api/v1/stocks/INFY')
        assert rejected.value is failure
        assert pool.rows[alice.id]['status']=='connected'
    assert client.get.await_count==2


@pytest.mark.asyncio
async def test_failed_token_replacement_preserves_existing_encrypted_credential(broker_setup):
    brokers,pool,client,alice,_=broker_setup
    await brokers.connect(alice,SecretStr('existing-personal-token'))
    encrypted=pool.rows[alice.id]['encrypted_token']
    client.post_internal.side_effect=PlatformError(401,'broker_reconnect_required')
    with pytest.raises(PlatformError):
        await brokers.connect(alice,SecretStr('invalid-replacement'))
    assert pool.rows[alice.id]['encrypted_token']==encrypted
    assert (await brokers.status(alice.id))['revision']==1


@pytest.mark.asyncio
async def test_account_disabled_during_validation_cannot_save_credential(broker_setup):
    brokers,pool,client,alice,_=broker_setup
    async def disable_after_validation(*args,**kwargs):
        pool.users[alice.id]['disabled']=True
        return {'valid':True}
    client.post_internal.side_effect=disable_after_validation
    with pytest.raises(PlatformError) as disabled:
        await brokers.connect(alice,SecretStr('personal-token'))
    assert disabled.value.status==403 and alice.id not in pool.rows


@pytest.mark.asyncio
async def test_failure_from_old_inflight_request_cannot_invalidate_replacement_credential(broker_setup):
    brokers,pool,client,alice,_=broker_setup
    await brokers.connect(alice,SecretStr('first-token'))
    async def replace_while_request_is_inflight(*args,**kwargs):
        await brokers.connect(alice,SecretStr('replacement-token'))
        raise PlatformError(401,'broker_reconnect_required')
    client.get.side_effect=replace_while_request_is_inflight
    with pytest.raises(PlatformError):
        await brokers.read(alice.id,'/api/v1/stocks/INFY')
    assert pool.rows[alice.id]['revision']==2 and pool.rows[alice.id]['status']=='connected'
    assert (await brokers.headers_for(alice.id))['X-Upstox-Access-Token']=='replacement-token'


def test_connection_routes_bind_identity_to_authenticated_user(broker_setup):
    brokers,pool,_,alice,bob=broker_setup
    app=FastAPI()
    app.state.brokers=brokers
    async def current_user():
        return alice
    @app.exception_handler(PlatformError)
    async def error(request,exc):
        return JSONResponse(status_code=exc.status,content={'detail':exc.detail})
    app.include_router(build_broker_router(current_user))
    with TestClient(app) as client:
        assert client.put('/api/v1/me/broker-connections/upstox',json={'access_token':'personal-token','user_id':str(bob.id)}).status_code==422
        response=client.put('/api/v1/me/broker-connections/upstox',json={'access_token':'personal-token'})
        assert response.status_code==200
        assert 'personal-token' not in response.text and 'encrypted_token' not in response.text
        assert alice.id in pool.rows and bob.id not in pool.rows
        assert client.get('/api/v1/me/broker-connections/upstox').json()['status']=='connected'
        assert client.delete('/api/v1/me/broker-connections/upstox').json()['status']=='disconnected'
