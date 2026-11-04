"""SQL is the source of truth. Every projection event commits with its data."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

import yaml

from upstox_service.adapters.repositories.timescale.numeric import TimescaleRepository
from upstox_service.application.financial_context import normalize_statements
from upstox_service.domain.models import CompanyBundle, EntityKind, StockRegistration, event

ADMIN_CATALOG_FIELDS = {
    "Stock": {
        "name", "short_name", "business_summary", "sector", "aliases",
        "revenue_segments", "raw_material_inputs", "geographic_exposure",
        "strengths", "business_exclusions", "latest_quarter_summary",
        "latest_guidance_highlights", "prospectus_links",
    },
    "Commodity": {"name", "description", "aliases", "unit", "related_ids", "related_rationale", "exposures"},
    "MacroFactor": {"name", "description", "aliases", "why_it_moves", "equity_transmission", "default_scope"},
    "Sector": {"name", "description", "aliases"},
}
ADMIN_STRING_FIELDS = {
    "Stock": {"name", "short_name", "business_summary", "sector"},
    "Commodity": {"name", "description", "unit", "related_rationale"},
    "MacroFactor": {"name", "description", "why_it_moves", "equity_transmission", "default_scope"},
    "Sector": {"name", "description"},
}
ADMIN_LIST_FIELDS = {
    "Stock": {
        "aliases", "revenue_segments", "raw_material_inputs", "geographic_exposure",
        "strengths", "business_exclusions", "prospectus_links",
    },
    "Commodity": {"aliases", "related_ids", "exposures"},
    "MacroFactor": {"aliases"},
    "Sector": {"aliases"},
}

CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS entity_catalog (
 kind text NOT NULL CHECK (kind IN ('Stock','Commodity','MacroFactor','Sector')),
 entity_id text NOT NULL, revision bigint NOT NULL, content_hash text NOT NULL,
 payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(kind,entity_id));
CREATE TABLE IF NOT EXISTS entity_catalog_versions (
 kind text NOT NULL, entity_id text NOT NULL, revision bigint NOT NULL,
 payload jsonb NOT NULL, valid_from timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(kind,entity_id,revision));
CREATE TABLE IF NOT EXISTS registration_jobs (
 job_id uuid PRIMARY KEY, request jsonb NOT NULL, state text NOT NULL DEFAULT 'pending',
 ticker text, attempts int NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, error text, warnings jsonb NOT NULL DEFAULT '[]',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS graph_outbox (
 event_id uuid PRIMARY KEY, event jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz, attempts int NOT NULL DEFAULT 0, error text,
 sequence_id bigserial NOT NULL);
ALTER TABLE graph_outbox ADD COLUMN IF NOT EXISTS sequence_id bigserial;
CREATE INDEX IF NOT EXISTS graph_outbox_unpublished ON graph_outbox(created_at) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS stock_fundamentals_raw (
 ticker text NOT NULL, series text NOT NULL, payload jsonb NOT NULL,
 vendor_id text NOT NULL, vendor_as_of timestamptz NOT NULL,
 PRIMARY KEY(ticker,series,vendor_as_of));
CREATE TABLE IF NOT EXISTS pending_news_reviews (
 provider_id text NOT NULL, external_id text NOT NULL, payload jsonb NOT NULL,
 published_at timestamptz, source_url text, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(provider_id, external_id));
CREATE TABLE IF NOT EXISTS normalized_news (
 provider_id text NOT NULL, external_id text NOT NULL, revision bigint NOT NULL,
 content_hash text NOT NULL, article jsonb NOT NULL, committed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(provider_id,external_id));
"""


def json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def merge_company_profile(existing: dict, incoming: dict) -> dict:
    """A provider refresh enriches knowledge; an absent value is not a deletion.

    Operator annotations and curated business context survive providers that do
    not supply those fields. Non-empty operator additions replace the prior
    annotation; identities, description and provenance use fresh non-null data.
    """
    merged = deepcopy(existing)
    merged.update(deepcopy({key: value for key, value in incoming.items() if value is not None}))
    for field in (
        "sector",
        "exposures",
        "revenue_segments",
        "raw_material_inputs",
        "geographic_exposure",
        "prospectus_links",
        "strengths",
        "business_exclusions",
    ):
        value = incoming.get(field)
        if (not value or (isinstance(value, str) and not value.strip())) and field in existing:
            merged[field] = deepcopy(existing[field])
    merged["aliases"] = list(
        dict.fromkeys([*(existing.get("aliases") or []), *(incoming.get("aliases") or [])])
    )
    return merged


