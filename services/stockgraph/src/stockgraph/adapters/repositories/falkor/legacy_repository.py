"""FalkorDB unified graph + vector repository (Rule 1: FalkorDB only)."""

from __future__ import annotations

import asyncio
import logging
import time

from falkordb import FalkorDB
from stockgraph.application.processors.similarity import cosine_similarity
from stockgraph.runtime.settings import settings

logger = logging.getLogger(__name__)

GRAPH_NAME = settings.falkor_graph_name
EMBEDDING_DIM = settings.embedding_dimension
DEFAULT_SECTION_LIMIT = 50
MIN_SECTION_LIMIT = 1
MAX_SECTION_LIMIT = 200
MIN_VECTOR_K = 1
MAX_VECTOR_K = 200

INDEX_CYPHER_STATEMENTS: list[str] = [
    "CREATE INDEX FOR (s:Stock) ON (s.ticker)",
    "CREATE INDEX FOR (c:Commodity) ON (c.id)",
    "CREATE INDEX FOR (m:MacroFactor) ON (m.id)",
    "CREATE INDEX FOR (sec:Sector) ON (sec.id)",
    "CREATE INDEX FOR (n:NewsEvent) ON (n.event_ts)",
    "CREATE INDEX FOR (n:NewsEvent) ON (n.id)",
    "CREATE INDEX FOR (q:QuarterlySnapshot) ON (q.valid_from_ts)",
    "CREATE INDEX FOR (q:QuarterlySnapshot) ON (q.valid_to_ts)",
    "CREATE INDEX FOR (g:GuidanceChunk) ON (g.valid_from_ts)",
    "CREATE INDEX FOR (g:GuidanceChunk) ON (g.valid_to_ts)",
    (
        "CREATE VECTOR INDEX FOR (n:NewsEvent) ON (n.embedding) "
        f"OPTIONS {{dimension: {EMBEDDING_DIM}, similarityFunction: 'cosine'}}"
    ),
    (
        "CREATE VECTOR INDEX FOR (g:GuidanceChunk) ON (g.embedding) "
        f"OPTIONS {{dimension: {EMBEDDING_DIM}, similarityFunction: 'cosine'}}"
    ),
    (
        "CREATE VECTOR INDEX FOR (s:Stock) ON (s.profile_embedding) "
        f"OPTIONS {{dimension: {EMBEDDING_DIM}, similarityFunction: 'cosine'}}"
    ),
]


def _render_section_query(query: str, limit: int) -> str:
    """Render a dossier section query with a literal, clamped LIMIT.

    FalkorDB's parser only accepts an integer token after LIMIT/SKIP; a
    parameter reference (`LIMIT $limit`) is a parse error. Type-checking and
    clamping in Python make the literal interpolation injection-safe.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"section limit must be an int, got {type(limit).__name__}")
    bounded = max(MIN_SECTION_LIMIT, min(limit, MAX_SECTION_LIMIT))
    return query.replace("{limit}", str(bounded))


def _render_vector_k(query: str, k: int) -> str:
    """Render the L3 top-K fan-out as a literal, clamped int.

    FalkorDB's vector call takes a positional integer (not `$k`), so the
    literal interpolation here mirrors `_render_section_query`. Type-checking
    and clamping in Python make it injection-safe.
    """
    if isinstance(k, bool) or not isinstance(k, int):
        raise TypeError(f"vector k must be an int, got {type(k).__name__}")
    bounded = max(MIN_VECTOR_K, min(k, MAX_VECTOR_K))
    return query.replace("{k}", str(bounded))


# Master dossier retrieval (Rule 3: window=LAST_6M|LAST_1Y only, always bounded).
# Run as separate per-section queries (each with LIMIT) and merged in Python —
# a single 6x OPTIONAL MATCH query would cartesian-explode intermediate rows.
# Duplicates never carry impact edges: canonical-only reads exclude DUPLICATE_OF.
# `{limit}` is rendered to a literal int by _render_section_query (FalkorDB
# rejects parameterized LIMIT/SKIP).
DIRECT_NEWS_QUERY = """
MATCH (n:NewsEvent)-[r:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s:Stock {ticker: $ticker})
WHERE n.event_ts >= $start_ts AND n.event_ts <= $end_ts
  AND NOT (n)-[:DUPLICATE_OF]->()
OPTIONAL MATCH (n)-[:CORRELATED_WITH]-(c:NewsEvent)
WHERE NOT (c)-[:DUPLICATE_OF]->()
WITH n, r, collect(DISTINCT c.id) AS correlated_ids
RETURN n.id AS id, n.event_date AS date, n.event_ts AS ts,
       n.headline AS headline, n.summary AS summary,
       n.category AS category, r.sentiment AS sentiment,
       type(r) AS impact_type, r.confidence AS confidence,
       r.causal_rationale AS rationale,
       correlated_ids AS correlated_news_ids
ORDER BY n.event_ts DESC LIMIT {limit}
"""

INDIRECT_NEWS_QUERY = """
MATCH (s:Stock {ticker: $ticker})
      -[exp:EXPOSED_TO|BELONGS_TO|SENSITIVE_TO_MACRO|SUPPLIES_TO|COMPETES_WITH]->(bridge)
      <-[r:SHOCKS|IMPACTS_SECTOR|ALTERS_MACRO]-(n:NewsEvent)
WHERE n.event_ts >= $start_ts AND n.event_ts <= $end_ts
  AND NOT (n)-[:DUPLICATE_OF]->()
  AND (exp.is_latest = true OR exp.is_latest IS NULL)
RETURN n.id AS id, n.event_date AS date, n.event_ts AS ts,
       bridge.id AS via_node, type(exp) AS exposure_type,
       exp.margin_impact AS margin_impact,
       n.headline AS headline, r.sentiment AS sentiment,
       exp.exposure_nature AS exposure_nature,
       exp.confidence AS exposure_confidence,
       exp.rationale AS exposure_rationale
