"""PostgreSQL/TimescaleDB repository (Rule 2: all numerics live here, SQL-only)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import asyncpg

from upstox_service.config.settings import settings
from upstox_service.domain.enums import Window

DDL_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Immutable vendor staging (Rule 7): every numeric value enters here first.
-- Vintage key includes fetched_at: a revised payload is staged as a NEW row
-- (never overwritten). Downstream reads take the latest vintage per key via
-- LATEST_VINTAGE_QUERY (DISTINCT ON ... ORDER BY fetched_at DESC).
CREATE TABLE IF NOT EXISTS vendor_quotes_raw (
    vendor_id VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    series VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor_id, ticker, trade_date, series, fetched_at)
);

CREATE TABLE IF NOT EXISTS daily_stock_metrics (
    trade_date DATE NOT NULL,
    session_type VARCHAR(10) NOT NULL DEFAULT 'CLOSE',
    ticker VARCHAR(20) NOT NULL,
    open_price NUMERIC(12, 2),
    high_price NUMERIC(12, 2),
    low_price NUMERIC(12, 2),
    close_price NUMERIC(12, 2) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    delivery_qty BIGINT,
    delivery_pct NUMERIC(5, 2),
    delivery_20d_avg NUMERIC(5, 2),
    delivery_20d_zscore NUMERIC(6, 2),
    pe_ratio NUMERIC(8, 2),
    pb_ratio NUMERIC(8, 2),
    ev_ebitda NUMERIC(8, 2),
    pe_5yr_percentile NUMERIC(5, 2),
    vendor_id VARCHAR(50) NOT NULL,
    vendor_as_of TIMESTAMPTZ NOT NULL,
    delivery_vendor_id VARCHAR(50),
    delivery_vendor_as_of TIMESTAMPTZ,
    PRIMARY KEY (trade_date, session_type, ticker)
);
SELECT create_hypertable('daily_stock_metrics', 'trade_date', if_not_exists => TRUE);
ALTER TABLE daily_stock_metrics ADD COLUMN IF NOT EXISTS delivery_vendor_id VARCHAR(50);
ALTER TABLE daily_stock_metrics ADD COLUMN IF NOT EXISTS delivery_vendor_as_of TIMESTAMPTZ;

-- Single-row-per-day table: plain table, not a hypertable.
CREATE TABLE IF NOT EXISTS daily_macro_and_flows (
    trade_date DATE NOT NULL PRIMARY KEY,
    brent_crude_usd NUMERIC(10, 2),
    hrc_steel_inr NUMERIC(12, 2),
    coking_coal_usd NUMERIC(10, 2),
    usd_inr NUMERIC(8, 4),
    fii_net_cash_cr NUMERIC(12, 2),
    dii_net_cash_cr NUMERIC(12, 2),
    vendor_id VARCHAR(50) NOT NULL,
    vendor_as_of TIMESTAMPTZ NOT NULL
);

-- Official monthly / bi-monthly releases (CPI, GDP, RBI Repo, capex) have
-- their own cadence and cannot be represented by the daily market table.
-- This is append-only: a revised release gets a new valid_from_ts vintage.
CREATE TABLE IF NOT EXISTS macro_observations (
    macro_id VARCHAR(80) NOT NULL,
    observation_date DATE NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    valid_from_ts BIGINT NOT NULL,
    value NUMERIC(18, 6) NOT NULL,
    unit VARCHAR(40),
    source_id VARCHAR(80) NOT NULL,
    source_as_of TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (macro_id, observation_date, valid_from_ts)
);
CREATE INDEX IF NOT EXISTS macro_observations_lookup_idx
    ON macro_observations (macro_id, observation_date DESC, valid_from_ts DESC);

CREATE TABLE IF NOT EXISTS quarterly_financials (
    ticker VARCHAR(20) NOT NULL,
    quarter_label VARCHAR(10) NOT NULL,
    published_date DATE NOT NULL,
    valid_from_ts BIGINT NOT NULL,
    revenue_cr NUMERIC(14, 2),
    rev_yoy_pct NUMERIC(6, 2),
    ebitda_cr NUMERIC(14, 2),
    ebitda_margin_pct NUMERIC(6, 2),
    pat_cr NUMERIC(14, 2),
    pat_yoy_pct NUMERIC(6, 2),
    debt_to_equity NUMERIC(6, 2),
    operating_cash_flow_cr NUMERIC(14, 2),
    free_cash_flow_cr NUMERIC(14, 2),
    order_book_cr NUMERIC(14, 2),
    promoter_holding_pct NUMERIC(5, 2),
    promoter_pledge_pct NUMERIC(5, 2),
    fii_holding_pct NUMERIC(5, 2),
    dii_holding_pct NUMERIC(5, 2),
    source_id VARCHAR(80) NOT NULL DEFAULT 'OFFICIAL_FILING',
    source_as_of TIMESTAMPTZ,
    -- Restatements/re-audits land as new vintages (never overwrite).
    PRIMARY KEY (ticker, quarter_label, valid_from_ts)
);

-- Safe for databases initialized by earlier milestones.
ALTER TABLE quarterly_financials
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(80) NOT NULL DEFAULT 'OFFICIAL_FILING';
ALTER TABLE quarterly_financials
    ADD COLUMN IF NOT EXISTS source_as_of TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS institutional_deals_raw (
    trade_date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    actor_name TEXT NOT NULL,
    actor_category VARCHAR(20) NOT NULL,
    deal_type VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    qty BIGINT,
    value_cr NUMERIC(14, 2),
    PRIMARY KEY (trade_date, ticker, actor_name, deal_type, side)
);
SELECT create_hypertable('institutional_deals_raw', 'trade_date', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS monthly_mf_holdings_raw (
    month DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    amc_id VARCHAR(50) NOT NULL,
    amc_name TEXT NOT NULL,
    shares_held BIGINT,
    stake_pct NUMERIC(6, 3),
    delta_stake_pct NUMERIC(6, 3),
    valid_from_ts BIGINT NOT NULL,
    valid_to_ts BIGINT NOT NULL DEFAULT 9999999999,
    -- In-month corrections land as new vintages (never overwrite).
    PRIMARY KEY (month, ticker, amc_id, valid_from_ts)
);

-- Ops log for the hardened scheduler (Rule 6).
CREATE TABLE IF NOT EXISTS ingest_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Backfill watermark (Rule 7): last data pushed per vendor series.
CREATE TABLE IF NOT EXISTS vendor_sync_state (
    vendor_id VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    series VARCHAR(50) NOT NULL,
    last_trade_date DATE NOT NULL,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vendor_id, ticker, series)
);

-- Immutable raw news staging (Rule 7 pattern, applied to news providers).
-- Every provider payload lands here BEFORE any graph write, so LLM routing
-- and embeddings can be replayed without re-spending metered API quota.
-- Vintage key includes fetched_at: a re-fetched/corrected article is a NEW
-- row, never an overwrite. The graph remains the serving store.
CREATE TABLE IF NOT EXISTS news_raw (
    provider_id VARCHAR(50) NOT NULL,
    external_id VARCHAR(160) NOT NULL,
    published_at TIMESTAMPTZ,
    source_url TEXT,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_id, external_id, fetched_at)
);
CREATE INDEX IF NOT EXISTS news_raw_lookup_idx
    ON news_raw (provider_id, published_at DESC);

-- Per-provider incremental fetch watermark. Only moves forward.
CREATE TABLE IF NOT EXISTS news_fetch_state (
    provider_id VARCHAR(50) PRIMARY KEY,
    last_published_at TIMESTAMPTZ,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Rule 7 normalization read: one row per key, latest vintage wins.
LATEST_VINTAGE_QUERY = """
SELECT DISTINCT ON (vendor_id, ticker, trade_date, series)
       vendor_id, ticker, trade_date, series, payload, fetched_at
