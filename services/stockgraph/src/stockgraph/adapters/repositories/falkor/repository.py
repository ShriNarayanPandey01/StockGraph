"""Canonical graph projections and graph-only, paginated context reads."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from uuid import uuid4

from stockgraph.adapters.repositories.falkor.legacy_repository import FalkorGraphRAGRepository
from stockgraph.adapters.repositories.falkor.news_reconciliation import NewsReconciliation
from stockgraph.runtime.settings import settings

KINDS = {"Stock": "ticker", "Commodity": "id", "MacroFactor": "id", "Sector": "id"}
# Narrative and identity only: provider payloads and numeric financial facts stay upstream.
ENTITY_FIELDS = {
    "id",
    "ticker",
    "isin",
    "name",
    "aliases",
    "sector",
    "business_summary",
    "revenue_segments",
    "raw_material_inputs",
    "geographic_exposure",
    "strengths",
    "business_exclusions",
    "description",
    "why_it_moves",
    "equity_transmission",
    "unit",
    "related_ids",
    "related_rationale",
    "exposures",
    "latest_quarter_summary",
    "latest_guidance_highlights",
    "source",
    "source_url",
    "prospectus_links",
    "vendor_id",
    "vendor_as_of",
}


def first(row: Any) -> Any:
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def public_props(props: dict) -> dict:
    return {
        k: v
        for k, v in props.items()
        if k not in {"embedding", "profile_embedding", "profile_json"}
    }


class GraphRepository(NewsReconciliation, FalkorGraphRAGRepository):
    def professional_page(self, ticker, start, end, offset=0, limit=50):
        from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
        return EvidenceRepository(self).professional_page(ticker, start, end, offset, limit)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._write_guard = None

    def set_write_guard(self, guard) -> None:
        self._write_guard = guard

    def _run(self, query: str, params: dict) -> list:
        if self._write_guard is not None and re.search(
            r"\b(MERGE|CREATE|SET|DELETE|REMOVE)\b", query, re.I
        ):
            self._write_guard()
        return super()._run(query, params)

    def merge_stock_profile_embedding(self, ticker: str, embedding: list[float]) -> None:
        self._run(
            "MATCH (s:Stock {ticker:$ticker}) SET s.profile_embedding=vecf32($embedding) RETURN s.ticker",
            {"ticker": ticker, "embedding": embedding},
        )

    def get_entity(self, kind: str, entity_id: str) -> dict | None:
        key = KINDS[kind]
        rows = self._run(f"MATCH (n:{kind} {{{key}: $id}}) RETURN properties(n)", {"id": entity_id})
        if not rows:
            return None
        props = dict(first(rows[0]))
        profile = json.loads(props.get("profile_json") or "{}")
        return {**profile, **public_props(props)}

    def catalog(self) -> dict[str, list[dict]]:
        result = {}
        for kind in KINDS:
            rows = self._run(f"MATCH (n:{kind}) RETURN properties(n)", {})
            result[kind] = [
                {**json.loads(first(row).get("profile_json") or "{}"), **public_props(first(row))}
                for row in rows
            ]
        return result

    def project_entity(
        self, kind: str, entity_id: str, entity: dict, revision: int, event_ts: int
    ) -> bool:
        """Project a committed registry event. Retries do not produce duplicate history."""
        key = KINDS[kind]
        current = self.get_entity(kind, entity_id)
        if current and int(current.get("revision", 0)) > revision:
            return False
        safe = {k: v for k, v in entity.items() if k in ENTITY_FIELDS}
        safe[key] = entity_id
        state_hash = hashlib.sha256(
            json.dumps(safe, sort_keys=True, default=str).encode()
        ).hexdigest()
        if kind == "MacroFactor" and (not current or current.get("state_hash") != state_hash):
            self._rotate_macro(entity_id, safe, state_hash, revision, event_ts, current)
        primitive = {
            k: v
            for k, v in safe.items()
            if isinstance(v, (str, bool))
            or (isinstance(v, list) and all(isinstance(item, str) for item in v))
        }
        props = {
            **primitive,
            "profile_json": json.dumps(safe),
            "revision": revision,
            "state_hash": state_hash,
            "processing_state": "graph_processing",
        }
        self._run(
            f"MERGE (n:{kind} {{{key}: $id}}) SET n += $props RETURN n.{key}",
            {"id": entity_id, "props": props},
        )
        self.ensure_macro_baseline()
        self._curated_links(kind, entity_id, safe)
        return True

    def _rotate_macro(
        self,
        entity_id: str,
        entity: dict,
        state_hash: str,
        revision: int,
        event_ts: int,
        current: dict | None,
    ) -> None:
        version_id = f"{entity_id}:{revision}"
        existing_version = self._run(
            "MATCH (v:MacroFactorVersion {id:$id}) RETURN properties(v)", {"id": version_id}
        )
        if existing_version:
            previous = first(existing_version[0]).get("previous_version_id")
            if previous:
                self._run(
                    "MATCH (v:MacroFactorVersion {id:$new}), (old:MacroFactorVersion {id:$old}) "
                    "MERGE (v)-[:SUPERSEDES]->(old) RETURN v.id",
                    {"new": version_id, "old": previous},
                )
            return
        # Do not regress the active descriptive state for a late older observation.
        latest = self._run(
            "MATCH (v:MacroFactorVersion {macro_id:$id, is_latest:true}) RETURN properties(v)",
            {"id": entity_id},
        )
        old = first(latest[0]) if latest else None
        if old is None:
            # Recover an interrupted close/create sequence without losing the history chain.
            previous_rows = self._run(
                "MATCH (v:MacroFactorVersion {macro_id:$id}) RETURN properties(v) "
                "ORDER BY v.valid_from_ts DESC LIMIT 1",
                {"id": entity_id},
            )
            old = first(previous_rows[0]) if previous_rows else None
        if old and old.get("source_event_ts", old["valid_from_ts"]) > event_ts:
            raise ValueError(
                "Late macro state cannot replace a newer active state; replay chronologically"
            )
        if old and old["id"] == version_id:
            return
        valid_from = max(event_ts, old["valid_from_ts"] + 1) if old else event_ts
        if old:
            self._run(
                "MATCH (v:MacroFactorVersion {id:$id}) SET v.is_latest=false, v.valid_to_ts=$end RETURN v.id",
                {"id": old["id"], "end": valid_from - 1},
            )
        self._run(
            "MERGE (m:MacroFactor {id:$id}) MERGE (v:MacroFactorVersion {id:$version_id}) "
            "SET v += $props MERGE (m)-[:HAS_VERSION]->(v) RETURN v.id",
            {
                "id": entity_id,
                "version_id": version_id,
                "props": {
                    "macro_id": entity_id,
                    "state_hash": state_hash,
                    "profile_json": json.dumps(entity),
                    "valid_from_ts": valid_from,
                    "source_event_ts": event_ts,
                    "previous_version_id": old["id"] if old else "",
                    "valid_to_ts": 9999999999,
                    "is_latest": True,
                },
            },
        )
        if old:
            self._run(
                "MATCH (v:MacroFactorVersion {id:$new}), (old:MacroFactorVersion {id:$old}) "
                "MERGE (v)-[:SUPERSEDES]->(old) RETURN v.id",
                {"new": version_id, "old": old["id"]},
            )

    def ensure_macro_baseline(self) -> None:
        self._run(
            "MATCH (s:Stock), (m:MacroFactor) "
            "MERGE (s)-[r:SENSITIVE_TO_MACRO {baseline:true}]->(m) "
            "ON CREATE SET r.confidence=1.0, r.rationale='All registered stocks share the macro baseline', "
            "r.inferred_by='policy_baseline', r.valid_from_ts=0, r.valid_to_ts=9999999999, r.is_latest=true "
            "RETURN count(r)",
            {},
        )

    def _curated_links(self, kind: str, entity_id: str, entity: dict) -> None:
        if kind == "Stock":
            for target in entity.get("exposures", []):
                self.merge_ontology_edge(
                    entity_id,
                    "EXPOSED_TO",
                    target,
                    1.0,
                    "Operator-curated stock exposure",
                    valid_from_ts=0,
                    inferred_by="registry",
                )
        if kind == "Commodity":
            for target in entity.get("related_ids", []):
                self.merge_ontology_edge(
                    entity_id,
                    "RELATED_TO",
                    target,
                    1.0,
                    entity.get("related_rationale") or "Operator-curated commodity linkage",
                    valid_from_ts=0,
                    inferred_by="registry",
                )
            # Bootstrap/API events can arrive before an outgoing target exists.
            # Repair committed incoming declarations when that target appears;
            # never fabricate a target node and never lose links to event order.
            incoming = self._run(
                "MATCH (c:Commodity) WHERE $id IN coalesce(c.related_ids,[]) "
                "RETURN c.id, c.related_rationale",
                {"id": entity_id},
            )
            for source_id, rationale in incoming:
                self.merge_ontology_edge(
                    source_id,
                    "RELATED_TO",
                    entity_id,
                    1.0,
                    rationale or "Operator-curated commodity linkage",
                    valid_from_ts=0,
                    inferred_by="registry",
                )

    def mark_entity_processed(
        self, kind: str, entity_id: str, revision: int, state: str = "completed"
    ) -> None:
        key = KINDS[kind]
        self._run(
            f"MATCH (n:{kind} {{{key}:$id}}) WHERE n.revision=$revision "
            "SET n.inference_revision=$revision, n.processing_state=$state RETURN n",
            {"id": entity_id, "revision": revision, "state": state},
        )

    def reconcile_curated_links(self) -> None:
        """Repair interrupted/out-of-order baseline projection without paid inference.

        Call under the graph writer lease. Registry links are permanent; normalize
        the timestamp from versions that interpreted zero as a missing timestamp.
        """
        self._run(
            "MATCH (a)-[r]->(b) WHERE r.inferred_by='registry' "
            "SET r.valid_from_ts=0, r.edge_id='registry:' + type(r) + ':' + "
            "coalesce(a.ticker,a.id) + ':' + coalesce(b.ticker,b.id) + ':0' RETURN count(r)",
            {},
        )
        catalog = self.catalog()
        for kind in ("Stock", "Commodity"):
            for entity in catalog[kind]:
                self._curated_links(kind, entity[KINDS[kind]], entity)
        self.ensure_macro_baseline()

    def mark_entity_failed(self, kind: str, entity_id: str) -> None:
        key = KINDS[kind]
        self._run(
            f"MATCH (n:{kind} {{{key}:$id}}) SET n.processing_state='failed' RETURN n.{key}",
            {"id": entity_id},
        )

    def create_developer_edge(
        self,
        *,
        source_kind: str,
        source_id: str,
        target_kind: str,
        target_id: str,
        relation: str,
        rationale: str,
        actor: str,
        confidence: float | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an auditable manual relationship between existing graph nodes.

        Node labels and business IDs are parameters, rather than interpolated
        into Cypher.  This supports any existing labeled node while preventing
        Cypher injection.  The relationship label stays ``DEVELOPER_LINK``;
        the requested semantic relation is data, not executable Cypher.
        """
        edge_id = f"developer:{uuid4()}"
        event_ts = int(time.time())
        props = {
            "edge_id": edge_id,
            "relation": relation,
            "rationale": rationale,
            "actor": actor,
            "confidence": confidence,
            "event_ts": event_ts,
            "inferred_by": "developer_api",
            "metadata_json": json.dumps(metadata, sort_keys=True, default=str),
        }
        rows = self._run(
            "MATCH (source), (target) "
            "WHERE $source_kind IN labels(source) "
            "AND coalesce(source.ticker,source.id)=$source_id "
            "AND $target_kind IN labels(target) "
            "AND coalesce(target.ticker,target.id)=$target_id "
            "CREATE (source)-[r:DEVELOPER_LINK {edge_id:$edge_id}]->(target) "
            "SET r += $props RETURN r.edge_id",
            {
                "source_kind": source_kind,
                "source_id": source_id,
                "target_kind": target_kind,
                "target_id": target_id,
                "edge_id": edge_id,
                "props": props,
            },
        )
        if not rows:
            raise KeyError("Source or target graph node was not found")
        return {
            "edge_id": edge_id,
            "source": {"kind": source_kind, "id": source_id},
            "target": {"kind": target_kind, "id": target_id},
            "relation": relation,
            "rationale": rationale,
            "actor": actor,
            "confidence": confidence,
            "event_ts": event_ts,
            "metadata": metadata,
        }

    def delete_developer_edge(self, edge_id: str) -> bool:
        """Delete exactly one developer override, never a system/LLM edge."""
        rows = self._run(
            "MATCH ()-[r:DEVELOPER_LINK {edge_id:$edge_id}]->() "
            "WITH r DELETE r RETURN 1 AS deleted",
            {"edge_id": edge_id},
        )
        return bool(rows)

    def historical_news(self, start_ts: int, offset: int = 0, limit: int = 100) -> list[dict]:
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
        rows = self._run(
            "MATCH (n:NewsEvent) WHERE n.event_ts >= $start AND NOT (n)-[:DUPLICATE_OF]->() "
            f"RETURN properties(n) ORDER BY n.event_ts, n.id SKIP {offset} LIMIT {limit}",
            {"start": start_ts},
        )
        return [dict(first(row)) for row in rows]

    def find_news(self, news_id: str) -> dict | None:
        rows = self._run("MATCH (n:NewsEvent {id:$id}) RETURN properties(n)", {"id": news_id})
        return dict(first(rows[0])) if rows else None

    def context_page(
        self, ticker: str, start_ts: int, end_ts: int, offset: int, limit: int
    ) -> dict:
        # Numeric literals are validated before rendering: Falkor rejects SKIP/LIMIT parameters.
        skip, take = max(0, int(offset)), min(200, max(1, int(limit))) + 1
        params = {
            "ticker": ticker,
            "start": start_ts,
            "end": end_ts,
            "confidence": settings.ontology_min_confidence,
        }
        temporal = (
            "coalesce(exp.valid_from_ts,0)<=$end AND coalesce(exp.valid_to_ts,9999999999)>=$start"
        )
        qualified = "coalesce(exp.confidence,0)>=$confidence"
        ontology = self._run(
            "MATCH (s:Stock {ticker:$ticker})-[exp:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->(t) "
            f"WHERE {temporal} AND {qualified} "
            "RETURN labels(t)[0], properties(t), type(exp), properties(exp) "
            f"ORDER BY labels(t)[0], coalesce(t.id,t.ticker), exp.valid_from_ts SKIP {skip} LIMIT {take}",
            params,
        )
        direct = self._run(
            "MATCH (n:NewsEvent)-[r:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s:Stock {ticker:$ticker}) "
            "WHERE n.event_ts >= $start AND n.event_ts <= $end AND r.confidence >= $confidence "
            "AND NOT (n)-[:DUPLICATE_OF]->() "
            "RETURN properties(n), type(r), properties(r) "
            f"ORDER BY n.event_ts DESC,n.id,type(r) SKIP {skip} LIMIT {take}",
            params,
        )
        indirect = self._run(
            "MATCH (s:Stock {ticker:$ticker})-[exp:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->(t)"
            "<-[r:SHOCKS|ALTERS_MACRO|IMPACTS_SECTOR]-(n:NewsEvent) "
            f"WHERE {temporal} AND {qualified} AND r.confidence >= $confidence "
            "AND n.event_ts >= $start AND n.event_ts <= $end AND NOT (n)-[:DUPLICATE_OF]->() "
            "RETURN properties(n), labels(t)[0],properties(t),type(exp),properties(exp),type(r),properties(r) "
            f"ORDER BY n.event_ts DESC,n.id,coalesce(t.id,t.ticker),exp.valid_from_ts SKIP {skip} LIMIT {take}",
            params,
        )
        return {"ontology": ontology, "direct": direct, "indirect": indirect}

    def public_market_graph_data(self, start_ts: int, end_ts: int) -> dict[str, list[dict]]:
        """Read the bounded source rows used to compose the public market preview.

        This deliberately returns only public-market labels and relationship types.
        The application service decides the final compact connected subgraph, keeping
        the database queries simple and the visual-selection policy testable.
        """
        params = {
            "start": start_ts,
            "end": end_ts,
            "confidence": settings.ontology_min_confidence,
        }
        temporal = (
            "coalesce(r.valid_from_ts,0)<=$end AND "
            "coalesce(r.valid_to_ts,9999999999)>=$start"
        )
        candidates = self._run(
            "MATCH (s:Stock) "
            "OPTIONAL MATCH (n:NewsEvent)-[impact:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s) "
            "WHERE n.event_ts >= $start AND n.event_ts <= $end "
            "AND coalesce(impact.confidence,0) >= $confidence "
            "AND NOT (n)-[:DUPLICATE_OF]->() "
            "OPTIONAL MATCH (s)-[ontology:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->() "
            "WHERE coalesce(ontology.valid_from_ts,0)<=$end AND "
            "coalesce(ontology.valid_to_ts,9999999999)>=$start "
            "AND coalesce(ontology.confidence,0) >= $confidence "
            "AND NOT (type(ontology)='SENSITIVE_TO_MACRO' AND coalesce(ontology.baseline,false)) "
            "RETURN properties(s), count(DISTINCT n), count(DISTINCT ontology) "
            "ORDER BY count(DISTINCT n) DESC, count(DISTINCT ontology) DESC, s.ticker ASC LIMIT 200",
            params,
        )
        ontology = self._run(
            "MATCH (s:Stock)-[r:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->(t) "
            f"WHERE {temporal} AND coalesce(r.confidence,0) >= $confidence "
            "AND NOT (type(r)='SENSITIVE_TO_MACRO' AND coalesce(r.baseline,false)) "
            "AND (t:Stock OR t:Commodity OR t:MacroFactor OR t:Sector) "
            "RETURN properties(s), labels(t)[0], properties(t), type(r), properties(r) LIMIT 600",
            params,
        )
        impacts = self._run(
            "MATCH (n:NewsEvent)-[r:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s:Stock) "
            "WHERE n.event_ts >= $start AND n.event_ts <= $end "
            "AND coalesce(r.confidence,0) >= $confidence AND NOT (n)-[:DUPLICATE_OF]->() "
            "RETURN properties(n), properties(s), type(r), properties(r) "
            "ORDER BY n.event_ts DESC, n.id ASC LIMIT 600",
            params,
        )
        shocks = self._run(
            "MATCH (n:NewsEvent)-[r:SHOCKS|ALTERS_MACRO|IMPACTS_SECTOR]->(t) "
            "WHERE n.event_ts >= $start AND n.event_ts <= $end "
            "AND coalesce(r.confidence,0) >= $confidence AND NOT (n)-[:DUPLICATE_OF]->() "
            "AND (t:Commodity OR t:MacroFactor OR t:Sector) "
            "RETURN properties(n), labels(t)[0], properties(t), type(r), properties(r) "
            "ORDER BY n.event_ts DESC, n.id ASC LIMIT 600",
            params,
        )
        correlations = self._run(
            "MATCH (newer:NewsEvent)-[r:CORRELATED_WITH]->(older:NewsEvent) "
            "WHERE newer.event_ts >= $start AND newer.event_ts <= $end "
            "AND older.event_ts >= $start AND older.event_ts <= $end "
            "AND NOT (newer)-[:DUPLICATE_OF]->() AND NOT (older)-[:DUPLICATE_OF]->() "
            "RETURN properties(newer), properties(older), properties(r) "
            "ORDER BY newer.event_ts DESC, newer.id ASC LIMIT 300",
            params,
        )
        related = self._run(
            "MATCH (source:Commodity)-[r:RELATED_TO]->(target:Commodity) "
            "RETURN properties(source), properties(target), properties(r) LIMIT 200",
            {},
        )

        def props(value: Any) -> dict:
            return dict(value or {})

        return {
            "candidates": [
                {"stock": props(row[0]), "news_count": int(row[1]), "ontology_count": int(row[2])}
                for row in candidates
            ],
            "ontology": [
                {
                    "source": props(row[0]), "target_kind": row[1], "target": props(row[2]),
                    "relation": row[3], "properties": props(row[4]),
                }
                for row in ontology
            ],
            "impacts": [
                {"news": props(row[0]), "stock": props(row[1]), "relation": row[2], "properties": props(row[3])}
                for row in impacts
            ],
            "shocks": [
                {
                    "news": props(row[0]), "target_kind": row[1], "target": props(row[2]),
                    "relation": row[3], "properties": props(row[4]),
                }
                for row in shocks
            ],
            "correlations": [
                {"source": props(row[0]), "target": props(row[1]), "properties": props(row[2])}
                for row in correlations
            ],
            "related": [
                {"source": props(row[0]), "target": props(row[1]), "properties": props(row[2])}
                for row in related
            ],
        }