ORDER BY n.event_ts DESC LIMIT {limit}
"""

DEALS_QUERY = """
MATCH (inst:InstitutionalActor)-[deal:EXECUTED_DEAL]->(s:Stock {ticker: $ticker})
WHERE deal.event_ts >= $start_ts AND deal.event_ts <= $end_ts
RETURN inst.name AS actor, inst.category AS actor_cat,
       deal.deal_type AS deal_type, deal.side AS side, deal.qty AS qty,
       deal.value_cr AS value_cr, deal.event_date AS date, deal.event_ts AS ts
ORDER BY deal.event_ts DESC LIMIT {limit}
"""

MF_HOLDINGS_QUERY = """
MATCH (mf:MutualFundHouse)-[mh:UPDATED_HOLDING]->(s:Stock {ticker: $ticker})
WHERE mh.valid_from_ts <= $end_ts AND mh.valid_to_ts >= $start_ts
RETURN mf.name AS amc, mh.month AS month,
       mh.delta_stake_pct AS delta_stake_pct, mh.valid_from_ts AS from_ts
ORDER BY mh.valid_from_ts DESC LIMIT {limit}
"""

QUARTERLY_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[:HAS_QTR_STATE]->(qtr:QuarterlySnapshot)
WHERE qtr.valid_from_ts <= $end_ts AND qtr.valid_to_ts >= $start_ts
RETURN properties(qtr) AS props
ORDER BY qtr.valid_from_ts DESC LIMIT {limit}
"""

GUIDANCE_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[:ISSUED_GUIDANCE]->(gd:GuidanceChunk)
WHERE gd.valid_from_ts <= $end_ts AND gd.valid_to_ts >= $start_ts
RETURN gd.id AS id, gd.quarter AS quarter,
       gd.concall_summary AS concall_summary,
       gd.order_book_cr AS order_book_cr, gd.valid_from_ts AS from_ts,
       gd.valid_to_ts AS to_ts
ORDER BY gd.valid_from_ts DESC LIMIT {limit}
"""

# L2 — text near-dup check before chunking (docs/02 §3.3). No embedding spent.
TEXT_DUP_QUERY = """
MATCH (canon:NewsEvent {ticker: $ticker})
WHERE canon.event_ts >= $now_ts - $window_secs
  AND canon.norm_headline = $norm_headline
  AND NOT (canon)-[:DUPLICATE_OF]->()
RETURN canon
LIMIT 1
"""

# L3 — semantic dedup during vector storage (docs/02 §3.4).
# Score orientation (FalkorDB v4.22.1, cosine index): `score` is cosine
# SIMILARITY in [0, 1] (1.0 = identical vectors), NOT distance. This matches
# `similarityFunction: 'cosine'` in INDEX_CYPHER_STATEMENTS above; identical
# embeddings must score ~1.0 and pass `score >= $threshold`.
# LIVE VALIDATION PENDING: no running FalkorDB was available when this was
# written, so orientation is asserted from index config + unit tests, NOT a
# live server round-trip. `tests/test_l3_dedup.py::test_l3_live_calibration`
# is skipped without `FALKOR_LIVE=1`; run it against staging FalkorDB before
# M4 ingestion goes live to confirm identical-vector score ~= 1.0.
# Defence in depth regardless: the Python `cosine_similarity() >= threshold`
# gate in `resolve_l3_duplicate` is authoritative for the merge decision, so
# a server-side orientation flip causes MISSED dups (recall loss, visible in
# dup-rate metrics) — never silent FALSE merges.
# Recall note: `queryNodes` returns top-K GLOBALLY, then we post-filter by
# ticker/window. K=5 lost in-ticker dups when global neighbours belonged to
# other tickers. K comes from `settings.dedup_vector_k` (default 50) and is
# rendered as a literal int (FalkorDB rejects parameterized K/LIMIT).
# `{k}` is substituted by `find_near_dup()` via `_render_vector_k()`.
VECTOR_DUP_QUERY = """
CALL db.idx.vector.queryNodes('NewsEvent', 'embedding', {k}, vecf32($embedding))
YIELD node, score
WHERE node.ticker = $ticker
  AND node.event_ts >= $now_ts - $window_secs
  AND score >= $threshold
  AND NOT (node)-[:DUPLICATE_OF]->()
RETURN node, score
ORDER BY score DESC
LIMIT 1
"""

MERGE_NEWS_QUERY = """
MERGE (n:NewsEvent {id: $props.id})
SET n += $props,
    n.embedding = vecf32($embedding)