FROM vendor_quotes_raw
WHERE vendor_id = $1 AND ticker = $2 AND trade_date >= $3 AND trade_date <= $4
ORDER BY vendor_id, ticker, trade_date, series, fetched_at DESC
"""

RANGE_QUERY = """
SELECT trade_date, session_type, open_price, high_price, low_price, close_price,
       volume, delivery_qty, delivery_pct, delivery_20d_zscore,
       delivery_vendor_id, delivery_vendor_as_of,
       pe_ratio, pb_ratio, ev_ebitda, pe_5yr_percentile,
       vendor_id, vendor_as_of
FROM daily_stock_metrics
WHERE ticker = $1 AND trade_date >= $2 AND trade_date <= $3
ORDER BY trade_date ASC, CASE WHEN session_type = 'OPEN' THEN 1 ELSE 2 END ASC
"""

# SQL-only anomalies (Rule 2): computed on CLOSE session with full Bhavcopy delivery.
ANOMALIES_QUERY = """
SELECT trade_date, session_type, delivery_pct, delivery_20d_zscore, pe_ratio, pe_5yr_percentile
FROM daily_stock_metrics
WHERE ticker = $1 AND trade_date >= $2 AND trade_date <= $3
  AND session_type = 'CLOSE'
  AND ABS(delivery_20d_zscore) >= $4
