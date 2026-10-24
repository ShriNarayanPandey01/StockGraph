"""Provision the platform database without granting runtime superuser access."""

import asyncio
import os
import re

import asyncpg


async def bootstrap():
    admin_dsn = os.environ['PLATFORM_ADMIN_DSN']
    name = os.environ.get('PLATFORM_DB_NAME','marketgraph_platform')
    role = os.environ.get('PLATFORM_DB_USER','marketgraph_platform')
    password = os.environ['PLATFORM_DB_PASSWORD']
    if not all(re.fullmatch(r'[a-z][a-z0-9_]{0,62}',v) for v in (name,role)):
        raise ValueError('Invalid platform database or role identifier')
    conn = await asyncpg.connect(admin_dsn)
    try:
        # This session lock makes concurrent startup safe. CREATE DATABASE must
        # run outside a transaction, so an advisory transaction lock is unsuitable.
        await conn.execute('SELECT pg_advisory_lock(780436153)')
        existing = await conn.fetchrow('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=$1',role)
        if existing:
            if existing['rolsuper'] or existing['rolbypassrls']:
                raise ValueError('Platform runtime role must not be superuser or bypass RLS')
        else:
            literal = await conn.fetchval('SELECT quote_literal($1)',password)
            await conn.execute(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {literal}')
        owner = await conn.fetchval('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=$1',name)
        if owner is None:
            await conn.execute(f'CREATE DATABASE "{name}" OWNER "{role}"')
        elif owner != role:
            raise ValueError('Existing platform database has a different owner')
        await conn.execute(f'REVOKE CONNECT ON DATABASE "{name}" FROM PUBLIC')
        await conn.execute(f'GRANT CONNECT ON DATABASE "{name}" TO "{role}"')
    finally:
        await conn.close()


def main():
    try:
        asyncio.run(bootstrap())
    except Exception:
        # Drivers include credentials/DSNs in some error messages.
        raise SystemExit('Platform database provisioning failed; verify administrator connectivity and ownership') from None
    print('Platform database provisioned; runtime credentials are restricted')


if __name__ == '__main__':
    main()
