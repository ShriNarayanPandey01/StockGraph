"""Offline archive safety and rollback behavior; SQL round trip is opt-in."""

import copy
import json
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZipFile

import asyncpg
import pytest

from scripts import platform_data as tool


class Connection:
    def __init__(self):
        self.rows = {table: [] for table in tool.TABLES}
        self.fail_table = None
        self.writes = []

    def is_in_transaction(self):
        return False

    @asynccontextmanager
    async def transaction(self, **kwargs):
        before = copy.deepcopy(self.rows)
        try:
            yield
        except Exception:
            self.rows = before
            raise

    async def fetch(self, query, *args):
        if "platform_schema_migrations" in query:
            return [
                {"name": key, "checksum": value}
                for key, value in tool.migration_checksums().items()
            ]
        return [
            {
                "column_name": "id",
                "udt_schema": "pg_catalog",
                "udt_name": "text",
                "is_nullable": "NO",
            }
        ]

    async def fetchval(self, query, *args):
        table = re.findall(r'\."([^";]+)"', query)[0]
        return bool(self.rows[table]) if "EXISTS" in query else len(self.rows[table])

    async def fetchrow(self, query, *args):
        return None

    async def execute(self, query, *args):
        self.writes.append(query)

    async def copy_from_table(self, table, *, output, **kwargs):
        output.write(json.dumps(self.rows[table]).encode())

    async def copy_to_table(self, table, *, source, **kwargs):
        if table == self.fail_table:
            raise ValueError("bad COPY body")
        self.rows[table] = json.loads(source.read())


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:password@production.example/marketgraph_platform",
        "postgresql://user:password@localhost/stockgraph",
        "postgresql://user:password@localhost/marketgraph_platform_other",
    ],
)
def test_maintenance_target_rejects_other_databases_without_revealing_credentials(dsn):
    with pytest.raises(ValueError) as error:
        tool.validate_target(dsn)
    assert "password" not in str(error.value)


async def test_archive_roundtrip_and_existing_records_are_never_replaced(tmp_path):
    source = Connection()
    source.rows["platform_users"] = ["author"]
    path = await tool.backup_connection(source, tmp_path / "platform.zip")
    target = Connection()
    await tool.restore_connection(target, path)
    assert target.rows == source.rows
    target.rows["platform_users"] = ["already present"]
    with pytest.raises(ValueError, match="empty initialized"):
        await tool.restore_connection(target, path)
    assert target.rows["platform_users"] == ["already present"]


async def test_failed_restore_rolls_back_earlier_table_copies(tmp_path):
    source = Connection()
    source.rows["platform_users"] = ["author"]
    path = await tool.backup_connection(source, tmp_path / "platform.zip")
    target = Connection()
    target.fail_table = "platform_contribution_versions"
    with pytest.raises(ValueError, match="COPY"):
        await tool.restore_connection(target, path)
    assert not any(target.rows.values())


async def test_backup_never_removes_an_existing_archive(tmp_path):
    path = tmp_path / "existing.zip"
    path.write_bytes(b"retain this archive")
    with pytest.raises(FileExistsError):
        await tool.backup_connection(Connection(), path)
    assert path.read_bytes() == b"retain this archive"


async def test_checksum_and_path_validation_precede_target_writes(tmp_path):
    original = await tool.backup_connection(Connection(), tmp_path / "original.zip")
    with ZipFile(original) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    for corruption in ("checksum", "path", "migration", "unknown_table"):
        altered = dict(entries)
        if corruption == "checksum":
            altered["sql/platform_users.copy"] = b"changed body"
        elif corruption == "path":
            altered["../credentials"] = b"unexpected"
        else:
            manifest = json.loads(altered["manifest.json"])
            if corruption == "migration":
                manifest["migrations"] = {}
            else:
                manifest["tables"]["other_application"] = manifest["tables"].pop("platform_users")
            altered["manifest.json"] = json.dumps(manifest).encode()
        path = tmp_path / f"{corruption}.zip"
        with ZipFile(path, "x") as archive:
            for name, body in altered.items():
                archive.writestr(name, body)
        target = Connection()
        with pytest.raises(ValueError):
            await tool.restore_connection(target, path)
        assert not target.writes


