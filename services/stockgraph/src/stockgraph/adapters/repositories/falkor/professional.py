"""Replay-safe professional evidence and versioned source-document projections."""

import json
from zoneinfo import ZoneInfo

from stockgraph.adapters.repositories.falkor.repository import first, public_props
from stockgraph.runtime.settings import settings


class EvidenceRepository:
    def __init__(self, graph):
        self.graph = graph

    def ensure_indexes(self):
        for label in ("Contribution", "ProfessionalEvidence", "ProfessionalAuthor", "DocumentRecord", "DocumentVersion", "DocumentChunk"):
            try:
                self.graph._run(f"CREATE INDEX FOR (n:{label}) ON (n.id)", {})
            except Exception as exc:
                if "already" not in str(exc).lower():
                    raise
        dimension = settings.embedding_dimension
        try:
            self.graph._run(
                "CREATE VECTOR INDEX FOR (c:DocumentChunk) ON (c.embedding) "
                f"OPTIONS {{dimension: {dimension}, similarityFunction: 'cosine'}}", {},
            )
        except Exception as exc:
            if "already" not in str(exc).lower():
                raise

    def project_author_status(self, event):
        author = str(event.payload.get("author_id", ""))
        verified = event.payload.get("verified")
        if author != event.entity_id or not isinstance(verified, bool):
            raise ValueError("Invalid professional author status")
        self.graph._run(
            "MERGE (a:ProfessionalAuthor {id:$id}) ON CREATE SET a.revision=0 "
            "WITH a WHERE a.revision<$revision SET a.revision=$revision,a.verified=$verified RETURN a.id",
            {"id": author, "revision": event.revision, "verified": verified},
        )
        return True

    def project_professional(self, event, payload=None):
        """Finish multi-statement projection before advancing the revision cursor.

        All writers share the renewable graph lock. Every statement is idempotent;
        a crash before the final cursor update replays and finishes the projection.
        """
        rows = self.graph._run(
            "MATCH (c:Contribution {id:$id}) RETURN properties(c)", {"id": event.entity_id}
        )
        current = first(rows[0]) if rows else {}
        if int(current.get("revision", 0)) >= event.revision:
            return False
        ts = int(event.occurred_at.timestamp())
        if event.kind == "professional.retracted":
            self.graph._run(
                "MATCH (p:ProfessionalEvidence {contribution_id:$id}) WHERE p.is_latest=true "
                "SET p.is_latest=false,p.retracted=true,"
                "p.valid_to_ts=CASE WHEN p.valid_to_ts>$ts THEN $ts ELSE p.valid_to_ts END RETURN p.id",
                {"id": event.entity_id, "ts": ts - 1},
            )
            # Create a tombstone even when retraction arrives before publication.
            self.graph._run(
                "MERGE (c:Contribution {id:$id}) SET c.revision=$revision,c.retracted=true "
                "RETURN c.id", {"id": event.entity_id, "revision": event.revision},
            )
            return True
        p = payload
        if str(p.contribution_id) != event.entity_id:
            raise ValueError("Contribution identity mismatch")
        if not self.graph.get_entity("Stock", p.ticker):
            raise KeyError("Canonical stock projection is not available yet")
        version = str(p.version_id)
        published = int(p.published_at.timestamp())
        props = {
            "id": version, "contribution_id": event.entity_id, "revision": event.revision,
            "author_id": str(p.author_id), "author_name": p.author_name,
            "ticker": p.ticker, "title": p.title, "body": p.body,
            "direction": p.direction, "horizon": p.horizon,
            "disclosures": p.disclosures,
            "event_ts": int(p.event_at.timestamp()),
            "event_date": p.event_at.astimezone(ZoneInfo(settings.app_timezone)).date().isoformat(),
            "known_at_ts": int((p.known_at or event.occurred_at).timestamp()), "published_at_ts": published,
            "valid_from_ts": published, "valid_to_ts": int(p.expires_at.timestamp()),
            "expires_at_ts": int(p.expires_at.timestamp()), "is_latest": True,
            "retracted": False, "future_access": p.future_access,
            "evidence_json": json.dumps(p.evidence), "priority_policy": "professional-priority-v1",
        }
        if props["expires_at_ts"] <= published:
            raise ValueError("Evidence expires before publication")
        self.graph._run(
            "MATCH (old:ProfessionalEvidence {contribution_id:$id}) "
            "WHERE old.id<>$version AND old.is_latest=true "
            "SET old.is_latest=false,old.valid_to_ts="
            "CASE WHEN old.valid_to_ts>$closed THEN $closed ELSE old.valid_to_ts END RETURN old.id",
            {"id": event.entity_id, "version": version, "closed": published - 1},
        )
        self.graph._run(
            "MATCH (s:Stock {ticker:$ticker}) MERGE (p:ProfessionalEvidence {id:$version}) "
            "SET p += $props MERGE (p)-[:PROFESSIONAL_VIEW_ON]->(s) RETURN p.id",
            {"ticker": p.ticker, "version": version, "props": props},
        )
        self.graph._run(
            "MATCH (p:ProfessionalEvidence {id:$version}),"
            "(old:ProfessionalEvidence {contribution_id:$id}) "
            "WHERE old.revision<$revision AND old.id<>$version "
            "WITH p,old ORDER BY old.revision DESC LIMIT 1 "
            "MERGE (p)-[:SUPERSEDES]->(old) RETURN p.id",
            {"version": version, "id": event.entity_id, "revision": event.revision},
        )
        self.graph._run(
            "MERGE (c:Contribution {id:$id}) SET c.revision=$revision,c.retracted=false "
            "RETURN c.id", {"id": event.entity_id, "revision": event.revision},
        )
        return True

    def professional_page(self, ticker, start, end, offset=0, limit=50):
        limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
        rows = self.graph._run(
            "MATCH (p:ProfessionalEvidence)-[:PROFESSIONAL_VIEW_ON]->(s:Stock {ticker:$ticker}) "
            "WHERE p.is_latest=true AND p.retracted=false AND p.valid_from_ts<=$end "
            "AND p.valid_to_ts>=$end AND p.event_ts>=$start AND p.event_ts<=$end "
            "OPTIONAL MATCH (a:ProfessionalAuthor {id:p.author_id}) "
            "RETURN properties(p),a.verified ORDER BY p.published_at_ts DESC,p.id "
            f"SKIP {offset} LIMIT {limit + 1}", {"ticker": ticker, "start": start, "end": end},
        )
        result = []
        for row in rows:
            props = dict(first(row))
            values = list(row.values()) if isinstance(row, dict) else row
            props["author_verified"] = values[1] is not False if len(values) > 1 else True
            props["evidence"] = json.loads(props.pop("evidence_json", "[]"))
            result.append(props)
        return result

    def project_document(self, event):
        p = event.payload
        ticker, identity = p["ticker"], p["version_id"]
        if event.entity_id != p["document_id"]:
            raise ValueError("Document identity mismatch")
        if not self.graph.get_entity("Stock", ticker):
            raise KeyError("Canonical stock projection is not available yet")
        records = self.graph._run(
            "MATCH (d:DocumentRecord {id:$document}) RETURN properties(d)",
            {"document": p["document_id"]},
        )
        current = first(records[0]) if records else {}
        active = int(current.get("revision", 0)) <= event.revision
        if int(current.get("revision", 0)) == event.revision and current.get("version_id") != identity:
            raise ValueError("Conflicting document revision")
        props = {k: p[k] for k in ("title", "source_url", "document_id", "content_hash", "document_kind")}
        props.update(id=identity, ticker=ticker, revision=event.revision,
                     known_at_ts=int(event.occurred_at.timestamp()))
        self.graph._run(
            "MATCH (s:Stock {ticker:$ticker}) MERGE (d:DocumentVersion {id:$id}) "
            "SET d += $props MERGE (d)-[:DOCUMENTS]->(s) RETURN d.id",
            {"ticker": ticker, "id": identity, "props": props},
        )
        ts = int(event.occurred_at.timestamp())
        if active:
            self.graph._run(
                "MATCH (old:DocumentChunk {document_id:$document}) WHERE old.document_version_id<>$version "
                "AND old.is_latest=true SET old.is_latest=false,old.valid_to_ts=$closed RETURN old.id",
                {"document": p["document_id"], "version": identity, "closed": ts - 1},
            )
            self.graph._run(
                "MATCH (d:DocumentVersion {id:$version}),"
                "(old:DocumentVersion {document_id:$document}) WHERE old.revision<$revision "
                "WITH d,old ORDER BY old.revision DESC LIMIT 1 "
                "MERGE (d)-[:SUPERSEDES]->(old) RETURN d.id",
                {"version": identity, "document": p["document_id"], "revision": event.revision},
            )
        for chunk in p["chunks"]:
            chunk_props = {**chunk, "document_version_id": identity, "ticker": ticker,
                           "source_url": p["source_url"], "title": p["title"],
                           "document_id": p["document_id"], "valid_from_ts": ts,
                           "valid_to_ts": 9999999999 if active else int(current.get("known_at_ts", ts))-1,
                           "is_latest": active, "semantic_status": "pending"}
            if p["document_kind"] == "GUIDANCE":
                chunk_props["concall_summary"] = chunk["text"]
            label = "DocumentChunk:GuidanceChunk" if p["document_kind"] == "GUIDANCE" else "DocumentChunk"
            self.graph._run(
                f"MATCH (d:DocumentVersion {{id:$version}}) MERGE (c:{label} {{id:$id}}) "
                "SET c += $props MERGE (c)-[:PART_OF]->(d) RETURN c.id",
                {"version": identity, "id": chunk["id"], "props": chunk_props},
            )
            if p["document_kind"] == "GUIDANCE":
                self.graph._run(
                    "MATCH (s:Stock {ticker:$ticker}),(c:GuidanceChunk {id:$id}) "
                    "MERGE (s)-[:ISSUED_GUIDANCE]->(c) RETURN c.id",
                    {"ticker": ticker, "id": chunk["id"]},
                )
        if active:
            self.graph._run(
                "MERGE (d:DocumentRecord {id:$document}) SET d.revision=$revision,"
                "d.version_id=$version,d.known_at_ts=$ts RETURN d.id",
                {"document": p["document_id"], "revision": event.revision, "version": identity, "ts": ts},
            )
        return True

    def embed_document_chunk(self, chunk_id, embedding):
        self.graph._run(
            "MATCH (c:DocumentChunk {id:$id}) SET c.embedding=vecf32($embedding),"
            "c.semantic_status='completed' RETURN c.id", {"id": chunk_id, "embedding": embedding},
        )

    def document_semantic_status(self, version_id, status):
        self.graph._run(
            "MATCH (d:DocumentVersion {id:$version}) SET d.semantic_status=$status RETURN d.id",
            {"version": version_id, "status": status},
        )
        if status != "completed":
            self.graph._run(
                "MATCH (c:DocumentChunk {document_version_id:$version}) "
                "SET c.semantic_status=$status RETURN c.id", {"version": version_id, "status": status},
            )

    def document_page(self, ticker, query="", offset=0, limit=50):
        limit, offset = max(1, min(int(limit), 100)), max(0, int(offset))
        rows = self.graph._run(
            "MATCH (c:DocumentChunk {ticker:$ticker}) WHERE $query='' "
            "OR toLower(c.text) CONTAINS toLower($query) RETURN properties(c) "
            f"ORDER BY c.document_version_id,c.page,c.ordinal SKIP {offset} LIMIT {limit+1}",
            {"ticker": ticker, "query": query},
        )
        return [public_props(dict(first(row))) for row in rows]

    def guidance_highlights(self, ticker):
        rows = self.graph._run(
            "MATCH (c:DocumentChunk)-[:PART_OF]->(d:DocumentVersion {ticker:$ticker}) "
            "WHERE d.document_kind='GUIDANCE' AND c.is_latest=true "
            "RETURN c.text,c.document_version_id,c.locator,c.source_url "
            "ORDER BY d.known_at_ts DESC,c.ordinal LIMIT 5",
            {"ticker": ticker},
        )
        highlights = []
        for row in rows:
            values = list(row.values()) if isinstance(row, dict) else row
            text = str(values[0])[:2000]
            if len(values) >= 4:
                text += f" [Document version {values[1]}; {values[2]}; source {values[3]}]"
            highlights.append(text)
        return highlights
