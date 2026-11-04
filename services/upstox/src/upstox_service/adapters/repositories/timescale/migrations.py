"""Checksummed, transactional adoption of existing and new source schemas.

An existing deployment adopts the idempotent baseline without deleting data.
Future changes must append a migration rather than changing an applied entry.
"""

import hashlib
from pathlib import Path


async def apply_migration(conn, name: str, sql: str):
    async with conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(780436154)')
        await conn.execute('CREATE TABLE IF NOT EXISTS upstox_schema_migrations ('
                           'name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())')
        digest = hashlib.sha256(sql.encode()).hexdigest()
        previous = await conn.fetchval('SELECT checksum FROM upstox_schema_migrations WHERE name=$1',name)
        if previous:
            if previous != digest:
                raise RuntimeError(f'Applied Data Service migration changed: {name}')
            return
        await conn.execute(sql)
        await conn.execute('INSERT INTO upstox_schema_migrations(name,checksum) VALUES($1,$2)',name,digest)


async def migrate_data_store(conn):
    from upstox_service.adapters.repositories.timescale.catalog import CATALOG_DDL
    from upstox_service.adapters.repositories.timescale.documents import DOCUMENT_DDL
    from upstox_service.adapters.repositories.timescale.numeric import DDL_SCHEMA
    from upstox_service.adapters.repositories.timescale.stock_data import STOCK_DATA_DDL

    for name,sql in (
        ('001_numeric',DDL_SCHEMA),('002_catalog',CATALOG_DDL),
        ('003_stock_data',STOCK_DATA_DDL),('004_documents',DOCUMENT_DDL),
        ('005_company_equity', Path(__file__).with_name('company_equity.sql').read_text(encoding='utf-8')),
    ):
        await apply_migration(conn,name,sql)
