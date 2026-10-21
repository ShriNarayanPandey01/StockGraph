"""News 3-layer dedup + routing contract assertions. No live DB required."""

import hashlib

from src.repositories import falkor_repo as m


def deterministic_id(headline: str, ticker: str, event_date: str) -> str:
    return hashlib.sha1(f"{headline.strip().lower()}|{ticker}|{event_date}".encode()).hexdigest()


def test_deterministic_id_shape():
    nid = deterministic_id("RBI holds repo rate", "RELIANCE", "2026-10-01")
    assert len(nid) == 40
    assert deterministic_id("RBI holds repo rate ", "RELIANCE", "2026-10-01") == nid


def test_merge_uses_deterministic_id():
    assert "MERGE (n:NewsEvent {id: $props.id})" in m.MERGE_NEWS_QUERY
    assert "CREATE (n:NewsEvent" not in m.MERGE_NEWS_QUERY


def test_l2_text_dup_query_is_embedding_free():
    assert "embedding" not in m.TEXT_DUP_QUERY
    assert "norm_headline" in m.TEXT_DUP_QUERY
    assert "$window_secs" in m.TEXT_DUP_QUERY
    assert "DUPLICATE_OF" in m.TEXT_DUP_QUERY


def test_l3_vector_dup_query_uses_settings_driven_threshold():
    assert "db.idx.vector.queryNodes" in m.VECTOR_DUP_QUERY
    assert "$threshold" in m.VECTOR_DUP_QUERY
    assert "$window_secs" in m.VECTOR_DUP_QUERY
    assert "DUPLICATE_OF" in m.VECTOR_DUP_QUERY


def test_duplicate_link_shape():
    assert "[:DUPLICATE_OF]" in m.LINK_DUPLICATE_QUERY
    assert "$dup_id" in m.LINK_DUPLICATE_QUERY and "$canon_id" in m.LINK_DUPLICATE_QUERY