async def test_platform_postgresql_roundtrip_with_immutable_history_and_fk_cycle(tmp_path):
    dsn = os.environ.get("PLATFORM_TEST_DATABASE_DSN")
    isolated_data_run = not dsn and os.environ.get("RUN_DATA_SQL_TESTS") == "1"
    if isolated_data_run:
        from upstox_service.config.settings import Settings

        dsn = Settings().timescale_dsn
    if not dsn:
        pytest.skip("Set PLATFORM_TEST_DATABASE_DSN to a disposable local platform_test_* database")
    parsed = urlsplit(dsn)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not (
        parsed.path.startswith("/platform_test_") or (isolated_data_run and parsed.path == "/stockgraph")
    ):
        pytest.fail("Integration database must be local and named platform_test_*")
    conn = await asyncpg.connect(dsn)
    suffix = uuid4().hex[:12]
    source_schema, target_schema = (
        f"platform_restore_test_{kind}_{suffix}" for kind in ("source", "target")
    )
    transaction = conn.transaction()
    await transaction.start()
    try:
        for schema in (source_schema, target_schema):
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}",public')
            await conn.execute(
                "CREATE TABLE platform_schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz DEFAULT now())"
            )
            for path in sorted(tool.MIGRATIONS.glob("*.sql")):
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO platform_schema_migrations(name,checksum) VALUES($1,$2)",
                    path.name,
                    tool.migration_checksums()[path.name],
                )
        user, contribution, version = uuid4(), uuid4(), uuid4()
        await conn.execute(f'SET LOCAL search_path TO "{source_schema}",public')
        await conn.execute("INSERT INTO platform_users(id,name) VALUES($1,'Author')", user)
        await conn.execute(
            "INSERT INTO platform_tokens(id,user_id,digest) VALUES($1,$2,'hash-only-no-raw-token')",
            uuid4(),
            user,
        )
        await conn.execute(
            "INSERT INTO platform_contributions(id,author_id,status,current_version_id) VALUES($1,$2,'DRAFT',$3)",
            contribution,
            user,
            version,
        )
        await conn.execute(
            "INSERT INTO platform_contribution_versions(id,contribution_id,version_number,ticker,content,event_at,expires_at) VALUES($1,$2,1,'ABC','{}',now(),now()+interval '1 day')",
            version,
            contribution,
        )
        await conn.execute(
            "INSERT INTO agent_access_audit(id,actor,action) VALUES(42,'operator','backup')"
        )
        path = await tool.backup_connection(conn, tmp_path / "sql.zip", schema=source_schema)
        await tool.restore_connection(conn, path, schema=target_schema)
        assert (
            await conn.fetchval(
                f'SELECT count(*) FROM "{target_schema}".platform_contribution_versions'
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT nextval($1::regclass)", f'"{target_schema}".agent_access_audit_id_seq'
            )
            == 43
        )
        assert (
            await conn.fetchval(f'SELECT digest FROM "{target_schema}".platform_tokens')
            == "hash-only-no-raw-token"
        )
    finally:
        # Both schemas and all test data vanish with one rollback; no existing
        # application table is truncated, deleted, or dropped.
        await transaction.rollback()
        await conn.close()


def test_source_originals_restore_immutably_and_validate_content_hashes(tmp_path):
    import hashlib

    from scripts import project_data
    from scripts.project_settings import ProjectDataSettings

    body = b"Versioned original with page evidence"
    digest = hashlib.sha256(body).hexdigest()
    manifest = {
        "tables": {"source_document_versions": {"rows": 1, "columns": []}},
        "graph_present": False,
        "redis": [],
        "documents": {digest: {"sha256": digest, "bytes": len(body)}},
    }
    path = tmp_path / "documents.zip"
    with ZipFile(path, "x") as archive:
        archive.writestr("sql/source_document_versions.copy", b"COPY fixture")
        archive.writestr(f"documents/{digest}", body)
    settings = ProjectDataSettings(
        _env_file=None, document_storage_root=str(tmp_path / "originals")
    )
    with ZipFile(path) as archive:
        project_data.validate_archive(archive, manifest)
        project_data.validate_document_targets(settings, archive, manifest)
        project_data.install_originals(settings, archive, manifest)
        target = tmp_path / "originals" / digest
        assert target.read_bytes() == body
        project_data.install_originals(settings, archive, manifest)
        assert target.read_bytes() == body
        target.write_bytes(b"corrupted existing blob")
        with pytest.raises(ValueError, match="checksum"):
            project_data.validate_document_targets(settings, archive, manifest)
        assert target.read_bytes() == b"corrupted existing blob"


def test_source_originals_reject_missing_assets_and_unsafe_hash_paths(tmp_path):
    from scripts import project_data

    path = tmp_path / "invalid-documents.zip"
    manifest = {
        "tables": {"source_document_versions": {"rows": 1}},
        "graph_present": False,
        "redis": [],
    }
    with ZipFile(path, "x") as archive:
        archive.writestr("sql/source_document_versions.copy", b"COPY fixture")
    with ZipFile(path) as archive:
        with pytest.raises(ValueError, match="missing its originals"):
            project_data.validate_archive(archive, manifest)
        manifest["documents"] = {"../escape": {"sha256": "../escape", "bytes": 0}}
        with pytest.raises(ValueError, match="archive path"):
            project_data.validate_archive(archive, manifest)


async def test_standalone_data_reset_refuses_to_invalidate_platform_records(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from scripts import project_data
    from scripts.project_settings import ProjectDataSettings

    connection = SimpleNamespace(
        fetchval=AsyncMock(side_effect=lambda query, *args: True), close=AsyncMock()
    )
    monkeypatch.setattr(project_data.asyncpg, "connect", AsyncMock(return_value=connection))
    with pytest.raises(ValueError, match="standalone Data reset would invalidate"):
        await project_data.ensure_standalone_reset_safe(ProjectDataSettings(_env_file=None))
    connection.close.assert_awaited_once()


async def test_standalone_data_reset_fails_closed_when_platform_state_cannot_be_read(monkeypatch):
    from unittest.mock import AsyncMock

    from scripts import project_data
    from scripts.project_settings import ProjectDataSettings

    monkeypatch.setattr(
        project_data.asyncpg,
        "connect",
        AsyncMock(side_effect=ConnectionError("secret credentials")),
    )
    with pytest.raises(ValueError, match="Cannot verify Platform state") as error:
        await project_data.ensure_standalone_reset_safe(ProjectDataSettings(_env_file=None))
    assert "secret credentials" not in str(error.value)
