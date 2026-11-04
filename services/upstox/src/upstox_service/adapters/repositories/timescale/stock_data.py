"""SQL-owned equity directory, fundamentals and daily chart history."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from upstox_service.domain.equity import is_company_equity

STOCK_DATA_DDL = """
CREATE TABLE IF NOT EXISTS equity_instruments (
    exchange text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    instrument_key text NOT NULL,
    trading_symbol text NOT NULL,
    isin text NOT NULL,
    name text NOT NULL,
    short_name text,
    payload jsonb NOT NULL,
    active boolean NOT NULL DEFAULT true,
    source_as_of timestamptz NOT NULL,
    PRIMARY KEY(exchange,instrument_key)
);
CREATE INDEX IF NOT EXISTS equity_instruments_lookup
    ON equity_instruments(exchange,trading_symbol) WHERE active;
CREATE INDEX IF NOT EXISTS equity_instruments_isin
    ON equity_instruments(isin) WHERE active;
CREATE TABLE IF NOT EXISTS equity_universe_refresh (
    source_id text PRIMARY KEY, source_as_of timestamptz NOT NULL,
    instrument_count int NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_company_profiles (
    isin text PRIMARY KEY, profile jsonb NOT NULL, vendor_id text NOT NULL,
    vendor_as_of timestamptz NOT NULL, content_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_company_profile_versions (
    isin text NOT NULL, content_hash text NOT NULL, profile jsonb NOT NULL,
    vendor_id text NOT NULL, vendor_as_of timestamptz NOT NULL,
    PRIMARY KEY(isin,content_hash)
);
CREATE TABLE IF NOT EXISTS stock_shareholding_versions (
    isin text NOT NULL, period text NOT NULL, category text NOT NULL,
    percentage numeric(7,4) NOT NULL, content_hash text NOT NULL,
    vendor_id text NOT NULL, vendor_as_of timestamptz NOT NULL,
    PRIMARY KEY(isin,period,category,content_hash)
);
CREATE INDEX IF NOT EXISTS stock_shareholding_latest
    ON stock_shareholding_versions(isin,period,category,vendor_as_of DESC);
CREATE TABLE IF NOT EXISTS stock_shareholding_snapshots (
    isin text NOT NULL, vendor_as_of timestamptz NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY(isin,vendor_as_of)
);
CREATE TABLE IF NOT EXISTS stock_shareholding_sync (
    isin text PRIMARY KEY, vendor_as_of timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_daily_candles_raw (
    exchange text NOT NULL, isin text NOT NULL, trade_date date NOT NULL,
    content_hash text NOT NULL, payload jsonb NOT NULL,
    vendor_id text NOT NULL, vendor_as_of timestamptz NOT NULL,
    PRIMARY KEY(exchange,isin,trade_date,content_hash)
);
CREATE TABLE IF NOT EXISTS stock_daily_candles (
    exchange text NOT NULL, isin text NOT NULL, trade_date date NOT NULL,
    open_price numeric(18,4) NOT NULL, high_price numeric(18,4) NOT NULL,
    low_price numeric(18,4) NOT NULL, close_price numeric(18,4) NOT NULL,
    volume bigint NOT NULL, vendor_id text NOT NULL,
    vendor_as_of timestamptz NOT NULL, content_hash text NOT NULL,
    PRIMARY KEY(exchange,isin,trade_date)
);
CREATE TABLE IF NOT EXISTS stock_daily_candle_fetches (
    exchange text NOT NULL, isin text NOT NULL, from_date date NOT NULL,
    to_date date NOT NULL, fetched_at timestamptz NOT NULL,
    PRIMARY KEY(exchange,isin,from_date,to_date)
);
"""


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def init_stock_data_schema(repository: Any) -> None:
    from upstox_service.adapters.repositories.timescale.migrations import apply_migration
    pool = await repository.connect()
    async with pool.acquire() as conn:
        await apply_migration(conn,"003_stock_data",STOCK_DATA_DDL)


class StockDataRepository:
    """Composes the DataRepository connection; no graph/outbox methods are called."""

    def __init__(self, repository: Any):
        self._repository = repository

    async def refresh_universe(self, instruments: list[dict]) -> dict[str, int]:
        by_exchange = {exchange: [] for exchange in ("NSE", "BSE")}
        for row in instruments:
            exchange = row.get("exchange")
            if exchange in by_exchange and is_company_equity(row, exchange):
                by_exchange[exchange].append(row)
        if not all(by_exchange.values()):
            raise ValueError("Both NSE and BSE equity files must contain stocks")
        now = datetime.now(UTC)
        pool = await self._repository.connect()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(72201701)")
            await conn.execute("UPDATE equity_instruments SET active=false WHERE active")
            for exchange, rows in by_exchange.items():
                await conn.executemany(
                    """
                    INSERT INTO equity_instruments
                      (exchange,instrument_key,trading_symbol,isin,name,short_name,
                       payload,active,source_as_of)
                    VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,true,$8)
                    ON CONFLICT(exchange,instrument_key) DO UPDATE SET
                      trading_symbol=EXCLUDED.trading_symbol,isin=EXCLUDED.isin,
                      name=EXCLUDED.name,short_name=EXCLUDED.short_name,
                      payload=EXCLUDED.payload,active=true,source_as_of=EXCLUDED.source_as_of
                    """,
                    [
                        (
                            exchange, r["instrument_key"], r["trading_symbol"],
                            r["isin"], r.get("name") or r["trading_symbol"],
                            r.get("short_name"), json.dumps(r), now,
                        )
                        for r in rows
                    ],
                )
                await conn.execute(
                    """INSERT INTO equity_universe_refresh(source_id,source_as_of,instrument_count)
                       VALUES($1,$2,$3) ON CONFLICT(source_id) DO UPDATE SET
                       source_as_of=EXCLUDED.source_as_of,
                       instrument_count=EXCLUDED.instrument_count""",
                    exchange, now, len(rows),
                )
        return {exchange: len(rows) for exchange, rows in by_exchange.items()}

    async def upsert_instrument(self, row: dict) -> None:
        """Cache a resolved equity before the next BOD refresh, without registration."""
        exchange = str(row.get("exchange") or row.get("segment", "").split("_")[0])
        if not is_company_equity(row, exchange):
            raise ValueError("Only NSE/BSE company equity instruments are supported")
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO equity_instruments
                   (exchange,instrument_key,trading_symbol,isin,name,short_name,payload,source_as_of)
                   VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,now())
                   ON CONFLICT(exchange,instrument_key) DO UPDATE SET
                   trading_symbol=EXCLUDED.trading_symbol,isin=EXCLUDED.isin,
                   name=EXCLUDED.name,short_name=EXCLUDED.short_name,
                   payload=EXCLUDED.payload,active=true,source_as_of=EXCLUDED.source_as_of""",
                exchange, row["instrument_key"], row["trading_symbol"], row["isin"],
                row.get("name") or row["trading_symbol"], row.get("short_name"),
                json.dumps(row),
            )

    async def search_instruments(
        self, query: str, exchange: str | None, after: tuple[str, str, str] | None,
        limit: int,
    ) -> list[dict]:
        pool = await self._repository.connect()
        escaped = query.replace("\\", "\\\\").replace("%", "\\%" ).replace("_", "\\_")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.exchange,e.instrument_key,e.trading_symbol,e.isin,e.name,
                       e.short_name,e.source_as_of,
                       EXISTS(SELECT 1 FROM entity_catalog c WHERE c.kind='Stock'
                          AND (c.payload->>'isin'=e.isin OR
                               (c.entity_id=e.trading_symbol AND
                                coalesce(c.payload->>'isin','')='')) ) AS registered
                FROM equity_instruments e
                WHERE e.active AND ($1::text IS NULL OR e.exchange=$1)
                  AND ($2::text='' OR e.trading_symbol ILIKE '%'||$2||'%' ESCAPE '\\'
                       OR e.name ILIKE '%'||$2||'%' ESCAPE '\\'
                       OR e.isin ILIKE '%'||$2||'%' ESCAPE '\\')
                  AND ($3::text IS NULL OR
                       (e.exchange,e.trading_symbol,e.instrument_key) > ($3,$4,$5))
                ORDER BY e.exchange,e.trading_symbol,e.instrument_key
                LIMIT $6
                """,
                exchange, escaped, *(after or (None, None, None)), limit,
            )
        return [dict(row) for row in rows]

    async def get_instrument(self, ticker: str, exchange: str) -> dict | None:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT exchange,instrument_key,trading_symbol,isin,name,short_name,
                          source_as_of FROM equity_instruments
                   WHERE active AND exchange=$1 AND trading_symbol=$2
                   LIMIT 2""",
                exchange, ticker.upper(),
            )
        if len(rows) > 1:
            raise ValueError("Ambiguous symbol within exchange; use an ISIN")
        return dict(rows[0]) if rows else None

    async def is_registered(self, ticker: str, isin: str) -> bool:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            return bool(await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM entity_catalog WHERE kind='Stock'
                   AND (payload->>'isin'=$1 OR
                        (entity_id=$2 AND coalesce(payload->>'isin','')='')))""",
                isin, ticker,
            ))

    async def get_profile(self, isin: str) -> dict | None:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile,vendor_id,vendor_as_of FROM stock_company_profiles WHERE isin=$1",
                isin,
            )
        return {"profile": _json(row["profile"]), "vendor_id": row["vendor_id"],
                "vendor_as_of": row["vendor_as_of"]} if row else None

    async def save_profile(self, isin: str, profile: dict, as_of: datetime) -> None:
        digest = _hash(profile)
        pool = await self._repository.connect()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO stock_company_profile_versions
                   (isin,content_hash,profile,vendor_id,vendor_as_of)
                   VALUES($1,$2,$3::jsonb,'UPSTOX',$4) ON CONFLICT DO NOTHING""",
                isin, digest, json.dumps(profile), as_of,
            )
            await conn.execute(
                """INSERT INTO stock_company_profiles
                   (isin,profile,vendor_id,vendor_as_of,content_hash)
                   VALUES($1,$2::jsonb,'UPSTOX',$3,$4)
                   ON CONFLICT(isin) DO UPDATE SET profile=EXCLUDED.profile,
                   vendor_as_of=EXCLUDED.vendor_as_of,content_hash=EXCLUDED.content_hash""",
                isin, json.dumps(profile), as_of, digest,
            )

    async def get_shareholding(self, isin: str) -> dict:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            snapshot = await conn.fetchrow(
                "SELECT payload,vendor_as_of FROM stock_shareholding_snapshots "
                "WHERE isin=$1 ORDER BY vendor_as_of DESC LIMIT 1", isin,
            )
            if snapshot:
                return {"rows": [
                    {**r, "vendor_id": "UPSTOX", "vendor_as_of": snapshot["vendor_as_of"]}
                    for r in _json(snapshot["payload"])
                ], "vendor_as_of": snapshot["vendor_as_of"]}
            rows = await conn.fetch(
                """SELECT DISTINCT ON (period,category) period,category,percentage,
                          vendor_id,vendor_as_of
                   FROM stock_shareholding_versions WHERE isin=$1
                   ORDER BY period,category,vendor_as_of DESC""", isin,
            )
            as_of = await conn.fetchval(
                "SELECT vendor_as_of FROM stock_shareholding_sync WHERE isin=$1", isin,
            )
        return {"rows": [dict(r) for r in rows], "vendor_as_of": as_of}

    async def save_shareholding(self, isin: str, rows: list[dict], as_of: datetime) -> None:
        pool = await self._repository.connect()
        async with pool.acquire() as conn, conn.transaction():
            # Whole observation snapshots preserve A -> B -> A and category removals.
            await conn.execute(
                "INSERT INTO stock_shareholding_snapshots(isin,vendor_as_of,payload) "
                "VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING",
                isin, as_of, json.dumps(rows, default=str),
            )
            await conn.executemany(
                """INSERT INTO stock_shareholding_versions
                   (isin,period,category,percentage,content_hash,vendor_id,vendor_as_of)
                   VALUES($1,$2,$3,$4,$5,'UPSTOX',$6) ON CONFLICT DO NOTHING""",
                [
                    (isin, r["period"], r["category"], r["percentage"], _hash(r), as_of)
                    for r in rows
                ],
            )
            await conn.execute(
                """INSERT INTO stock_shareholding_sync(isin,vendor_as_of) VALUES($1,$2)
                   ON CONFLICT(isin) DO UPDATE SET vendor_as_of=EXCLUDED.vendor_as_of""",
                isin, as_of,
            )

    async def has_candle_coverage(
        self, exchange: str, isin: str, start: date, end: date
    ) -> bool:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            return bool(await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM stock_daily_candle_fetches
                   WHERE exchange=$1 AND isin=$2 AND from_date<=$3 AND to_date>=$4
                   AND (to_date<current_date-10 OR fetched_at>now()-interval '1 day'))""",
                exchange, isin, start, end,
            ))

    async def save_candles(
        self, exchange: str, isin: str, start: date, end: date,
        candles: list[dict], as_of: datetime,
    ) -> None:
        pool = await self._repository.connect()
        async with pool.acquire() as conn, conn.transaction():
            for candle in candles:
                digest = _hash(candle)
                await conn.execute(
                    """INSERT INTO stock_daily_candles_raw
                       (exchange,isin,trade_date,content_hash,payload,vendor_id,vendor_as_of)
                       VALUES($1,$2,$3,$4,$5::jsonb,'UPSTOX',$6)
                       ON CONFLICT DO NOTHING""",
                    exchange, isin, candle["trade_date"], digest,
                    json.dumps(candle, default=str), as_of,
                )
                await conn.execute(
                    """INSERT INTO stock_daily_candles
                       (exchange,isin,trade_date,open_price,high_price,low_price,
                        close_price,volume,vendor_id,vendor_as_of,content_hash)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,'UPSTOX',$9,$10)
                       ON CONFLICT(exchange,isin,trade_date) DO UPDATE SET
                       open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,
                       low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,
                       volume=EXCLUDED.volume,vendor_as_of=EXCLUDED.vendor_as_of,
                       content_hash=EXCLUDED.content_hash""",
                    exchange, isin, candle["trade_date"], candle["open"],
                    candle["high"], candle["low"], candle["close"], candle["volume"],
                    as_of, digest,
                )
            await conn.execute(
                """INSERT INTO stock_daily_candle_fetches
                   (exchange,isin,from_date,to_date,fetched_at)
                   VALUES($1,$2,$3,$4,$5) ON CONFLICT(exchange,isin,from_date,to_date)
                   DO UPDATE SET fetched_at=EXCLUDED.fetched_at""",
                exchange, isin, start, end, as_of,
            )

    async def get_candles(
        self, exchange: str, isin: str, start: date, end: date
    ) -> list[dict]:
        pool = await self._repository.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT trade_date,open_price AS open,high_price AS high,
                          low_price AS low,close_price AS close,volume,
                          vendor_id,vendor_as_of FROM stock_daily_candles
                   WHERE exchange=$1 AND isin=$2 AND trade_date BETWEEN $3 AND $4
                   ORDER BY trade_date""",
                exchange, isin, start, end,
            )
        return [dict(row) for row in rows]
