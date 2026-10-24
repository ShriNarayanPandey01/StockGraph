"""Back up platform records; restore only to an empty initialized local database.

python -m scripts.platform_data --backup-dir backups
python -m scripts.platform_data --restore archive.zip --writers-stopped --confirm marketgraph_platform
Archives contain private application records and hashed authentication material.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import asyncpg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TABLES = (
    "platform_users",
    "platform_tokens",
    "platform_contributions",
    "platform_contribution_versions",
    "platform_contribution_requests",
    "platform_submissions",
    "platform_reviews",
    "platform_publications",
    "platform_retractions",
    "platform_outbox",
    "platform_usage",
    "platform_request_buckets",
    "watchlists",
    "conversations",
    "research_messages",
    "monitors",
    "agent_jobs",
    "opportunity_alerts",
    "agent_usage",
    "job_evidence",
    "agent_access_audit",
)
MIGRATIONS = (
    Path(__file__).resolve().parents[1] / "services/platform/src/marketgraph_platform/migrations"
)
MAX_ARCHIVE_BYTES = 4 * 1024**3


class PlatformDataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", env_file=".env", extra="ignore")
    database_dsn: SecretStr = SecretStr(
        "postgresql://platform:platform@localhost:5432/marketgraph_platform"
    )


def validate_target(dsn: str) -> None:
    parsed = urlsplit(dsn)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/marketgraph_platform"
    ):
        raise ValueError(
            "Platform maintenance is restricted to local database marketgraph_platform"
        )


def _schema(value: str) -> str:
    if value != "public" and not re.fullmatch(r"platform_restore_test_[a-z0-9_]{1,35}", value):
        raise ValueError("Unsupported maintenance schema")
    return '"' + value + '"'


def migration_checksums() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
        for path in sorted(MIGRATIONS.glob("*.sql"))
    }


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def _migration_state(conn, schema):
    rows = await conn.fetch(
        f"SELECT name,checksum FROM {_schema(schema)}.platform_schema_migrations ORDER BY name"
    )
    actual = {row["name"]: row["checksum"] for row in rows}
    if actual != migration_checksums():
        raise ValueError("Platform migration checksums do not match this application version")
    return actual


async def _columns(conn, table, schema):
    return [
        dict(row)
        for row in await conn.fetch(
            "SELECT column_name,udt_schema,udt_name,is_nullable FROM information_schema.columns "
            "WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position",
            schema,
            table,
        )
    ]


async def backup_connection(conn, destination: Path, *, schema="public") -> Path:
    _schema(schema)
    manifest = {
        "format": 1,
        "database": "marketgraph_platform",
        "created_at": datetime.now(UTC).isoformat(),
        "migrations": {},
        "tables": {},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Savepoint-compatible for opt-in isolated-schema tests; production uses a
    # repeatable-read snapshot and never includes database credentials.
    transaction = (
        conn.transaction()
        if conn.is_in_transaction()
        else conn.transaction(isolation="repeatable_read", readonly=True)
    )
    created = False
    try:
        with ZipFile(destination, "x", ZIP_DEFLATED) as archive:
            created = True
            async with transaction:
                manifest["migrations"] = await _migration_state(conn, schema)
                for table in TABLES:
                    columns = await _columns(conn, table, schema)
                    if not columns:
                        raise ValueError("Platform schema is not initialized")
                    buffer = io.BytesIO()
                    await conn.copy_from_table(
                        table, schema_name=schema, output=buffer, format="binary"
                    )
                    body = buffer.getvalue()
                    archive.writestr(f"sql/{table}.copy", body)
                    manifest["tables"][table] = {
                        "columns": columns,
                        "sha256": _digest(body),
                        "rows": await conn.fetchval(
                            f'SELECT count(*) FROM {_schema(schema)}."{table}"'
                        ),
                    }
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        with ZipFile(destination) as archive:
            validate_archive(archive)
    except Exception:
        # A partial export is never presented as recoverable.
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def validate_archive(archive: ZipFile) -> dict:
    names = archive.namelist()
    expected = {"manifest.json", *(f"sql/{table}.copy" for table in TABLES)}
    if len(names) != len(set(names)) or set(names) != expected:
        raise ValueError("Archive members do not match the platform table allowlist")
    if sum(member.file_size for member in archive.infolist()) > MAX_ARCHIVE_BYTES:
        raise ValueError("Platform archive exceeds the supported restore size")
    if archive.testzip() is not None:
        raise ValueError("Platform archive failed ZIP integrity validation")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format") != 1 or manifest.get("database") != "marketgraph_platform":
        raise ValueError("Not a platform backup")
    if manifest.get("migrations") != migration_checksums() or set(
        manifest.get("tables", {})
    ) != set(TABLES):
        raise ValueError("Archive migration or table manifest mismatch")
    for table, entry in manifest["tables"].items():
        if not isinstance(entry.get("rows"), int) or entry["rows"] < 0 or not entry.get("columns"):
            raise ValueError("Invalid table manifest")
        if _digest(archive.read(f"sql/{table}.copy")) != entry.get("sha256"):
            raise ValueError("Platform table checksum mismatch")
    return manifest


async def restore_connection(conn, source: Path, *, schema="public") -> None:
    _schema(schema)
    with ZipFile(source) as archive:
        manifest = validate_archive(archive)  # Validate every member before writes.
        async with conn.transaction():
            await _migration_state(conn, schema)
            await conn.execute(
                "LOCK TABLE "
                + ",".join(f'{_schema(schema)}."{table}"' for table in TABLES)
                + " IN ACCESS EXCLUSIVE MODE"
            )
            for table in TABLES:
                if await conn.fetchval(f'SELECT EXISTS(SELECT 1 FROM {_schema(schema)}."{table}")'):
                    raise ValueError("Restore requires an empty initialized platform database")
                if await _columns(conn, table, schema) != manifest["tables"][table]["columns"]:
                    raise ValueError("Target column types do not match the platform archive")
            await conn.execute("SET CONSTRAINTS ALL DEFERRED")
            for table in TABLES:
                entry = manifest["tables"][table]
                await conn.copy_to_table(
                    table,
                    schema_name=schema,
                    columns=[column["column_name"] for column in entry["columns"]],
                    source=io.BytesIO(archive.read(f"sql/{table}.copy")),
                    format="binary",
                )
                count = await conn.fetchval(f'SELECT count(*) FROM {_schema(schema)}."{table}"')
                if count != entry["rows"]:
                    raise ValueError("Restored table count mismatch")
            await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            for table in TABLES:
                for column in manifest["tables"][table]["columns"]:
                    name = column["column_name"]
                    sequence = await conn.fetchrow(
                        "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE c.oid=pg_get_serial_sequence($1,$2)::regclass",
                        f'{_schema(schema)}."{table}"',
                        name,
                    )
                    if sequence:
                        safe_column = '"' + name.replace('"', '""') + '"'
                        maximum = await conn.fetchval(
                            f'SELECT max({safe_column}) FROM {_schema(schema)}."{table}"'
                        )
                        quoted_sequence = ".".join(
                            '"' + sequence[key].replace('"', '""') + '"'
                            for key in ("nspname", "relname")
                        )
                        # RESTART is transactional; setval would survive rollback.
                        await conn.execute(
                            f"ALTER SEQUENCE {quoted_sequence} RESTART WITH {max(1, (maximum or 0) + 1)}"
                        )


async def run(args):
    dsn = PlatformDataSettings().database_dsn.get_secret_value()
    validate_target(dsn)
    if args.restore and (not args.writers_stopped or args.confirm != "marketgraph_platform"):
        raise ValueError(
            "Stop platform writers and supply --writers-stopped --confirm marketgraph_platform"
        )
    if args.restore:
        with ZipFile(args.restore) as archive:
            validate_archive(archive)
    conn = await asyncpg.connect(dsn)
    try:
        if args.restore:
            await restore_connection(conn, Path(args.restore))
            print("Restored platform application records into the empty initialized database.")
        else:
            path = Path(args.backup_dir) / (
                datetime.now(UTC).strftime("marketgraph-platform-%Y%m%dT%H%M%S-%fZ") + ".zip"
            )
            await backup_connection(conn, path)
            print(json.dumps({"backup": str(path.resolve()), "database": "marketgraph_platform"}))
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--restore")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--confirm", default="")
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as exc:
        parser.exit(
            1,
            f"Platform maintenance failed ({type(exc).__name__}); target records were not replaced.\n",
        )


if __name__ == "__main__":
    main()
