"""Account behavior without an email transport."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from marketgraph_platform import accounts as module
from marketgraph_platform.account_api import build_account_router
from marketgraph_platform.accounts import Accounts, profile, verify_password
from marketgraph_platform.auth import current_user, token_digest
from marketgraph_platform.models import Principal
from marketgraph_platform.repository import PlatformError, Repository
from marketgraph_platform.settings import Settings
from pydantic import SecretStr


class Memory:
    def __init__(self):
        self.users = {}
        self.tokens = {}
        self.rates = {}
        self.audit = []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            yield

    def user(self, **overrides):
        row = dict(id=uuid4(), name='Reader', email=None, password_hash=None,
                   professional_verified=False, is_developer=False, disabled=False,
                   roles=['USER'], plan='FREE', plan_expires_at=None,
                   active_selection_initialized=False, auth_revision=1, verification_revision=1)
        row.update(overrides)
        self.users[row['id']] = row
        return row

    async def fetchrow(self, sql, *args):
        if sql.startswith('SELECT') and 'FROM platform_users' in sql:
            if 'WHERE is_developer' in sql:
                row = next((u for u in self.users.values() if u['is_developer']), None)
            elif 'WHERE lower(email)' in sql:
                row = next((u for u in self.users.values() if u['email'] == args[0]), None)
            else:
                row = self.users.get(args[0])
            return row.copy() if row else None
        if sql.startswith('UPDATE platform_users SET name=$2,roles='):
            row = self.users[args[0]]
            row.update(name=args[1], roles=json.loads(args[2]), professional_verified=args[3],
                       plan=args[4], plan_expires_at=args[5], disabled=args[6])
            row['verification_revision'] += args[7]
            return row.copy()
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql.startswith('SELECT id FROM platform_users WHERE lower(email)'):
            return next((u['id'] for u in self.users.values() if u['email'] == args[0] and (len(args) == 1 or u['id'] != args[1])), None)
        if sql.startswith('INSERT INTO platform_auth_rate_buckets'):
            self.rates[args[0]] = self.rates.get(args[0], 0) + 1
            return self.rates[args[0]]
        if sql.startswith('INSERT INTO platform_tokens'):
            expires = datetime.now(UTC)
            self.tokens[args[2]] = {'user_id': args[1], 'revoked_at': None}
            return expires
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith('SELECT pg_advisory'):
            return
        if sql.startswith('INSERT INTO platform_users'):
            if not any(u['email'] == args[2] for u in self.users.values()):
                self.user(id=args[0], name=args[1], email=args[2], password_hash=args[3],
                          is_developer='is_developer' in sql,
                          professional_verified='professional_verified' in sql,
                          roles=['USER', 'PROFESSIONAL', 'REVIEWER'] if 'is_developer' in sql else ['USER'],
                          plan='PRO' if 'is_developer' in sql else 'FREE')
        elif sql.startswith('UPDATE platform_users SET name=$2,email='):
            self.users[args[0]].update(name=args[1], email=args[2], password_hash=args[3],
                                       disabled=False, roles=['USER', 'PROFESSIONAL', 'REVIEWER'],
                                       plan='PRO', professional_verified=True)
            self.users[args[0]]['auth_revision'] += args[4]
        elif sql.startswith('UPDATE platform_users SET disabled='):
            self.users[args[0]]['disabled'] = True
        elif sql.startswith('UPDATE platform_users SET password_hash='):
            self.users[args[0]]['password_hash'] = args[1]
        elif sql.startswith('UPDATE platform_tokens'):
            for digest, token in self.tokens.items():
                if ('WHERE digest=' in sql and digest == args[0]) or ('WHERE user_id=' in sql and token['user_id'] == args[0]):
                    token['revoked_at'] = datetime.now(UTC)
        elif sql.startswith('INSERT INTO platform_admin_audit'):
            self.audit.append(args)
        elif sql.startswith('UPDATE agent_jobs'):
            pass
        else:
            raise AssertionError(sql)


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setattr(module, '_PASSWORDS', PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    repo = Repository(Settings(_env_file=None))
    repo.pool = Memory()
    return Accounts(repo, repo.settings), repo


@pytest.mark.asyncio
async def test_signup_immediately_allows_login_and_duplicate_is_generic(accounts):
    account, repo = accounts
    first = await account.signup('reader@example.test', 'Reader', 'safe long password', 'ip')
    second = await account.signup('reader@example.test', 'Other', 'other long password', 'ip')
    assert first == second
    assert len(repo.pool.users) == 1
    row = next(iter(repo.pool.users.values()))
    assert row['roles'] == ['USER'] and row['plan'] == 'FREE'
    assert row['password_hash'].startswith('$argon2id$')
    assert verify_password(row['password_hash'], 'safe long password')
    assert not verify_password(row['password_hash'], 'other long password')
    session = await account.login(row['email'], 'safe long password', 'ip')
    assert session['user']['id'] == str(row['id'])
    assert 'email_verified' not in session['user']
    assert token_digest(session['access_token']) in repo.pool.tokens
    await account.logout(token_digest(session['access_token']))
    assert repo.pool.tokens[token_digest(session['access_token'])]['revoked_at']


@pytest.mark.asyncio
async def test_password_change_revokes_sessions_and_rate_limits_remain(accounts):
    account, repo = accounts
    await account.signup('reader@example.test', 'Reader', 'safe long password', 'ip')
    row = next(iter(repo.pool.users.values()))
    user = Principal.model_validate(profile(row))
    session = await account.login(row['email'], 'safe long password', 'ip')
    with pytest.raises(PlatformError):
        await account.change_password(user, 'wrong password', 'new safe password')
    await account.change_password(user, 'safe long password', 'new safe password')
    assert repo.pool.tokens[token_digest(session['access_token'])]['revoked_at']
    assert verify_password(row['password_hash'], 'new safe password')
    with pytest.raises(PlatformError) as old:
        await account.login(row['email'], 'safe long password', 'ip')
    assert old.value.status == 401
    await account.throttle('test', row['email'], 'ip', email_limit=1)
    with pytest.raises(PlatformError) as limited:
        await account.throttle('test', row['email'], 'ip', email_limit=1)
    assert limited.value.status == 429


def test_openapi_has_only_supported_account_flows(accounts):
    account, repo = accounts
    app = FastAPI()
    app.state.accounts, app.state.repository = account, repo
    async def reader():
        return Principal(id=uuid4(), name='Reader')
    app.include_router(build_account_router(reader))
    paths = TestClient(app).get('/openapi.json').json()['paths']
    assert '/api/v1/auth/change-password' in paths
    for suffix in ('verify-email', 'resend-verification', 'forgot-password', 'reset-password'):
        assert '/api/v1/auth/' + suffix not in paths
    assert '/api/v1/me/credentials' not in paths
    assert TestClient(app).patch('/api/v1/admin/users/' + str(uuid4()), json={'plan': 'PRO'}).status_code == 403


@pytest.mark.asyncio
async def test_bearer_accepts_active_account_and_rejects_disabled(accounts):
    account, repo = accounts
    user = Principal(id=uuid4(), name='Reader', email='reader@example.test')
    repository = SimpleNamespace(authenticate=AsyncMock(return_value=user.model_dump()), allow_request=AsyncMock(return_value=True))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository)), state=SimpleNamespace())
    assert (await current_user(request, 'Bearer fixture-token')).id == user.id
    repository.authenticate.return_value = user.model_copy(update={'disabled': True}).model_dump()
    with pytest.raises(HTTPException) as denied:
        await current_user(request, 'Bearer fixture-token')
    assert denied.value.status_code == 401


@pytest.mark.asyncio
async def test_developer_bootstrap_creates_account_and_rotates_sessions(accounts):
    account, repo = accounts
    repo.settings.admin_email = 'admin@example.test'
    repo.settings.admin_password = SecretStr('developer long password')
    await account.bootstrap_developer()
    row = next(iter(repo.pool.users.values()))
    assert row['is_developer'] and row['plan'] == 'PRO'
    assert verify_password(row['password_hash'], 'developer long password')
    session = await account.login(row['email'], 'developer long password', 'ip')
    repo.settings.admin_password = SecretStr('rotated developer password')
    await account.bootstrap_developer()
    assert repo.pool.tokens[token_digest(session['access_token'])]['revoked_at']