class DataRepository(TimescaleRepository):
    async def init_schema(self) -> None:
        from upstox_service.adapters.repositories.timescale.migrations import migrate_data_store
        pool = await self.connect()
        async with pool.acquire() as conn:
            await migrate_data_store(conn)

    async def bootstrap(self, seed: dict | None = None) -> int:
        if seed is None:
            seed = yaml.safe_load(
                files("upstox_service.resources")
                .joinpath("ontology_seed.yaml")
                .read_text(encoding="utf-8")
            )
        pool = await self.connect()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(726782301)")
            if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM entity_catalog)"):
                return 0
            count = 0
            # Register non-stock entities first so consumers already have the catalog.
            for section, kind in [
                ("commodities", "Commodity"),
                ("macro_factors", "MacroFactor"),
                ("sectors", "Sector"),
                ("stocks", "Stock"),
            ]:
                for original in seed.get(section, []):
                    entity = dict(original)
                    entity.pop("macro_exposures", None)
                    entity.pop("default_scope", None)
                    await self._put_entity(conn, kind, entity)
                    count += 1
            return count

    async def _enqueue(self, conn: Any, message: dict) -> None:
        await conn.execute(
            "INSERT INTO graph_outbox(event_id,event) VALUES($1,$2::jsonb)",
            UUID(message["event_id"]),
            json.dumps(message, default=str),
        )

    async def _put_entity(
        self, conn: Any, kind: str, entity: dict, job_id: str | None = None
    ) -> tuple[int, bool]:
        entity_id = entity["ticker"] if kind == "Stock" else entity["id"]
        # Serialize concurrent changes to the same canonical entity, including first insertion.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"{kind}:{entity_id}"
        )
        old = await conn.fetchrow(
            "SELECT * FROM entity_catalog WHERE kind=$1 AND entity_id=$2 FOR UPDATE",
            kind,
            entity_id,
        )
        digest = canonical_hash(entity)
        if old and old["content_hash"] == digest:
            if job_id:
                # Re-registration still requests graph refresh/backfill and needs completion status.
                await self._enqueue(
                    conn,
                    event(
                        "registry.updated",
                        entity_id,
                        old["revision"],
                        {"kind": kind, "entity": entity},
                        job_id,
                    ),
                )
            return old["revision"], False
        revision = (old["revision"] if old else 0) + 1
        encoded = json.dumps(entity, default=str)
        await conn.execute(
            "INSERT INTO entity_catalog(kind,entity_id,revision,content_hash,payload) VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(kind,entity_id) DO UPDATE SET revision=EXCLUDED.revision,content_hash=EXCLUDED.content_hash,payload=EXCLUDED.payload,updated_at=now()",
            kind,
            entity_id,
            revision,
            digest,
            encoded,
        )
        await conn.execute(
            "INSERT INTO entity_catalog_versions(kind,entity_id,revision,payload) VALUES($1,$2,$3,$4::jsonb)",
            kind,
            entity_id,
            revision,
            encoded,
        )
        await self._enqueue(
            conn,
            event(
                "registry.updated", entity_id, revision, {"kind": kind, "entity": entity}, job_id
            ),
        )
        return revision, True

    async def upsert_entity(self, kind: EntityKind, entity: dict) -> dict:
        pool = await self.connect()
        async with pool.acquire() as conn, conn.transaction():
            revision, changed = await self._put_entity(conn, kind.value, entity)
        return {
            "entity_id": entity.get("id", entity.get("ticker")),
            "revision": revision,
            "changed": changed,
            "state": "graph_processing" if changed else "unchanged",
        }

    async def update_catalog_entity(self, kind: EntityKind, entity_id: str, changes: dict) -> dict:
        """Update descriptive catalog fields and publish a versioned graph event."""
        name = kind.value
        allowed = ADMIN_CATALOG_FIELDS[name]
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Fields cannot be edited for {name}: {', '.join(sorted(invalid))}")
        for field, value in changes.items():
            if field in ADMIN_STRING_FIELDS[name]:
                if field == "default_scope":
                    if value not in ("BROAD", "SELECTIVE"):
                        raise ValueError("default_scope must be BROAD or SELECTIVE")
                elif value is not None and (not isinstance(value, str) or len(value) > 20000):
                    raise ValueError(f"{field} must be a string of at most 20000 characters")
                if field == "name" and (not isinstance(value, str) or not value.strip()):
                    raise ValueError("name cannot be empty or null")
                if field == "description" and value is not None and not value.strip():
                    raise ValueError(f"{field} cannot be empty")
            elif field in ADMIN_LIST_FIELDS[name]:
                if not isinstance(value, list) or len(value) > 200:
                    raise ValueError(f"{field} must be a list with at most 200 entries")
                if field == "prospectus_links":
                    for item in value:
                        if not isinstance(item, dict) or set(item) != {"document_type", "url"}:
                            raise ValueError("prospectus_links entries require document_type and url")
                        document_type, url = item["document_type"], item["url"]
                        if (not isinstance(document_type, str) or document_type not in {"DRHP", "RHP"}
                                or not isinstance(url, str) or len(url) > 2048):
                            raise ValueError("prospectus_links entries require a valid type and URL")
                elif any(not isinstance(item, str) or len(item) > 2000 for item in value):
                    raise ValueError(f"{field} entries must be strings of at most 2000 characters")
            elif field in {"latest_quarter_summary", "latest_guidance_highlights"}:
                if value is not None and not isinstance(value, (str, dict)):
                    raise ValueError(f"{field} must be text, an object, or null")
        if name == "Stock":
            entity_id = entity_id.strip().upper()
        pool = await self.connect()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"{name}:{entity_id}"
            )
            row = await conn.fetchrow(
                "SELECT payload FROM entity_catalog WHERE kind=$1 AND entity_id=$2 FOR UPDATE",
                name,
                entity_id,
            )
            if row is None:
                raise KeyError(f"Unknown {name} entity: {entity_id}")
            entity = json_value(row["payload"])
            targets = changes.get("exposures", changes.get("related_ids", []))
            if targets:
                registered = await conn.fetch(
                    "SELECT entity_id FROM entity_catalog WHERE kind='Commodity' AND entity_id=ANY($1::text[])",
                    targets,
                )
                known = {item["entity_id"] for item in registered}
                missing = sorted(set(targets) - known)
                if missing:
                    raise ValueError("Unknown canonical commodity ID(s): " + ", ".join(missing))
            entity.update(changes)
            revision, changed = await self._put_entity(conn, name, entity)
        return {
            "entity_id": entity_id,
            "kind": name,
            "revision": revision,
            "changed": changed,
            "state": "graph_processing" if changed else "unchanged",
        }

    async def list_catalog(self, kind: str | None = None) -> list[dict]:
        pool = await self.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT kind,entity_id,revision,payload FROM entity_catalog WHERE ($1::text IS NULL OR kind=$1) ORDER BY kind,entity_id",
                kind,
            )
        return [{**dict(row), "payload": json_value(row["payload"])} for row in rows]

    async def get_entity(self, kind: str, entity_id: str) -> dict | None:
        pool = await self.connect()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM entity_catalog WHERE kind=$1 AND entity_id=$2", kind, entity_id
            )
        return json_value(row["payload"]) if row else None

    async def create_job(self, request: StockRegistration) -> dict:
        job_id = uuid4()
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO registration_jobs(job_id,request) VALUES($1,$2::jsonb)",
                job_id,
                request.model_dump_json(),
            )
        return {"job_id": str(job_id), "state": "pending"}

    async def get_job(self, job_id: str) -> dict | None:
        pool = await self.connect()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT job_id,state,ticker,attempts,error,warnings,created_at,updated_at FROM registration_jobs WHERE job_id=$1",
                UUID(job_id),
            )
        if not row:
            return None
        return {**dict(row), "job_id": str(row["job_id"]), "warnings": json_value(row["warnings"])}

    async def claim_job(self, lease_seconds: int, max_attempts: int) -> dict | None:
        pool = await self.connect()
        async with pool.acquire() as conn, conn.transaction():
            # A crashed final attempt must become visibly failed, not remain running forever.
            await conn.execute(
                "UPDATE registration_jobs SET state='failed',error='Worker lease expired after final attempt',updated_at=now() WHERE state='data_collection' AND lease_until<now() AND attempts >= $1",
                max_attempts,
            )
            row = await conn.fetchrow(
                "SELECT * FROM registration_jobs WHERE attempts<$1 AND next_attempt_at<=now() AND (state='pending' OR (state='data_collection' AND lease_until<now())) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1",
                max_attempts,
            )
            if not row:
                return None
            await conn.execute(
                "UPDATE registration_jobs SET state='data_collection',attempts=attempts+1,lease_until=now()+$2*interval '1 second',updated_at=now() WHERE job_id=$1",
                row["job_id"],
                lease_seconds,
            )
        return {
            **dict(row),
            "job_id": str(row["job_id"]),
            "request": json_value(row["request"]),
            "attempts": row["attempts"] + 1,
        }

    async def renew_job(self, job_id: str, attempt: int, lease_seconds: int) -> bool:
        pool = await self.connect()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE registration_jobs SET lease_until=clock_timestamp()+$3*interval '1 second',updated_at=clock_timestamp() WHERE job_id=$1 AND attempts=$2 AND state='data_collection' AND lease_until>clock_timestamp()",
                UUID(job_id),
                attempt,
                lease_seconds,
            )
        return result == "UPDATE 1"

    async def fail_job(
        self, job_id: str, error: str, retry: bool, *, attempt: int | None = None
    ) -> None:
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE registration_jobs SET state=$2,error=$3,lease_until=NULL,next_attempt_at=now()+interval '30 seconds',updated_at=now() WHERE job_id=$1 AND ($4::int IS NULL OR (attempts=$4 AND state='data_collection' AND lease_until>clock_timestamp()))",
                UUID(job_id),
                "pending" if retry else "failed",
                error[:1000],
                attempt,
            )

    async def commit_company(
        self, job_id: str, bundle: CompanyBundle, *, attempt: int | None = None
    ) -> None:
        entity = dict(bundle.entity)
        ticker = entity["ticker"]
        now = datetime.now(UTC)
        pool = await self.connect()
        async with pool.acquire() as conn, conn.transaction():
            job = await conn.fetchrow(
                "SELECT state,attempts,lease_until>clock_timestamp() AS lease_valid FROM registration_jobs WHERE job_id=$1 FOR UPDATE",
                UUID(job_id),
            )
            if (
                not job
                or job["state"] != "data_collection"
                or not job["lease_valid"]
                or (attempt is not None and job["attempts"] != attempt)
            ):
                raise RuntimeError("Registration worker lost its lease; stale commit rejected")
            # Use the same per-entity lock as all catalog writers. Read/merge and
            # the eventual revision/outbox write must see one consistent profile.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                f"Stock:{ticker}",
            )
            existing = await conn.fetchval(
                "SELECT payload FROM entity_catalog WHERE kind='Stock' AND entity_id=$1 FOR UPDATE",
                ticker,
            )
            if existing is not None:
                entity = merge_company_profile(json_value(existing), entity)
            for series, payload in {"company_profile": bundle.raw, **bundle.statements}.items():
                await conn.execute(
                    "INSERT INTO stock_fundamentals_raw(ticker,series,payload,vendor_id,vendor_as_of) VALUES($1,$2,$3::jsonb,'UPSTOX',$4) ON CONFLICT DO NOTHING",
                    ticker,
                    series,
                    json.dumps(payload, default=str),
                    now,
                )
            for normalized in normalize_statements(ticker, bundle.statements, "UPSTOX", now):
                columns = tuple(normalized)
                placeholders = ",".join(f"${index}" for index in range(1, len(columns) + 1))
                await conn.execute(
                    f"INSERT INTO quarterly_financials ({','.join(columns)}) VALUES ({placeholders}) "
                    "ON CONFLICT(ticker,quarter_label,valid_from_ts) DO NOTHING",
                    *(normalized[column] for column in columns),
                )
            if bundle.checkpoint:
                p = bundle.checkpoint
                await conn.execute(
                    "INSERT INTO vendor_quotes_raw(vendor_id,ticker,trade_date,series,payload,fetched_at) VALUES('UPSTOX',$1,$2,$3,$4::jsonb,$5) ON CONFLICT DO NOTHING",
                    ticker,
                    p["trade_date"],
                    p["session_type"],
                    json.dumps(bundle.raw.get("historical_close", p), default=str),
                    now,
                )
                await conn.execute(
                    "INSERT INTO daily_stock_metrics(trade_date,session_type,ticker,open_price,high_price,low_price,close_price,volume,vendor_id,vendor_as_of) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'UPSTOX',$9) ON CONFLICT(trade_date,session_type,ticker) DO UPDATE SET open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,volume=EXCLUDED.volume,vendor_id=EXCLUDED.vendor_id,vendor_as_of=EXCLUDED.vendor_as_of",
                    p["trade_date"],
                    p["session_type"],
                    ticker,
                    p.get("open_price"),
                    p.get("high_price"),
                    p.get("low_price"),
                    p["close_price"],
                    p.get("volume", 0),
                    now,
                )
            await self._put_entity(conn, "Stock", entity, job_id)
            await conn.execute(
                "UPDATE registration_jobs SET state='graph_processing',ticker=$2,error=NULL,lease_until=NULL,warnings=$3::jsonb,updated_at=now() WHERE job_id=$1",
                UUID(job_id),
                ticker,
                json.dumps(bundle.warnings),
            )

    async def commit_news(self, result: Any) -> int:
        """Approved raw pairs, normalized news, watermark, and outbox share one transaction."""
        pool = await self.connect()
        count = 0
        async with pool.acquire() as conn, conn.transaction():
            for raw in result.staged:
                await conn.execute(
                    "INSERT INTO news_raw(provider_id,external_id,published_at,source_url,payload,fetched_at) VALUES($1,$2,$3,$4,$5::jsonb,now()) ON CONFLICT DO NOTHING",
                    result.provider_id,
                    raw.external_id,
                    raw.published_at,
                    raw.source_url,
                    json.dumps(raw.payload, default=str),
                )
                if raw.external_id not in result.approvals:
                    await conn.execute(
                        "INSERT INTO pending_news_reviews(provider_id,external_id,payload,published_at,source_url) "
                        "VALUES($1,$2,$3::jsonb,$4,$5) ON CONFLICT(provider_id,external_id) "
                        "DO UPDATE SET payload=EXCLUDED.payload,published_at=EXCLUDED.published_at,"
                        "source_url=EXCLUDED.source_url,updated_at=now()",
                        result.provider_id,
                        raw.external_id,
                        json.dumps(raw.payload, default=str),
                        raw.published_at,
                        raw.source_url,
                    )
            for article in result.articles:
                approval = result.approvals.get(article.external_id)
                if approval is None:
                    raise ValueError("Refusing to persist news without an eligibility approval")
                approval_source, approval_reason = approval
                payload = {
                    "external_id": article.external_id,
                    "headline": article.headline,
                    "summary": article.summary,
                    "source_url": article.source_url,
                    "source": article.source,
                    "published_at": article.published_at.isoformat(),
                    "category": article.category.value,
                    "sentiment": article.sentiment,
                    "tickers": list(article.tickers),
                    "ticker_sentiment": dict(article.ticker_sentiment),
                    "eligibility": {
                        "version": 1,
                        "decision": "APPROVED",
                        "source": approval_source,
                        "reason": approval_reason,
                    },
                }
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    f"news:{result.provider_id}:{article.external_id}",
                )
                old = await conn.fetchrow(
                    "SELECT revision,content_hash FROM normalized_news WHERE provider_id=$1 AND external_id=$2",
                    result.provider_id,
                    article.external_id,
                )
                digest = canonical_hash(payload)
                if old and old["content_hash"] == digest:
                    continue
                revision = (old["revision"] if old else 0) + 1
                await conn.execute(
                    "INSERT INTO normalized_news(provider_id,external_id,revision,content_hash,article) VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(provider_id,external_id) DO UPDATE SET revision=EXCLUDED.revision,content_hash=EXCLUDED.content_hash,article=EXCLUDED.article,committed_at=now()",
                    result.provider_id,
                    article.external_id,
                    revision,
                    digest,
                    json.dumps(payload),
                )
                await self._enqueue(
                    conn,
                    event(
                        "news.received",
                        f"{result.provider_id}:{article.external_id}",
                        revision,
                        payload,
                    ),
                )
                count += 1
            if result.watermark_at is not None:
                await conn.execute(
                    "INSERT INTO news_fetch_state(provider_id,last_published_at,last_fetched_at) VALUES($1,$2,now()) ON CONFLICT(provider_id) DO UPDATE SET last_published_at=GREATEST(news_fetch_state.last_published_at,EXCLUDED.last_published_at),last_fetched_at=now()",
                    result.provider_id,
                    result.watermark_at,
                )
        return count

    async def pending_news_reviews(self, limit: int = 100) -> list[dict]:
        pool = await self.connect()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT provider_id,external_id,payload FROM pending_news_reviews ORDER BY updated_at LIMIT $1",
                limit,
            )
        return [{**dict(row), "payload": json_value(row["payload"])} for row in rows]

    async def defer_news_review(self, provider_id: str, external_id: str) -> None:
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE pending_news_reviews SET updated_at=now() WHERE provider_id=$1 AND external_id=$2",
                provider_id,
                external_id,
            )

    async def finish_news_review(self, provider_id: str, external_id: str) -> None:
        pool = await self.connect()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM pending_news_reviews WHERE provider_id=$1 AND external_id=$2",
                provider_id,
                external_id,
            )

    async def publish_outbox(self, publisher: Any, limit: int = 100) -> int:
        """Mark after XADD. Crash after XADD causes safe redelivery, never lost events."""
        pool = await self.connect()
        count = 0
        async with pool.acquire() as conn, conn.transaction():
            # One publisher holds a transaction-scoped lock so multiple workers cannot
            # reorder catalog-before-stock events or revisions across batches.
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock(726782302)"):
                return 0
            rows = await conn.fetch(
                "SELECT event_id,event FROM graph_outbox WHERE published_at IS NULL ORDER BY sequence_id FOR UPDATE SKIP LOCKED LIMIT $1",
                limit,
            )
            for row in rows:
                try:
                    await publisher.publish(json_value(row["event"]))
                except Exception:
                    await conn.execute(
                        "UPDATE graph_outbox SET attempts=attempts+1,error='Redis publication failed' WHERE event_id=$1",
                        row["event_id"],
                    )
                    break
                await conn.execute(
                    "UPDATE graph_outbox SET published_at=now(),attempts=attempts+1,error=NULL WHERE event_id=$1",
                    row["event_id"],
                )
                count += 1
        return count

    async def get_financials(self, ticker: str, window: Any) -> dict:
        from zoneinfo import ZoneInfo

        start, end = self.window_dates(window, datetime.now(ZoneInfo("Asia/Kolkata")).date())
        rows = await self.get_daily_range(ticker, start, end)
        pool = await self.connect()
        async with pool.acquire() as conn:
            statements = await conn.fetch(
                "SELECT DISTINCT ON (series) series,payload,vendor_id,vendor_as_of FROM stock_fundamentals_raw WHERE ticker=$1 ORDER BY series,vendor_as_of DESC",
                ticker,
            )
            quarterly = await conn.fetch(
                "SELECT DISTINCT ON (quarter_label) * FROM quarterly_financials "
                "WHERE ticker=$1 AND published_date BETWEEN $2 AND $3 "
                "AND valid_from_ts<=$4 ORDER BY quarter_label,valid_from_ts DESC",
                ticker,
                start,
                end,
                int(datetime.now(UTC).timestamp()),
            )
        return {
            "ticker": ticker,
            "window": window.value,
            "quarterly_financials": [dict(row) for row in quarterly],
            "start_date": start,
            "end_date": end,
            "daily_metrics": [dict(row) for row in rows],
            "statements": [
                {**dict(row), "payload": json_value(row["payload"])} for row in statements
            ],
        }
