"""Back up/reset/restore ONLY this project's explicit local data targets.

Run as ``python -m scripts.project_data`` from the repository root. Reset is
opt-in and requires stopped writers; there is deliberately no FLUSHDB/CASCADE.
Backups contain licensed news payloads and must not be committed.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import asyncpg
import redis

from scripts.project_settings import ProjectDataSettings

TABLES = (
    "vendor_quotes_raw",
    "daily_stock_metrics",
    "daily_macro_and_flows",
    "macro_observations",
    "quarterly_financials",
    "institutional_deals_raw",
    "monthly_mf_holdings_raw",
    "ingest_runs",
    "vendor_sync_state",
    "news_raw",
    "news_fetch_state",
    "entity_catalog",
    "entity_catalog_versions",
    "registration_jobs",
    "graph_outbox",
    "stock_fundamentals_raw",
    "normalized_news",
    "equity_instruments",
    "equity_universe_refresh",
    "stock_company_profiles",
    "stock_company_profile_versions",
    "stock_shareholding_versions",
    "stock_shareholding_sync",
    "stock_daily_candles_raw",
    "stock_daily_candles",
    "stock_daily_candle_fetches",
)
# Preserve provider quota/degraded-provider and LLM spend/cache ledgers. The
# scheduler store is removed only after writers have been explicitly stopped.
REDIS_PATTERNS = (
    "stockgraph:*",
    "seen:*",
    "lock:stream_news*",
    "lock:daily_*",
    "lock:quarterly*",
    "lock:periodic_*",
    "apscheduler.jobs",
    "apscheduler.run_times",
    "upstox:lock:*",
    "upstox:scheduler:*",
    "upstox:market:v1:*",
)
CONFIRMATION = "stockgraph/stock_graph"


def validate_targets(settings: ProjectDataSettings) -> None:
    sql = urlsplit(settings.timescale_dsn)
    cache = urlsplit(settings.redis_url)
    if sql.path != "/stockgraph" or sql.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Refusing: reset is restricted to local database stockgraph")
    if settings.falkor_graph_name != "stock_graph" or settings.falkor_host not in {
        "localhost",
        "127.0.0.1",
    }:
        raise ValueError("Refusing: reset is restricted to local graph stock_graph")
    if cache.hostname not in {"localhost", "127.0.0.1"} or cache.path not in {"", "/0"}:
        raise ValueError("Refusing: reset is restricted to local project Redis database 0")
    if settings.falkor_port == cache.port:
        raise ValueError("Refusing: graph and application Redis must be separate servers")


def project_keys(client: redis.Redis) -> list[bytes]:
    return sorted({key for pattern in REDIS_PATTERNS for key in client.scan_iter(match=pattern)})


async def backup(settings: ProjectDataSettings, directory: Path) -> Path:
    validate_targets(settings)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (datetime.now(UTC).strftime("stockgraph-%Y%m%dT%H%M%S-%fZ") + ".zip")
    manifest = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "database": "stockgraph",
        "graph": "stock_graph",
        "tables": {},
        "redis": [],
    }
    sql = await asyncpg.connect(settings.timescale_dsn)
    graph = redis.Redis(host=settings.falkor_host, port=settings.falkor_port)
    cache = redis.Redis.from_url(settings.redis_url)
    try:
        with ZipFile(path, "x", ZIP_DEFLATED) as archive:
            async with sql.transaction(isolation="repeatable_read", readonly=True):
                for table in TABLES:
                    exists = await sql.fetchval("SELECT to_regclass($1)", f"public.{table}")
                    if not exists:
                        continue
                    columns = await sql.fetch(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position",
                        table,
                    )
                    stream = io.BytesIO()
                    await sql.copy_from_table(
                        table, schema_name="public", output=stream, format="binary"
                    )
                    archive.writestr(f"sql/{table}.copy", stream.getvalue())
                    manifest["tables"][table] = {
                        "columns": [r["column_name"] for r in columns],
                        "rows": await sql.fetchval(f'SELECT count(*) FROM public."{table}"'),
                    }
            graph_value = graph.dump("stock_graph")
            manifest["graph_present"] = graph_value is not None
            if graph_value is not None:
                archive.writestr("graph.dump", graph_value)
            for index, key in enumerate(project_keys(cache)):
                value = cache.dump(key)
                if value is None:
                    continue
                archive.writestr(f"redis/{index}.dump", value)
                manifest["redis"].append(
                    {"key": key.decode(), "ttl": cache.pttl(key), "index": index}
                )
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        # Read every compressed member before any destructive operation.
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Backup integrity check failed; reset cancelled")
        print(
            json.dumps(
                {
                    "backup": str(path.resolve()),
                    "rows": {k: v["rows"] for k, v in manifest["tables"].items()},
                    "graph_backed_up": manifest["graph_present"],
                    "redis_keys": len(manifest["redis"]),
                }
            )
        )
        return path
    finally:
        await sql.close()
        graph.close()
        cache.close()


async def reset(settings: ProjectDataSettings) -> None:
    validate_targets(settings)
    sql = await asyncpg.connect(settings.timescale_dsn)
    graph = redis.Redis(host=settings.falkor_host, port=settings.falkor_port)
    cache = redis.Redis.from_url(settings.redis_url)
    try:
        tables = [
            table
            for table in TABLES
            if await sql.fetchval("SELECT to_regclass($1)", f"public.{table}")
        ]
        if tables:
            # A missing FK dependency aborts safely instead of cascading to an
            # unrelated table. SQL structure, users, extensions and volumes stay.
            async with sql.transaction():
                await sql.execute(
                    "TRUNCATE "
                    + ",".join(f'public."{table}"' for table in tables)
                    + " RESTART IDENTITY"
                )
        if graph.exists("stock_graph"):
            graph.execute_command("GRAPH.DELETE", "stock_graph")
        keys = project_keys(cache)
        if keys:
            cache.delete(*keys)
        print(
            "Cleared project application data only; backup is recoverable. Quota/spend ledgers preserved."
        )
    finally:
        await sql.close()
        graph.close()
        cache.close()


async def restore(settings: ProjectDataSettings, path: Path) -> None:
    validate_targets(settings)
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Invalid backup")
        manifest = json.loads(archive.read("manifest.json"))
        if (
            manifest.get("database") != "stockgraph"
            or manifest.get("graph") != "stock_graph"
            or manifest.get("format") != 1
        ):
            raise ValueError("Not a project backup")
        validate_archive(archive, manifest)
        sql = await asyncpg.connect(settings.timescale_dsn)
        graph = redis.Redis(host=settings.falkor_host, port=settings.falkor_port)
        cache = redis.Redis.from_url(settings.redis_url)
        try:
            async with sql.transaction():
                for table, entry in manifest["tables"].items():
                    await sql.copy_to_table(
                        table,
                        schema_name="public",
                        columns=entry["columns"],
                        source=io.BytesIO(archive.read(f"sql/{table}.copy")),
                        format="binary",
                    )
                    for column in entry["columns"]:
                        sequence = await sql.fetchval(
                            "SELECT pg_get_serial_sequence($1,$2)", f"public.{table}", column
                        )
                        if sequence:
                            safe_column = column.replace('"', '""')
                            maximum = await sql.fetchval(
                                f'SELECT max("{safe_column}") FROM public."{table}"'
                            )
                            await sql.fetchval(
                                "SELECT setval($1::regclass,$2,$3)",
                                sequence,
                                max(1, maximum or 1),
                                maximum is not None,
                            )
            if manifest["graph_present"]:
                graph.restore("stock_graph", 0, archive.read("graph.dump"), replace=True)
            for entry in manifest["redis"]:
                ttl = max(0, entry["ttl"])
                cache.restore(
                    entry["key"], ttl, archive.read(f"redis/{entry['index']}.dump"), replace=True
                )
        finally:
            await sql.close()
            graph.close()
            cache.close()
    print("Restored project backup; verify graph and service status before resuming writers.")


def validate_archive(archive: ZipFile, manifest: dict) -> None:
    if not set(manifest["tables"]) <= set(TABLES):
        raise ValueError("Backup contains a table outside the project allowlist")
    for table in manifest["tables"]:
        archive.getinfo(f"sql/{table}.copy")
    if manifest["graph_present"]:
        archive.getinfo("graph.dump")
    for entry in manifest["redis"]:
        if not any(fnmatch(entry["key"], pattern) for pattern in REDIS_PATTERNS):
            raise ValueError("Backup contains a Redis key outside the project allowlist")
        archive.getinfo(f"redis/{entry['index']}.dump")


async def run(args: argparse.Namespace) -> None:
    settings = ProjectDataSettings()
    validate_targets(settings)
    if args.reset or args.restore:
        if args.confirm != CONFIRMATION or not args.writers_stopped:
            raise ValueError(
                "Stop project writers and supply --writers-stopped --confirm stockgraph/stock_graph"
            )
    if args.restore:
        # Validate the entire requested archive BEFORE resetting any existing data.
        with ZipFile(args.restore) as archive:
            if archive.testzip() is not None:
                raise ValueError("Invalid backup")
            manifest = json.loads(archive.read("manifest.json"))
            if (manifest.get("database"), manifest.get("graph"), manifest.get("format")) != (
                "stockgraph",
                "stock_graph",
                1,
            ):
                raise ValueError("Not a project backup")
            validate_archive(archive, manifest)
    await backup(settings, Path(args.backup_dir))
    if args.reset or args.restore:
        await reset(settings)
    if args.restore:
        await restore(settings, Path(args.restore))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--reset", action="store_true")
    operations.add_argument("--restore", metavar="BACKUP_ZIP")
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--writers-stopped", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