RETURN n
"""

MERGE_NEWS_NO_EMBED_QUERY = """
MERGE (n:NewsEvent {id: $props.id})
SET n += $props
RETURN n
"""

# Stock profile vector (Rule 1): the semantic shortlist for articles that
# name no tracked company. `vecf32` is mandatory - FalkorDB rejects a raw
# list on a vector-typed property.
SET_STOCK_PROFILE_EMBEDDING_QUERY = """
MATCH (s:Stock {ticker: $ticker})
SET s.profile_embedding = vecf32($embedding)
RETURN s.ticker AS ticker
"""

# Semantic shortlist over the stock profile vectors. `score` is cosine
# SIMILARITY in [0, 1] on this index (same orientation as the NewsEvent
# index).
SIMILAR_STOCKS_QUERY = """
CALL db.idx.vector.queryNodes('Stock', 'profile_embedding', {k}, vecf32($embedding))
YIELD node, score
RETURN node.ticker AS ticker, score AS score
ORDER BY score DESC
LIMIT {limit}
"""

LINK_DUPLICATE_QUERY = """
MATCH (dup:NewsEvent {id: $dup_id}), (canon:NewsEvent {id: $canon_id})
MERGE (dup)-[:DUPLICATE_OF]->(canon)
RETURN dup, canon
"""

# News impact edges (Step 2: NewsGraphExtractor). MERGE keeps re-ingestion
# idempotent; confidence/rationale refresh on every write (SET re-runs).
# One statement per edge type: Cypher MERGE does not accept `|` alternation
# in the relationship type position.
# `r.sentiment` carries the PROVIDER's per-entity sentiment score (-1..+1)
# for the impacted stock. It is written from outside the LLM schema, so the
# LLM can never fabricate it. The dossier queries read it back.
MERGE_STOCK_DIRECT_IMPACT_QUERY = """
MATCH (n:NewsEvent {id: $news_id}), (s:Stock {ticker: $ticker})
MERGE (n)-[r:DIRECTLY_IMPACTS]->(s)
SET r.confidence = $confidence,
    r.causal_rationale = $rationale,
    r.sentiment = coalesce($sentiment, r.sentiment),
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_STOCK_INDIRECT_IMPACT_QUERY = """
MATCH (n:NewsEvent {id: $news_id}), (s:Stock {ticker: $ticker})
MERGE (n)-[r:INDIRECTLY_IMPACTS]->(s)
SET r.confidence = $confidence,
    r.causal_rationale = $rationale,
    r.sentiment = coalesce($sentiment, r.sentiment),
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_NEWS_SHOCKS_COMMODITY_QUERY = """
MATCH (n:NewsEvent {id: $news_id}), (c:Commodity {id: $target_id})
MERGE (n)-[r:SHOCKS]->(c)
SET r.confidence = $confidence,
    r.causal_rationale = $rationale,
    r.sentiment = coalesce($sentiment, r.sentiment),
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_NEWS_ALTERS_MACRO_QUERY = """
MATCH (n:NewsEvent {id: $news_id}), (m:MacroFactor {id: $target_id})
MERGE (n)-[r:ALTERS_MACRO]->(m)
SET r.confidence = $confidence,
    r.causal_rationale = $rationale,
    r.sentiment = coalesce($sentiment, r.sentiment),
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_NEWS_IMPACTS_SECTOR_QUERY = """
MATCH (n:NewsEvent {id: $news_id}), (sec:Sector {id: $target_id})
MERGE (n)-[r:IMPACTS_SECTOR]->(sec)
SET r.confidence = $confidence,
    r.causal_rationale = $rationale,
    r.sentiment = coalesce($sentiment, r.sentiment),
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_NEWS_CORRELATION_QUERY = """
MATCH (n:NewsEvent {id: $new_news_id}), (p:NewsEvent {id: $prior_news_id})
MERGE (n)-[r:CORRELATED_WITH]->(p)
SET r.correlation_type = $correlation_type,
    r.confidence = $confidence,
    r.rationale = $rationale,
    r.event_ts = $event_ts
RETURN type(r) AS rel
"""

# L4 - correlation candidates (Step 3: NewsCorrelator). Canonical prior news in
# the trailing window sharing an impacted stock/commodity/macro/sector, or a
# paraphrase-band embedding neighbour. The LLM judges causality; the dup band
# (>= dedup threshold) never reaches correlation - it links DUPLICATE_OF.
CORRELATION_CANDIDATES_QUERY = """
MATCH (n:NewsEvent {id: $news_id})
OPTIONAL MATCH (n)-[:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s:Stock)
OPTIONAL MATCH (n)-[:SHOCKS]->(c:Commodity)
OPTIONAL MATCH (n)-[:ALTERS_MACRO]->(m:MacroFactor)
OPTIONAL MATCH (n)-[:IMPACTS_SECTOR]->(sec:Sector)
WITH n, collect(DISTINCT s.ticker) AS tickers,
     collect(DISTINCT c.id) AS commodities,
     collect(DISTINCT m.id) AS macros,
     collect(DISTINCT sec.id) AS sectors
MATCH (p:NewsEvent)
WHERE p.id <> $news_id
  AND p.event_ts >= $now_ts - $window_secs
  AND p.event_ts <= $now_ts
  AND NOT (p)-[:DUPLICATE_OF]->()
  AND NOT (n)-[:DUPLICATE_OF]->()
OPTIONAL MATCH (p)-[:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(ps:Stock)
OPTIONAL MATCH (p)-[:SHOCKS]->(pc:Commodity)
OPTIONAL MATCH (p)-[:ALTERS_MACRO]->(pm:MacroFactor)
OPTIONAL MATCH (p)-[:IMPACTS_SECTOR]->(psec:Sector)
WITH p, tickers, commodities, macros, sectors,
     collect(DISTINCT ps.ticker) AS p_tickers,
     collect(DISTINCT pc.id) AS p_commodities,
     collect(DISTINCT pm.id) AS p_macros,
     collect(DISTINCT psec.id) AS p_sectors
WHERE size([t IN p_tickers WHERE t IN tickers]) > 0
   OR size([c IN p_commodities WHERE c IN commodities]) > 0
   OR size([x IN p_macros WHERE x IN macros]) > 0
   OR size([x IN p_sectors WHERE x IN sectors]) > 0
RETURN p.id AS id, p.headline AS headline, p.summary AS summary,
       p.event_ts AS event_ts, p.category AS category
ORDER BY p.event_ts DESC LIMIT {limit}
"""

CORRELATION_PARAPHRASE_CANDIDATES_QUERY = """
CALL db.idx.vector.queryNodes('NewsEvent', 'embedding', {k}, vecf32($embedding))
YIELD node, score
WHERE node.id <> $news_id
  AND node.event_ts >= $now_ts - $window_secs
  AND node.event_ts <= $now_ts
  AND score >= $min_cosine
  AND score < $dedup_threshold
  AND NOT (node)-[:DUPLICATE_OF]->()
RETURN node.id AS id, node.headline AS headline, node.summary AS summary,
       node.event_ts AS event_ts, node.category AS category
LIMIT {limit}
"""