ORDER BY trade_date ASC
"""

MONTHLY_AGGREGATES_QUERY = """
SELECT date_trunc('month', trade_date)::date AS month,
       MIN(close_price) AS min_close,
       MAX(close_price) AS max_close,
       AVG(close_price) AS mean_close
FROM daily_stock_metrics
WHERE ticker = $1 AND trade_date >= $2 AND trade_date <= $3
  AND session_type = 'CLOSE'
GROUP BY 1
ORDER BY 1 ASC
"""

WINDOW_DAYS: dict[Window, int] = {Window.LAST_6M: 180, Window.LAST_1Y: 365}


class TimescaleRepository:
    """Async TimescaleDB access. All reads are window-bounded (Rule 3)."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.timescale_dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def init_schema(self) -> None:
        from upstox_service.adapters.repositories.timescale.migrations import apply_migration
        pool = await self.connect()
        async with pool.acquire() as conn:
            await apply_migration(conn,"001_numeric",DDL_SCHEMA)

    @staticmethod
    def window_dates(window: Window, today: date | None = None) -> tuple[date, date]:
        """Resolve a window to [start, end] dates for SQL range queries."""
        from datetime import timedelta

        end = today or date.today()
        return end - timedelta(days=WINDOW_DAYS[window] - 1), end

    async def get_daily_range(
        self, ticker: str, start: date, end: date, session_type: str | None = None
    ) -> list[asyncpg.Record]:
        pool = await self.connect()
        async with pool.acquire() as conn:
            if session_type is not None:
                return await conn.fetch(
                    """
                    SELECT trade_date, session_type, open_price, high_price, low_price, close_price,
                           volume, delivery_qty, delivery_pct, delivery_20d_zscore,
                           delivery_vendor_id, delivery_vendor_as_of,
                           pe_ratio, pb_ratio, ev_ebitda, pe_5yr_percentile,
                           vendor_id, vendor_as_of
                    FROM daily_stock_metrics
                    WHERE ticker = $1 AND trade_date >= $2 AND trade_date <= $3
                      AND session_type = $4
                    ORDER BY trade_date ASC
                    """,
                    ticker,
                    start,
                    end,
                    session_type,
                )
            return await conn.fetch(RANGE_QUERY, ticker, start, end)

    async def get_anomalies(
        self, ticker: str, start: date, end: date, threshold: float = 1.8
    ) -> list[asyncpg.Record]:
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.fetch(ANOMALIES_QUERY, ticker, start, end, threshold)

    async def get_monthly_aggregates(self, ticker: str, window: Window) -> list[asyncpg.Record]:
        start, end = self.window_dates(window)
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.fetch(MONTHLY_AGGREGATES_QUERY, ticker, start, end)

    async def missing_checkpoint_dates(
        self, ticker: str, session: str, start: date, end: date
    ) -> list[date]:
        pool = await self.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT d::date AS trade_date FROM generate_series($3::date,$4::date,interval '1 day') d "
                "WHERE extract(isodow FROM d)<6 AND NOT EXISTS(SELECT 1 FROM daily_stock_metrics m "
                "WHERE m.ticker=$1 AND m.session_type=$2 AND m.trade_date=d::date) ORDER BY d",
                ticker,
                session,
                start,
                end,
            )
        return [row["trade_date"] for row in rows]

    async def get_watermark(self, vendor_id: str, ticker: str, series: str) -> date | None:
        """Last trade_date pushed for a vendor series (Rule 7 backfill)."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT last_trade_date FROM vendor_sync_state "
                "WHERE vendor_id = $1 AND ticker = $2 AND series = $3",
                vendor_id,
                ticker,
                series,
            )

    async def advance_watermark(
        self, vendor_id: str, ticker: str, series: str, last_date: date
    ) -> None:
        """Advance the watermark after inserting rows with trade_date > old mark."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vendor_sync_state "
                "(vendor_id, ticker, series, last_trade_date, last_fetched_at) "
                "VALUES ($1, $2, $3, $4, now()) "
                "ON CONFLICT (vendor_id, ticker, series) DO UPDATE SET "
                "last_trade_date = GREATEST(vendor_sync_state.last_trade_date, EXCLUDED.last_trade_date), "
                "last_fetched_at = now()",
                vendor_id,
                ticker,
                series,
                last_date,
            )

    async def stage_vendor_quote(
        self,
        vendor_id: str,
        ticker: str,
        trade_date: date,
        series: str,
        payload: dict[str, Any],
        fetched_at: datetime | None = None,
    ) -> None:
        """Stage raw payload as an immutable vintage in vendor_quotes_raw (Rule 7)."""
        ts = fetched_at or datetime.now(UTC)
        payload_json = json.dumps(payload, default=str)
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vendor_quotes_raw "
                "(vendor_id, ticker, trade_date, series, payload, fetched_at) "
                "SELECT $1::varchar, $2::varchar, $3::date, $4::varchar, $5::jsonb, $6::timestamptz WHERE $5::jsonb IS DISTINCT FROM "
                "(SELECT payload FROM vendor_quotes_raw WHERE vendor_id=$1 AND ticker=$2 "
                "AND trade_date=$3 AND series=$4 ORDER BY fetched_at DESC LIMIT 1) "
                "ON CONFLICT (vendor_id, ticker, trade_date, series, fetched_at) DO NOTHING",
                vendor_id,
                ticker.upper(),
                trade_date,
                series,
                payload_json,
                ts,
            )

    async def get_latest_vintages(
        self, vendor_id: str, ticker: str, start: date, end: date
    ) -> list[asyncpg.Record]:
        """Fetch latest vintage per (vendor_id, ticker, trade_date, series) via DISTINCT ON."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.fetch(LATEST_VINTAGE_QUERY, vendor_id, ticker.upper(), start, end)

    async def upsert_daily_metrics(self, rows: list[dict[str, Any]]) -> int:
        """Upsert normalized daily metrics (OPEN + CLOSE session rows)."""
        if not rows:
            return 0
        pool = await self.connect()
        query = """
        INSERT INTO daily_stock_metrics (
            trade_date, session_type, ticker, open_price, high_price, low_price,
            close_price, volume, delivery_qty, delivery_pct, delivery_20d_avg,
            delivery_20d_zscore, pe_ratio, pb_ratio, ev_ebitda, pe_5yr_percentile,
            vendor_id, vendor_as_of, delivery_vendor_id, delivery_vendor_as_of
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
        )
        ON CONFLICT (trade_date, session_type, ticker) DO UPDATE SET
            open_price = COALESCE(EXCLUDED.open_price, daily_stock_metrics.open_price),
            high_price = COALESCE(EXCLUDED.high_price, daily_stock_metrics.high_price),
            low_price = COALESCE(EXCLUDED.low_price, daily_stock_metrics.low_price),
            close_price = EXCLUDED.close_price,
            volume = EXCLUDED.volume,
            delivery_qty = COALESCE(EXCLUDED.delivery_qty, daily_stock_metrics.delivery_qty),
            delivery_pct = COALESCE(EXCLUDED.delivery_pct, daily_stock_metrics.delivery_pct),
            delivery_20d_avg = COALESCE(EXCLUDED.delivery_20d_avg, daily_stock_metrics.delivery_20d_avg),
            delivery_20d_zscore = COALESCE(EXCLUDED.delivery_20d_zscore, daily_stock_metrics.delivery_20d_zscore),
            pe_ratio = COALESCE(EXCLUDED.pe_ratio, daily_stock_metrics.pe_ratio),
            pb_ratio = COALESCE(EXCLUDED.pb_ratio, daily_stock_metrics.pb_ratio),
            ev_ebitda = COALESCE(EXCLUDED.ev_ebitda, daily_stock_metrics.ev_ebitda),
            pe_5yr_percentile = COALESCE(EXCLUDED.pe_5yr_percentile, daily_stock_metrics.pe_5yr_percentile),
            vendor_id = EXCLUDED.vendor_id,
            vendor_as_of = EXCLUDED.vendor_as_of,
            delivery_vendor_id = COALESCE(EXCLUDED.delivery_vendor_id, daily_stock_metrics.delivery_vendor_id),
            delivery_vendor_as_of = COALESCE(EXCLUDED.delivery_vendor_as_of, daily_stock_metrics.delivery_vendor_as_of)
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    await conn.execute(
                        query,
                        r["trade_date"],
                        r.get("session_type", "CLOSE"),
                        r["ticker"].upper(),
                        r.get("open_price"),
                        r.get("high_price"),
                        r.get("low_price"),
                        r["close_price"],
                        r.get("volume", 0),
                        r.get("delivery_qty"),
                        r.get("delivery_pct"),
                        r.get("delivery_20d_avg"),
                        r.get("delivery_20d_zscore"),
                        r.get("pe_ratio"),
                        r.get("pb_ratio"),
                        r.get("ev_ebitda"),
                        r.get("pe_5yr_percentile"),
                        r["vendor_id"],
                        r["vendor_as_of"],
                        r.get("delivery_vendor_id"),
                        r.get("delivery_vendor_as_of"),
                    )
        return len(rows)

    async def upsert_macro_and_flows(self, rows: list[dict[str, Any]]) -> int:
        """Upsert daily macro indicators and FII/DII flow records."""
        if not rows:
            return 0
        pool = await self.connect()
        query = """
        INSERT INTO daily_macro_and_flows (
            trade_date, brent_crude_usd, hrc_steel_inr, coking_coal_usd,
            usd_inr, fii_net_cash_cr, dii_net_cash_cr, vendor_id, vendor_as_of
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (trade_date) DO UPDATE SET
            brent_crude_usd = COALESCE(EXCLUDED.brent_crude_usd, daily_macro_and_flows.brent_crude_usd),
            hrc_steel_inr = COALESCE(EXCLUDED.hrc_steel_inr, daily_macro_and_flows.hrc_steel_inr),
            coking_coal_usd = COALESCE(EXCLUDED.coking_coal_usd, daily_macro_and_flows.coking_coal_usd),
            usd_inr = COALESCE(EXCLUDED.usd_inr, daily_macro_and_flows.usd_inr),
            fii_net_cash_cr = COALESCE(EXCLUDED.fii_net_cash_cr, daily_macro_and_flows.fii_net_cash_cr),
            dii_net_cash_cr = COALESCE(EXCLUDED.dii_net_cash_cr, daily_macro_and_flows.dii_net_cash_cr),
            vendor_id = EXCLUDED.vendor_id,
            vendor_as_of = EXCLUDED.vendor_as_of
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    await conn.execute(
                        query,
                        r["trade_date"],
                        r.get("brent_crude_usd"),
                        r.get("hrc_steel_inr"),
                        r.get("coking_coal_usd"),
                        r.get("usd_inr"),
                        r.get("fii_net_cash_cr"),
                        r.get("dii_net_cash_cr"),
                        r["vendor_id"],
                        r["vendor_as_of"],
                    )
        return len(rows)

    async def append_macro_observations(self, rows: list[dict[str, Any]]) -> int:
        """Append official periodic macro vintages; never overwrite a release."""
        if not rows:
            return 0
        pool = await self.connect()
        inserted = 0
        query = """
        INSERT INTO macro_observations (
            macro_id, observation_date, published_at, valid_from_ts, value,
            unit, source_id, source_as_of, payload
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        ON CONFLICT (macro_id, observation_date, valid_from_ts) DO NOTHING
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in rows:
                    result = await conn.execute(
                        query,
                        row["macro_id"],
                        row["observation_date"],
                        row["published_at"],
                        row["valid_from_ts"],
                        row["value"],
                        row.get("unit"),
                        row.get("source_id", "OFFICIAL_RELEASE"),
                        row.get("source_as_of", row["published_at"]),
                        json.dumps(row.get("payload", {}), default=str),
                    )
                    inserted += int(result.split()[-1])
        return inserted

    async def insert_quarterly_financials(self, row: dict[str, Any]) -> bool:
        """Insert one immutable official-result vintage.

        A restatement uses a later valid_from_ts and is appended. Replaying an
        already-seen filing hits the primary key and is a no-op.
        """
        columns = (
            "ticker",
            "quarter_label",
            "published_date",
            "valid_from_ts",
            "revenue_cr",
            "rev_yoy_pct",
            "ebitda_cr",
            "ebitda_margin_pct",
            "pat_cr",
            "pat_yoy_pct",
            "debt_to_equity",
            "operating_cash_flow_cr",
            "free_cash_flow_cr",
            "order_book_cr",
            "promoter_holding_pct",
            "promoter_pledge_pct",
            "fii_holding_pct",
            "dii_holding_pct",
            "source_id",
            "source_as_of",
        )
        values = [row.get(column) for column in columns]
        values[0] = str(values[0]).upper()
        pool = await self.connect()
        placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
        query = (
            f"INSERT INTO quarterly_financials ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (ticker, quarter_label, valid_from_ts) DO NOTHING"
        )
        async with pool.acquire() as conn:
            result = await conn.execute(query, *values)
        return result.endswith("1")

    async def rotate_mf_holding(self, row: dict[str, Any]) -> bool:
        """Append an MF holding and close only its prior active state.

        The SQL interval mirrors the graph UPDATED_HOLDING relationship.  The
        caller must hold the periodic-MF Redis lock so a fund cannot acquire
        two active states for the same ticker in concurrent runs.
        """
        ticker = str(row["ticker"]).upper()
        amc_id = str(row["amc_id"])
        new_ts = int(row["valid_from_ts"])
        pool = await self.connect()
        insert_query = """
        INSERT INTO monthly_mf_holdings_raw (
            month, ticker, amc_id, amc_name, shares_held, stake_pct,
            delta_stake_pct, valid_from_ts, valid_to_ts
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 9999999999)
        ON CONFLICT (month, ticker, amc_id, valid_from_ts) DO NOTHING
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval(
                    "SELECT 1 FROM monthly_mf_holdings_raw "
                    "WHERE month = $1 AND ticker = $2 AND amc_id = $3 AND valid_from_ts = $4",
                    row["month"],
                    ticker,
                    amc_id,
                    new_ts,
                )
                if existing:
                    return False
                await conn.execute(
                    "UPDATE monthly_mf_holdings_raw SET valid_to_ts = $4 "
                    "WHERE ticker = $1 AND amc_id = $2 AND valid_to_ts = 9999999999 "
                    "AND valid_from_ts < $3",
                    ticker,
                    amc_id,
                    new_ts,
                    new_ts - 1,
                )
                await conn.execute(
                    insert_query,
                    row["month"],
                    ticker,
                    amc_id,
                    row["amc_name"],
                    row.get("shares_held"),
                    row.get("stake_pct"),
                    row.get("delta_stake_pct"),
                    new_ts,
                )
        return True

    async def upsert_institutional_deals(self, rows: list[dict[str, Any]]) -> int:
        """Upsert bulk, block, and insider deals."""
        if not rows:
            return 0
        pool = await self.connect()
        query = """
        INSERT INTO institutional_deals_raw (
            trade_date, ticker, actor_name, actor_category, deal_type, side, qty, value_cr
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (trade_date, ticker, actor_name, deal_type, side) DO UPDATE SET
            actor_category = EXCLUDED.actor_category,
            qty = EXCLUDED.qty,
            value_cr = EXCLUDED.value_cr
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    await conn.execute(
                        query,
                        r["trade_date"],
                        r["ticker"].upper(),
                        r["actor_name"],
                        r.get("actor_category", "OTHER"),
                        r["deal_type"],
                        r["side"],
                        r.get("qty"),
                        r.get("value_cr"),
                    )
        return len(rows)

    async def record_ingest_run(
        self,
        job_name: str,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Log an ops run to ingest_runs table (Rule 6)."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO ingest_runs (job_name, status, started_at, finished_at, error, details) "
                "VALUES ($1, $2, COALESCE($3, now()), $4, $5, $6::jsonb) RETURNING id",
                job_name,
                status,
                started_at,
                finished_at,
                error,
                json.dumps(details or {}),
            )
            return int(row["id"])

    async def update_ingest_run(
        self,
        run_id: int,
        status: str,
        finished_at: datetime | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Update an existing ingest_runs record with finished_at and final status."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ingest_runs SET status = $2, finished_at = COALESCE($3, now()), error = $4, "
                "details = COALESCE($5::jsonb, details) "
                "WHERE id = $1",
                run_id,
                status,
                finished_at,
                error,
                json.dumps(details) if details is not None else None,
            )

    # --- News provider raw staging + fetch watermark (Rule 7 pattern) -------

    async def stage_news_raw(
        self,
        provider_id: str,
        external_id: str,
        payload: dict[str, Any],
        published_at: datetime | None = None,
        source_url: str | None = None,
    ) -> None:
        """Stage one raw provider payload as an immutable vintage.

        The raw payload lands here BEFORE any graph write, so LLM routing
        and embedding can be replayed without re-spending metered API
        quota. A re-fetched or corrected article becomes a NEW vintage
        (fetched_at is part of the primary key), never an overwrite.
        """
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO news_raw "
                "(provider_id, external_id, published_at, source_url, payload, fetched_at) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, now()) "
                "ON CONFLICT (provider_id, external_id, fetched_at) DO NOTHING",
                provider_id,
                external_id,
                published_at,
                source_url,
                json.dumps(payload, default=str),
            )

    async def get_news_watermark(self, provider_id: str) -> datetime | None:
        """Last publication instant successfully fetched for a provider."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT last_published_at FROM news_fetch_state WHERE provider_id = $1",
                provider_id,
            )

    async def get_staged_news(
        self,
        provider_ids: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """The staged provider payloads, newest first.

        One row per (provider, article, fetch vintage): the same article
        fetched twice is two vintages, and a replay must see the LATEST
        payload per article - which is what `DISTINCT ON` selects.
        """
        pool = await self.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (provider_id, external_id)
                       provider_id, external_id, published_at, source_url,
                       payload, fetched_at
                FROM news_raw
                WHERE ($1::text[] IS NULL OR provider_id = ANY($1::text[]))
                  AND ($2::timestamptz IS NULL OR published_at >= $2)
                ORDER BY provider_id, external_id, fetched_at DESC
                """,
                provider_ids,
                since,
            )
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            payload = row["payload"]
            if isinstance(payload, (str, bytes)):
                try:
                    payload = json.loads(payload)
                except Exception:  # noqa: BLE001 - a broken payload is skipped, not fatal
                    continue
            out.append(
                {
                    "provider_id": row["provider_id"],
                    "external_id": row["external_id"],
                    "published_at": row["published_at"],
                    "source_url": row["source_url"],
                    "payload": payload,
                    "fetched_at": row["fetched_at"],
                }
            )
        return out

    async def advance_news_watermark(self, provider_id: str, published_at: datetime) -> None:
        """Advance the provider watermark. Only ever moves forward."""
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO news_fetch_state "
                "(provider_id, last_published_at, last_fetched_at) "
                "VALUES ($1, $2, now()) "
                "ON CONFLICT (provider_id) DO UPDATE SET "
                "last_published_at = GREATEST("
                "    news_fetch_state.last_published_at, EXCLUDED.last_published_at), "
                "last_fetched_at = now()",
                provider_id,
                published_at,
            )
