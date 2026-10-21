"""L3 dedup correctness (Issue 3 mitigation). No live DB required.

Locks in: score IS cosine similarity (1.0 = identical), K=50 fan-out from
settings (never hardcoded), `>=` gate, deterministic Python re-score.
"""

import os

import pytest

from src.config.settings import settings
from src.repositories import falkor_repo as m


def test_vector_dup_query_declares_similarity_orientation():
    q = m.VECTOR_DUP_QUERY
    assert "db.idx.vector.queryNodes" in q
    assert "vecf32($embedding)" in q
    # Similarity gate: identical vectors (~1.0) must pass.
    assert "score >= $threshold" in q
    assert "score > $threshold" not in q  # strict `>` dropped exact-threshold hits
    assert "RETURN node, score" in q
    assert "ORDER BY score DESC" in q
    assert "DUPLICATE_OF" in q
    assert "{k}" in q  # K rendered as literal by _render_vector_k
    assert ", 5," not in q  # old hardcoded K=5 recall hole


def test_vector_k_comes_from_settings_and_clamps():
    assert settings.dedup_vector_k == 50
    rendered = m._render_vector_k(m.VECTOR_DUP_QUERY, settings.dedup_vector_k)
    assert "'embedding', 50," in rendered
    assert "{k}" not in rendered
    assert "'embedding', 200," in m._render_vector_k(m.VECTOR_DUP_QUERY, 10_000)
    assert "'embedding', 1," in m._render_vector_k(m.VECTOR_DUP_QUERY, 0)
    with pytest.raises(TypeError):
        m._render_vector_k(m.VECTOR_DUP_QUERY, "50")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        m._render_vector_k(m.VECTOR_DUP_QUERY, True)


def test_find_near_dup_uses_settings_k_and_threshold(monkeypatch):
    repo = m.FalkorGraphRAGRepository()
    seen: dict = {}

    def fake_run(query: str, params: dict) -> list:
        seen["query"] = query
        seen["params"] = params
        return []

    monkeypatch.setattr(repo, "_run", fake_run)
    repo.find_near_dup([0.1, 0.2], "RELIANCE", 1_700_000_000)
    assert "'embedding', 50," in seen["query"]
    assert seen["params"]["threshold"] == settings.dedup_cosine_threshold == 0.92
    assert seen["params"]["window_secs"] == settings.dedup_window_hours * 3600 == 48 * 3600


def test_cosine_similarity_orientation():
    # Identical vectors score 1.0 (similarity, NOT distance).
    assert m.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert m.cosine_similarity([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)
    # Orthogonal → 0.0, opposite → -1.0.
    assert m.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert m.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    # Degenerate inputs fail-open to 0.0 (never a false duplicate).
    assert m.cosine_similarity([], []) == 0.0
    assert m.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert m.cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_resolve_l3_duplicate_gates_on_threshold():
    dup = m.FalkorGraphRAGRepository.resolve_l3_duplicate([1.0, 0.0], [1.0, 0.0])
    assert dup["is_duplicate"] is True and dup["cosine"] == pytest.approx(1.0)
    near = m.FalkorGraphRAGRepository.resolve_l3_duplicate([1.0, 0.0], [0.0, 1.0])
    assert near["is_duplicate"] is False  # 0.0 < 0.92
    # Paraphrase band (0.68–0.92) → NOT a dup (L4 correlation candidate).
    assert (
        m.FalkorGraphRAGRepository.resolve_l3_duplicate([1.0, 0.0], [1.0, 0.5])["is_duplicate"]
        is False
    )
    # Missing candidate embedding fails OPEN (new node, never false merge).
    assert m.FalkorGraphRAGRepository.resolve_l3_duplicate([1.0], None)["is_duplicate"] is False
    assert m.FalkorGraphRAGRepository.resolve_l3_duplicate([1.0], [])["is_duplicate"] is False


@pytest.mark.skipif(
    os.environ.get("FALKOR_LIVE") != "1",
    reason="Needs a running FalkorDB (docker compose up falkordb); set FALKOR_LIVE=1.",
)
def test_l3_live_calibration():
    """Live orientation check: identical vector must score ~= 1.0 (similarity).

    Run: `FALKOR_LIVE=1 python -m pytest tests/test_l3_dedup.py::test_l3_live_calibration`
    against staging FalkorDB BEFORE M4 ingestion goes live. If this fails
    (score ~= 0.0 = distance), the server-side `score >= 0.92` pre-filter is
    inverted — fix VECTOR_DUP_QUERY before enabling ingestion. The Python
    `resolve_l3_duplicate` gate still prevents false merges either way.
    """
    pytest.importorskip("falkordb")
    repo = m.FalkorGraphRAGRepository()
    repo.ensure_indexes_and_constraints()
    now_ts = 1_790_000_000
    vec = [0.5, 0.25, -0.125] + [0.0] * (settings.embedding_dimension - 3)
    canon_id = "LIVE_CALIB_CANON"
    repo.merge_news_event(
        {
            "id": canon_id,
            "ticker": "LIVE_CALIB",
            "headline": "calibration probe",
            "norm_headline": "calibration probe",
            "event_ts": now_ts,
            "event_date": "2026-10-18",
        },
        embedding=vec,
    )
    try:
        hit = repo.find_near_dup(vec, "LIVE_CALIB", now_ts)
        assert hit is not None, "identical vector not returned — check index/score orientation"
        _node, score = hit[0], hit[1]
        assert score == pytest.approx(1.0, abs=0.05), f"expected similarity ~1.0, got {score}"
    finally:
        repo._run("MATCH (n:NewsEvent {ticker: $t}) DETACH DELETE n", {"t": "LIVE_CALIB"})