GET_ACTIVE_EXPOSURES_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[r:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->(target)
WHERE r.is_latest = true OR r.is_latest IS NULL
RETURN DISTINCT coalesce(target.id, target.ticker) AS entity_id
"""

MERGE_ONTOLOGY_EDGE_EXPOSED_TO = """
MATCH (s:Stock {ticker: $source_id}), (t:Commodity {id: $target_id})
MERGE (s)-[r:EXPOSED_TO {edge_id: $edge_id}]->(t)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.exposure_nature = $exposure_nature,
    r.margin_impact = $margin_impact,
    r.sensitivity = $sensitivity,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_ONTOLOGY_EDGE_SENSITIVE_TO_MACRO = """
MATCH (s:Stock {ticker: $source_id}), (t:MacroFactor {id: $target_id})
MERGE (s)-[r:SENSITIVE_TO_MACRO {edge_id: $edge_id}]->(t)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.sensitivity = $sensitivity,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_ONTOLOGY_EDGE_BELONGS_TO = """
MATCH (s:Stock {ticker: $source_id}), (t:Sector {id: $target_id})
MERGE (s)-[r:BELONGS_TO {edge_id: $edge_id}]->(t)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_ONTOLOGY_EDGE_SUPPLIES_TO = """
MATCH (s:Stock {ticker: $source_id}), (t:Stock {ticker: $target_id})
MERGE (s)-[r:SUPPLIES_TO {edge_id: $edge_id}]->(t)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_ONTOLOGY_EDGE_COMPETES_WITH = """
MATCH (s:Stock {ticker: $source_id}), (t:Stock {ticker: $target_id})
MERGE (s)-[r:COMPETES_WITH {edge_id: $edge_id}]->(t)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

MERGE_ONTOLOGY_EDGE_RELATED_TO = """
MATCH (c1:Commodity {id: $source_id}), (c2:Commodity {id: $target_id})
MERGE (c1)-[r:RELATED_TO {edge_id: $edge_id}]->(c2)
SET r.confidence = $confidence,
    r.rationale = $rationale,
    r.valid_from_ts = $valid_from_ts,
    r.valid_to_ts = 9999999999,
    r.is_latest = true,
    r.inferred_by = $inferred_by
RETURN type(r) AS rel
"""

# Bi-temporal rotation WITHOUT FOREACH (support uncertain on FalkorDB).

# Callers must hold the job's Redis lock; run close_old then create_new.
# Statements project scalar business ids (`old.id`/`new_q.id` properties):
# whole-node RETURNs deserialize into SDK Node objects (Node.id is the internal
# graph id with no dict access), while the SUPERSEDES link needs the business
# `id` property for its property match.
ROTATE_CLOSE_OLD_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[r:HAS_QTR_STATE]->(old:QuarterlySnapshot {is_latest: true})
SET old.is_latest = false,
    old.valid_to_ts = $new_ts - 1
RETURN old.id AS old_id
"""

ROTATE_CREATE_NEW_QUERY = """
MATCH (s:Stock {ticker: $ticker})
CREATE (new_q:QuarterlySnapshot $new_props)
SET new_q.valid_from_ts = $new_ts,
    new_q.valid_to_ts = 9999999999,
    new_q.is_latest = true
CREATE (s)-[:HAS_QTR_STATE]->(new_q)
RETURN new_q.id AS new_id
"""

ROTATE_LINK_SUPERSEDES_QUERY = """
MATCH (new_q:QuarterlySnapshot {id: $new_id}),
      (old:QuarterlySnapshot {id: $old_id})
CREATE (new_q)-[:SUPERSEDES]->(old)
RETURN new_q.id AS new_id
"""

QUARTERLY_SNAPSHOT_EXISTS_QUERY = """
MATCH (q:QuarterlySnapshot {id: $new_id})
RETURN q.id AS new_id
LIMIT 1
"""

# Guidance is a set of vector chunks. A new official document replaces the
# previous active set for a ticker; every newly-created chunk links to the
# prior active chunks, retaining a traversable validity history.
GUIDANCE_SET_EXISTS_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[:ISSUED_GUIDANCE]->
      (g:GuidanceChunk {guidance_set_id: $guidance_set_id, is_latest: true})
RETURN g.id AS id
LIMIT 1
"""

CLOSE_ACTIVE_GUIDANCE_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[:ISSUED_GUIDANCE]->(old:GuidanceChunk {is_latest: true})
SET old.is_latest = false, old.valid_to_ts = $new_ts - 1
RETURN old.id AS old_id
"""

MERGE_GUIDANCE_CHUNK_QUERY = """
MATCH (s:Stock {ticker: $ticker})
MERGE (g:GuidanceChunk {id: $props.id})
SET g += $props
MERGE (s)-[:ISSUED_GUIDANCE]->(g)
RETURN g.id AS id
"""

MERGE_GUIDANCE_CHUNK_WITH_EMBEDDING_QUERY = """
MATCH (s:Stock {ticker: $ticker})
MERGE (g:GuidanceChunk {id: $props.id})
SET g += $props, g.embedding = vecf32($embedding)
MERGE (s)-[:ISSUED_GUIDANCE]->(g)
RETURN g.id AS id
"""

LINK_GUIDANCE_SUPERSEDES_QUERY = """
MATCH (new_g:GuidanceChunk {id: $new_id}), (old_g:GuidanceChunk {id: $old_id})
MERGE (new_g)-[:SUPERSEDES]->(old_g)
RETURN new_g.id AS id
"""

ROTATE_CLOSE_DYNAMIC_EDGES_QUERY = """
MATCH (s:Stock {ticker: $ticker})-[r:EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH]->()
WHERE r.inferred_by = 'LLM' AND r.is_latest = true
SET r.is_latest = false, r.valid_to_ts = $new_ts - 1
RETURN count(r) AS closed_count
"""

ROTATE_MF_CLOSE_OLD_QUERY = """
MATCH (mf:MutualFundHouse {amc_id: $amc_id})-[old:UPDATED_HOLDING]->
      (s:Stock {ticker: $ticker})
WHERE old.is_latest = true AND old.valid_from_ts < $new_ts
SET old.is_latest = false, old.valid_to_ts = $new_ts - 1
RETURN old.valid_from_ts AS old_from_ts
"""

ROTATE_MF_EXISTS_QUERY = """
MATCH (:MutualFundHouse {amc_id: $amc_id})-[h:UPDATED_HOLDING]->
      (:Stock {ticker: $ticker})
WHERE h.valid_from_ts = $new_ts
RETURN h.valid_from_ts AS valid_from_ts
LIMIT 1
"""

ROTATE_MF_CREATE_NEW_QUERY = """
MERGE (mf:MutualFundHouse {amc_id: $props.amc_id})
SET mf.name = $props.amc_name
WITH mf
MATCH (s:Stock {ticker: $ticker})
CREATE (mf)-[new_h:UPDATED_HOLDING $props]->(s)
RETURN new_h.valid_from_ts AS new_from_ts
"""

GET_LATEST_QUARTERLY_QUERY = """
MATCH (:Stock {ticker: $ticker})-[:HAS_QTR_STATE]->(q:QuarterlySnapshot {is_latest: true})
RETURN q.quarter AS quarter, q.rev_yoy_pct AS rev_yoy_pct,
       q.ebitda_margin_pct AS ebitda_margin_pct, q.pat_cr AS pat_cr,
       q.debt_to_equity AS debt_to_equity, q.fcf_cr AS fcf_cr,
       q.promoter_pledge_pct AS promoter_pledge_pct
ORDER BY q.valid_from_ts DESC
LIMIT 1
"""

GET_LATEST_GUIDANCE_QUERY = """
MATCH (:Stock {ticker: $ticker})-[:ISSUED_GUIDANCE]->(g:GuidanceChunk {is_latest: true})
RETURN g.concall_summary AS summary
ORDER BY g.valid_from_ts DESC, g.chunk_index ASC
LIMIT 5
"""


class FalkorGraphRAGRepository:
    """Sync FalkorDB client with async wrappers for FastAPI use."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        graph_name: str | None = None,
    ) -> None:
        self._host = host or settings.falkor_host
        self._port = port or settings.falkor_port
        self._graph_name = graph_name or GRAPH_NAME
        self._db: FalkorDB | None = None

    def connect(self) -> FalkorDB:
        if self._db is None:
            self._db = FalkorDB(host=self._host, port=self._port)
        return self._db

    def _graph(self):  # type: ignore[no-untyped-def]
        return self.connect().select_graph(self._graph_name)

    def ensure_indexes_and_constraints(self) -> list[str]:
        """Run index-creation Cypher on startup. Idempotent: skips existing."""
        executed: list[str] = []
        graph = self._graph()
        for stmt in INDEX_CYPHER_STATEMENTS:
            try:
                graph.query(stmt)
                executed.append(stmt)
            except Exception as exc:  # index already exists
                logger.debug("Skipping index (likely exists): %s (%s)", stmt[:60], exc)
        return executed

    def _run(self, query: str, params: dict) -> list:
        result = self._graph().query(query, params)
        return result.result_set

    def get_temporal_subgraph(
        self, ticker: str, start_ts: int, end_ts: int, limit: int = DEFAULT_SECTION_LIMIT
    ) -> dict:
        """Window-bounded dossier subgraph. Six bounded section queries merged.

        `limit` is type-checked, clamped to [MIN_SECTION_LIMIT, MAX_SECTION_LIMIT]
        and rendered as a literal integer: FalkorDB rejects `LIMIT $param`.
        """
        params = {"ticker": ticker, "start_ts": start_ts, "end_ts": end_ts}
        return {
            "direct_news": self._run(_render_section_query(DIRECT_NEWS_QUERY, limit), params),
            "indirect_news": self._run(_render_section_query(INDIRECT_NEWS_QUERY, limit), params),
            "institutional_deals": self._run(_render_section_query(DEALS_QUERY, limit), params),
            "mf_shifts": self._run(_render_section_query(MF_HOLDINGS_QUERY, limit), params),
            "quarterly_snapshots": self._run(_render_section_query(QUARTERLY_QUERY, limit), params),
            "guidance_chunks": self._run(_render_section_query(GUIDANCE_QUERY, limit), params),
        }

    def find_text_dup(
        self,
        norm_headline: str,
        ticker: str,
        window_secs: int,
        now_ts: int | None = None,
    ) -> dict | None:
        """L2: normalized-headline match within the dedup window.

        `now_ts` (epoch seconds) bounds the window and is required by the
        Cypher (`$now_ts - $window_secs`). It defaults to the current
        epoch so a direct caller still gets a correct window.
        """
        now = int(now_ts) if now_ts is not None else int(time.time())
        rows = self._run(
            TEXT_DUP_QUERY,
            {
                "norm_headline": norm_headline,
                "ticker": ticker,
                "window_secs": window_secs,
                "now_ts": now,
            },
        )
        return rows[0] if rows else None

    def find_near_dup(
        self,
        embedding: list[float],
        ticker: str,
        now_ts: int,
        threshold: float | None = None,
        k: int | None = None,
    ) -> dict | None:
        """L3: 48h vector search; cosine >= threshold returns the canonical node.

        `score` from FalkorDB is cosine SIMILARITY (1.0 = identical) on the
        `similarityFunction: 'cosine'` index — see VECTOR_DUP_QUERY header.
        K comes from `settings.dedup_vector_k` (default 50): `queryNodes`
        fans out globally, then Cypher post-filters by ticker/window.
        Returns the raw row (node + score); callers MUST confirm with
        `resolve_l3_duplicate()` (Python re-score) before linking DUPLICATE_OF.
        """
        window_secs = settings.dedup_window_hours * 3600
        rows = self._run(
            _render_vector_k(VECTOR_DUP_QUERY, k if k is not None else settings.dedup_vector_k),
            {
                "embedding": embedding,
                "ticker": ticker,
                "now_ts": now_ts,
                "window_secs": window_secs,
                "threshold": threshold
                if threshold is not None
                else settings.dedup_cosine_threshold,
            },
        )
        return rows[0] if rows else None

    @staticmethod
    def resolve_l3_duplicate(
        query_embedding: list[float],
        candidate_embedding: list[float] | None,
        threshold: float | None = None,
    ) -> dict[str, float | bool]:
        """Authoritative L3 gate: local cosine re-score vs threshold.

        Returns {"cosine": float, "is_duplicate": bool}. A None/empty
        candidate embedding is never a duplicate (fail-open to new node).
        """
        gate = threshold if threshold is not None else settings.dedup_cosine_threshold
        if not candidate_embedding:
            return {"cosine": 0.0, "is_duplicate": False}
        cosine = cosine_similarity(query_embedding, candidate_embedding)
        return {"cosine": cosine, "is_duplicate": cosine >= gate}

    def merge_news_event(self, props: dict, embedding: list[float] | None = None) -> dict:
        """Deterministic MERGE on NewsEvent.id (L1 id shape enforced by caller).
        If embedding is provided (or present in props), it is indexed using vecf32.
        """
        props_clean = dict(props)
        emb = embedding or props_clean.pop("embedding", None)
        if emb is not None:
            rows = self._run(MERGE_NEWS_QUERY, {"props": props_clean, "embedding": emb})
        else:
            rows = self._run(MERGE_NEWS_NO_EMBED_QUERY, {"props": props_clean})
        return rows[0] if rows else {}

    def set_stock_profile_embedding(self, ticker: str, embedding: list[float]) -> dict:
        """Write the stock's profile vector (Rule 1 - `vecf32` in FalkorDB).

        The vector index on `:Stock.profile_embedding` is the semantic
        shortlist: an article that names no tracked company ("IT stocks gain
        Rs 77,000 crore") is matched against the profile vectors to find the
        companies it is about. Without this write the index is empty and the
        shortlist is limited to provider tags plus literal text matches.
        """
        rows = self._run(
            SET_STOCK_PROFILE_EMBEDDING_QUERY,
            {"ticker": ticker.upper(), "embedding": embedding},
        )
        return rows[0] if rows else {}

    def find_similar_stocks(
        self,
        embedding: list[float],
        k: int = 4,
        min_score: float = 0.0,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Stocks whose profile vector is closest to `embedding`.

        Returns [(ticker, cosine_similarity)]. The score is the FalkorDB
        cosine similarity in [0, 1] (same orientation as the NewsEvent
        index, verified by the L3 calibration test).
        """
        if not embedding:
            return []
        k = max(MIN_VECTOR_K, min(MAX_VECTOR_K, int(k)))
        query = _render_vector_k(SIMILAR_STOCKS_QUERY, k)
        query = _render_section_query(query, max(MIN_SECTION_LIMIT, min(limit, MAX_SECTION_LIMIT)))
        try:
            rows = self._run(query, {"embedding": embedding})
        except Exception as exc:  # noqa: BLE001 - a missing index must not stop ingestion
            logger.warning("Stock similarity search failed: %s", exc)
            return []
        out: list[tuple[str, float]] = []
        for row in rows:
            ticker = row[0] if not isinstance(row, dict) else row.get("ticker")
            score = row[1] if not isinstance(row, dict) else row.get("score")
            if ticker is None or score is None:
                continue
            if float(score) < min_score:
                continue
            out.append((str(ticker), float(score)))
        return out[:limit]

    def link_duplicate(self, dup_id: str, canon_id: str) -> dict:
        """Link (dup)-[:DUPLICATE_OF]->(canonical). Never a self-link."""
        if not dup_id or not canon_id or dup_id == canon_id:
            return {}
        rows = self._run(LINK_DUPLICATE_QUERY, {"dup_id": dup_id, "canon_id": canon_id})
        return rows[0] if rows else {}

    def merge_stock_impact(
        self,
        news_id: str,
        ticker: str,
        impact_type: str,
        confidence: float,
        rationale: str,
        sentiment: float | None = None,
        inferred_by: str = "news_graph_extractor",
    ) -> dict:
        """Persist DIRECTLY_IMPACTS / INDIRECTLY_IMPACTS (idempotent MERGE).

        `sentiment` is the provider's per-entity sentiment for this ticker
        (-1..+1). It is supplied by the caller, never by the LLM.
        """
        query = (
            MERGE_STOCK_DIRECT_IMPACT_QUERY
            if impact_type == "DIRECTLY_IMPACTS"
            else MERGE_STOCK_INDIRECT_IMPACT_QUERY
        )
        rows = self._run(
            query,
            {
                "news_id": news_id,
                "ticker": ticker,
                "confidence": confidence,
                "rationale": rationale,
                "sentiment": sentiment,
                "inferred_by": inferred_by,
            },
        )
        return rows[0] if rows else {}

    def merge_news_shock(
        self,
        news_id: str,
        target_kind: str,
        target_id: str,
        confidence: float,
        rationale: str,
        sentiment: float | None = None,
        inferred_by: str = "news_graph_extractor",
    ) -> dict:
        """Persist SHOCKS (commodity) / ALTERS_MACRO / IMPACTS_SECTOR edges."""
        query = {
            "commodity": MERGE_NEWS_SHOCKS_COMMODITY_QUERY,
            "macro": MERGE_NEWS_ALTERS_MACRO_QUERY,
            "sector": MERGE_NEWS_IMPACTS_SECTOR_QUERY,
        }[target_kind]
        rows = self._run(
            query,
            {
                "news_id": news_id,
                "target_id": target_id,
                "confidence": confidence,
                "rationale": rationale,
                "sentiment": sentiment,
                "inferred_by": inferred_by,
            },
        )
        return rows[0] if rows else {}

    def merge_news_correlation(
        self,
        new_news_id: str,
        prior_news_id: str,
        correlation_type: str,
        confidence: float,
        rationale: str,
        event_ts: int,
    ) -> dict:
        """Persist (new)-[:CORRELATED_WITH]->(prior) (idempotent MERGE)."""
        rows = self._run(
            MERGE_NEWS_CORRELATION_QUERY,
            {
                "new_news_id": new_news_id,
                "prior_news_id": prior_news_id,
                "correlation_type": correlation_type,
                "confidence": confidence,
                "rationale": rationale,
                "event_ts": event_ts,
            },
        )
        return rows[0] if rows else {}

    def find_correlation_candidates(
        self,
        news_id: str,
        now_ts: int,
        limit: int = DEFAULT_SECTION_LIMIT,
        embedding: list[float] | None = None,
    ) -> list:
        """L4: canonical priors in the window sharing an impacted entity or in paraphrase band."""
        window_secs = settings.correlation_window_days * 86400
        query = _render_section_query(CORRELATION_CANDIDATES_QUERY, limit)
        candidates = list(
            self._run(
                query,
                {"news_id": news_id, "now_ts": now_ts, "window_secs": window_secs},
            )
        )

        # Vector paraphrase band candidates [correlation_min_cosine, dedup_cosine_threshold)
        if embedding is not None:
            try:
                vec_query = _render_vector_k(
                    CORRELATION_PARAPHRASE_CANDIDATES_QUERY, settings.dedup_vector_k
                )
                vec_query = _render_section_query(vec_query, limit)
                vec_rows = self._run(
                    vec_query,
                    {
                        "news_id": news_id,
                        "now_ts": now_ts,
                        "window_secs": window_secs,
                        "embedding": embedding,
                        "min_cosine": settings.correlation_min_cosine,
                        "dedup_threshold": settings.dedup_cosine_threshold,
                    },
                )
                seen_ids = {
                    (r[0] if isinstance(r, (list, tuple)) else r.get("id")) for r in candidates
                }
                for vr in vec_rows:
                    vid = vr[0] if isinstance(vr, (list, tuple)) else vr.get("id")
                    if vid and vid not in seen_ids:
                        seen_ids.add(vid)
                        candidates.append(vr)
            except Exception as exc:
                logger.debug("Paraphrase candidates vector search skipped: %s", exc)

        return candidates

    def get_active_exposures(self, ticker: str) -> list[str]:
        """Return list of active entity IDs (commodities/macros/sectors/stocks) linked to the ticker."""
        rows = self._run(GET_ACTIVE_EXPOSURES_QUERY, {"ticker": ticker.upper()})
        out: list[str] = []
        for r in rows:
            val = (
                r[0]
                if isinstance(r, (list, tuple))
                else (r.get("entity_id") if isinstance(r, dict) else None)
            )
            if val:
                out.append(str(val))
        return out

    def get_latest_quarterly_snapshot(self, ticker: str) -> dict | None:
        """Return scalar latest-quarter facts for a StockContextCard."""
        rows = self._run(GET_LATEST_QUARTERLY_QUERY, {"ticker": ticker.upper()})
        if not rows:
            return None
        row = rows[0]
        if isinstance(row, dict):
            return dict(row)
        columns = (
            "quarter",
            "rev_yoy_pct",
            "ebitda_margin_pct",
            "pat_cr",
            "debt_to_equity",
            "fcf_cr",
            "promoter_pledge_pct",
        )
        return {key: row[index] if index < len(row) else None for index, key in enumerate(columns)}

    def get_latest_guidance_highlights(self, ticker: str) -> list[str]:
        """Return bounded current guidance highlights for an LLM context card."""
        rows = self._run(GET_LATEST_GUIDANCE_QUERY, {"ticker": ticker.upper()})
        out: list[str] = []
        for row in rows:
            value = row.get("summary") if isinstance(row, dict) else row[0]
            if value:
                out.append(str(value))
        return out

    def merge_ontology_edge(
        self,
        source_id: str,
        relation: str,
        target_id: str,
        confidence: float,
        rationale: str,
        exposure_nature: str | None = None,
        margin_impact: str | None = None,
        sensitivity: float | None = None,
        valid_from_ts: int | None = None,
        inferred_by: str = "LLM",
    ) -> dict:
        """Write a versioned inferred ontology edge without touching seed edges."""
        queries = {
            "EXPOSED_TO": MERGE_ONTOLOGY_EDGE_EXPOSED_TO,
            "SENSITIVE_TO_MACRO": MERGE_ONTOLOGY_EDGE_SENSITIVE_TO_MACRO,
            "BELONGS_TO": MERGE_ONTOLOGY_EDGE_BELONGS_TO,
            "SUPPLIES_TO": MERGE_ONTOLOGY_EDGE_SUPPLIES_TO,
            "COMPETES_WITH": MERGE_ONTOLOGY_EDGE_COMPETES_WITH,
            "RELATED_TO": MERGE_ONTOLOGY_EDGE_RELATED_TO,
        }
        query = queries.get(relation)
        if not query:
            logger.warning("Unknown ontology relation %s", relation)
            return {}
        effective_ts = int(time.time()) if valid_from_ts is None else valid_from_ts
        rows = self._run(
            query,
            {
                "source_id": source_id,
                "target_id": target_id,
                "confidence": confidence,
                "rationale": rationale,
                "exposure_nature": exposure_nature,
                "margin_impact": margin_impact,
                "sensitivity": sensitivity,
                "valid_from_ts": effective_ts,
                "inferred_by": inferred_by,
                "edge_id": (f"{inferred_by}:{relation}:{source_id}:{target_id}:{effective_ts}"),
            },
        )
        return rows[0] if rows else {}

    def rotate_dynamic_ontology_edges(self, ticker: str, edges: list, new_ts: int) -> int:
        """Replace one stock's active LLM edges after a quarterly refresh.

        Curated seed edges are permanent baseline edges and are deliberately
        excluded.  A retry with the same timestamp is idempotent because each
        new relationship has a deterministic ``edge_id``.
        """
        self._run(ROTATE_CLOSE_DYNAMIC_EDGES_QUERY, {"ticker": ticker.upper(), "new_ts": new_ts})
        written = 0
        for edge in edges:
            source_id = getattr(edge, "source_id", None)
            if source_id != ticker.upper():
                # A quarterly stock refresh must not close independent
                # commodity-to-commodity discoveries.
                continue
            result = self.merge_ontology_edge(
                source_id=source_id,
                relation=getattr(edge.relation, "value", edge.relation),
                target_id=edge.target_id,
                confidence=edge.confidence,
                rationale=edge.rationale,
                exposure_nature=getattr(edge, "exposure_nature", None),
                margin_impact=getattr(edge, "margin_impact", None),
                sensitivity=getattr(edge, "sensitivity", None),
                valid_from_ts=new_ts,
                inferred_by="LLM",
            )
            if result:
                written += 1
        return written

    def rotate_validity_interval_node(self, ticker: str, new_ts: int, new_props: dict) -> dict:
        """Close the old latest snapshot, create the new one, link SUPERSEDES.

        Three statements instead of FOREACH (uncertain support). The caller MUST
        hold the job's Redis lock so two writers cannot both stay is_latest.
        Each statement projects a scalar business id (`old.id`/`new_q.id`), so
        nothing is deserialized into SDK Node objects.

        Returns {"new_id": str | None, "old_id": str | None}.
        """
        if not new_props.get("id"):
            raise ValueError("QuarterlySnapshot requires a deterministic business id")
        close_rows = self._run(ROTATE_CLOSE_OLD_QUERY, {"ticker": ticker, "new_ts": new_ts})
        old_id = close_rows[0][0] if close_rows else None
        rows = self._run(
            ROTATE_CREATE_NEW_QUERY,
            {"ticker": ticker, "new_ts": new_ts, "new_props": new_props},
        )
        new_id = rows[0][0] if rows else None
        if not new_id:
            logger.error("Quarterly rotation: no new snapshot created for %s", ticker)
            return {"new_id": None, "old_id": old_id}
        if old_id:
            self._run(ROTATE_LINK_SUPERSEDES_QUERY, {"new_id": new_id, "old_id": old_id})
        return {"new_id": new_id, "old_id": old_id}

    def has_quarterly_snapshot(self, snapshot_id: str) -> bool:
        """Check a deterministic snapshot id before a replayed rotation."""
        return bool(self._run(QUARTERLY_SNAPSHOT_EXISTS_QUERY, {"new_id": snapshot_id}))

    def rotate_mf_holding(self, ticker: str, props: dict) -> bool:
        """Mirror the SQL MF-holding interval in FalkorDB."""
        new_ts = int(props["valid_from_ts"])
        exists = self._run(
            ROTATE_MF_EXISTS_QUERY,
            {"ticker": ticker.upper(), "amc_id": props["amc_id"], "new_ts": new_ts},
        )
        if exists:
            return False
        self._run(
            ROTATE_MF_CLOSE_OLD_QUERY,
            {"ticker": ticker.upper(), "amc_id": props["amc_id"], "new_ts": new_ts},
        )
        rows = self._run(
            ROTATE_MF_CREATE_NEW_QUERY,
            {
                "ticker": ticker.upper(),
                "props": {**props, "is_latest": True, "valid_to_ts": 9999999999},
            },
        )
        return bool(rows)

    def replace_guidance_chunks(
        self,
        ticker: str,
        guidance_set_id: str,
        new_ts: int,
        chunks: list[dict],
    ) -> int:
        """Rotate a guidance-document chunk set and retain SUPERSEDES links."""
        existing = self._run(
            GUIDANCE_SET_EXISTS_QUERY,
            {"ticker": ticker.upper(), "guidance_set_id": guidance_set_id},
        )
        if existing:
            return 0
        closed = self._run(
            CLOSE_ACTIVE_GUIDANCE_QUERY, {"ticker": ticker.upper(), "new_ts": new_ts}
        )
        old_ids = [row.get("old_id") if isinstance(row, dict) else row[0] for row in closed]
        written = 0
        for chunk in chunks:
            props = {
                **chunk,
                "guidance_set_id": guidance_set_id,
                "valid_from_ts": new_ts,
                "valid_to_ts": 9999999999,
                "is_latest": True,
            }
            embedding = props.pop("embedding", None)
            if embedding is None:
                rows = self._run(
                    MERGE_GUIDANCE_CHUNK_QUERY, {"ticker": ticker.upper(), "props": props}
                )
            else:
                rows = self._run(
                    MERGE_GUIDANCE_CHUNK_WITH_EMBEDDING_QUERY,
                    {"ticker": ticker.upper(), "props": props, "embedding": embedding},
                )
            if not rows:
                continue
            new_id = rows[0].get("id") if isinstance(rows[0], dict) else rows[0][0]
            for old_id in old_ids:
                if old_id:
                    self._run(LINK_GUIDANCE_SUPERSEDES_QUERY, {"new_id": new_id, "old_id": old_id})
            written += 1
        return written

    async def aget_temporal_subgraph(
        self, ticker: str, start_ts: int, end_ts: int, limit: int = DEFAULT_SECTION_LIMIT
    ) -> dict:
        return await asyncio.to_thread(self.get_temporal_subgraph, ticker, start_ts, end_ts, limit)

    async def aensure_indexes_and_constraints(self) -> list[str]:
        return await asyncio.to_thread(self.ensure_indexes_and_constraints)
