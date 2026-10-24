"""Source-owned immutable originals, citations, and a transactional evidence outbox."""

import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

DOCUMENT_DDL = """
CREATE TABLE IF NOT EXISTS source_documents (
 document_id uuid PRIMARY KEY, ticker text NOT NULL, source_url text NOT NULL, revision bigint NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS source_document_versions (
 version_id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES source_documents(document_id),
 content_hash text NOT NULL, title text NOT NULL, media_type text NOT NULL,
 document_kind text NOT NULL, pages jsonb NOT NULL, chunks jsonb NOT NULL, revision bigint NOT NULL DEFAULT 1,
 received_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(document_id,content_hash));
CREATE INDEX IF NOT EXISTS source_documents_ticker ON source_documents(ticker);
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 0;
ALTER TABLE source_document_versions ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS document_outbox (
 event_id uuid PRIMARY KEY, event jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz);
"""


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


class DocumentRepository:
    def __init__(self, data_repository):
        self.data = data_repository

    async def init_schema(self):
        from upstox_service.adapters.repositories.timescale.migrations import apply_migration
        pool = await self.data.connect()
        async with pool.acquire() as conn:
            await apply_migration(conn,"004_documents",DOCUMENT_DDL)

    async def save(self, request, extracted):
        document_id = uuid5(NAMESPACE_URL, f"{request.ticker}|{request.source_url}")
        version_id = uuid5(document_id, extracted.content_hash)
        chunks = [{**c, "id": f"{version_id}:{c['ordinal']}"} for c in extracted.chunks]
        pool = await self.data.connect()
        async with pool.acquire() as conn, conn.transaction():
            # Source documents cannot invent a stock identity.
            exists = await conn.fetchval(
                "SELECT 1 FROM entity_catalog WHERE kind='Stock' AND entity_id=$1", request.ticker
            )
            if not exists:
                raise KeyError("Unknown registered stock")
            await conn.execute("INSERT INTO source_documents(document_id,ticker,source_url) "
                               "VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                               document_id, request.ticker, request.source_url)
            current_revision = await conn.fetchval(
                "SELECT revision FROM source_documents WHERE document_id=$1 FOR UPDATE", document_id
            )
            revision = current_revision + 1
            now = datetime.now(UTC)
            inserted = await conn.fetchval(
                "INSERT INTO source_document_versions(version_id,document_id,content_hash,title,media_type,"
                "document_kind,pages,chunks,revision,received_at) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10) "
                "ON CONFLICT DO NOTHING RETURNING version_id", version_id, document_id,
                extracted.content_hash, request.title, request.media_type, request.document_kind,
                json.dumps(extracted.pages), json.dumps(chunks), revision, now,
            )
            if inserted:
                await conn.execute("UPDATE source_documents SET revision=$2 WHERE document_id=$1",
                                   document_id, revision)
                event_id = uuid4()
                event = {"schema_version": 1, "event_id": str(event_id), "kind": "document.extracted",
                         "entity_id": str(document_id), "revision": revision, "occurred_at": now.isoformat(),
                         "payload": {"ticker": request.ticker, "document_id": str(document_id),
                                     "version_id": str(version_id), "content_hash": extracted.content_hash,
                                     "title": request.title, "source_url": request.source_url,
                                     "document_kind": request.document_kind, "chunks": chunks}}
                await conn.execute("INSERT INTO document_outbox(event_id,event) VALUES($1,$2::jsonb)",
                                   event_id, json.dumps(event))
            stored = await conn.fetchrow(
                "SELECT received_at,revision FROM source_document_versions WHERE version_id=$1", version_id
            )
        return {"document_id": str(document_id), "version_id": str(version_id),
                "content_hash": extracted.content_hash, "page_count": len(extracted.pages),
                "chunk_count": len(chunks), "received_at": stored["received_at"],
                "revision": stored["revision"], "processing_status": "graph_pending", "duplicate": not bool(inserted)}

    async def get(self, version_id):
        pool = await self.data.connect()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT v.*,d.ticker,d.source_url FROM source_document_versions v "
                "JOIN source_documents d USING(document_id) WHERE version_id=$1", UUID(str(version_id))
            )
        if not row:
            return None
        result = dict(row)
        for field in ("pages", "chunks"):
            result[field] = decoded(result[field])
        return result

    async def publish_outbox(self, redis_client, stream="stockgraph:platform-events:v1", limit=20):
        pool = await self.data.connect()
        published = 0
        async with pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "SELECT event_id,event FROM document_outbox WHERE published_at IS NULL "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT $1", limit
            )
            for row in rows:
                await redis_client.xadd(stream, {"event": json.dumps(decoded(row["event"]))})
                await conn.execute("UPDATE document_outbox SET published_at=now() WHERE event_id=$1",
                                   row["event_id"])
                published += 1
        return published
