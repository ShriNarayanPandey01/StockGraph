"""FalkorDB query-shape assertions (Rule 2/3/5). No live DB required."""

import pytest

from src.repositories import falkor_repo as m


def test_section_queries_exclude_duplicates_and_use_literal_limit():
    for q in (
        m.DIRECT_NEWS_QUERY,
        m.INDIRECT_NEWS_QUERY,
        m.DEALS_QUERY,
        m.MF_HOLDINGS_QUERY,
        m.QUARTERLY_QUERY,
        m.GUIDANCE_QUERY,
    ):
        # FalkorDB's parser rejects `LIMIT $param`: only a literal int is valid.
        assert "LIMIT {limit}" in q
        assert "$limit" not in q
    assert "[:DUPLICATE_OF]" in m.DIRECT_NEWS_QUERY
    assert "NOT (" in m.DIRECT_NEWS_QUERY
    assert "[:DUPLICATE_OF]" in m.INDIRECT_NEWS_QUERY
    assert "NOT (" in m.INDIRECT_NEWS_QUERY


def test_section_limit_is_clamped_and_rendered_as_literal():
    for q in (m.DIRECT_NEWS_QUERY, m.GUIDANCE_QUERY):
        assert "LIMIT 50" in m._render_section_query(q, 50)
        assert "{limit}" not in m._render_section_query(q, 50)
        assert "LIMIT 200" in m._render_section_query(q, 10_000)
        assert "LIMIT 1" in m._render_section_query(q, 0)
        assert "LIMIT 1" in m._render_section_query(q, -3)
    with pytest.raises(TypeError):
        m._render_section_query(m.DIRECT_NEWS_QUERY, "10")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        m._render_section_query(m.DIRECT_NEWS_QUERY, True)


def test_indirect_news_uses_relationship_type_function():
    # A relationship's type is graph structure, not a property: `exp.type`
    # reads a (absent) property and yields null. `type(exp)` yields
    # EXPOSED_TO / BELONGS_TO / SENSITIVE_TO_MACRO.
    assert "type(exp) AS exposure_type" in m.INDIRECT_NEWS_QUERY
    assert "exp.type AS exposure_type" not in m.INDIRECT_NEWS_QUERY


def test_rotate_queries_project_scalar_business_ids():
    # Whole-node RETURNs deserialize into SDK Node objects; Node.id is the
    # internal graph id and there is no dict access. Project `id` instead.
    assert "RETURN old.id AS old_id" in m.ROTATE_CLOSE_OLD_QUERY
    assert "RETURN new_q.id AS new_id" in m.ROTATE_CREATE_NEW_QUERY
    assert "RETURN new_q.id AS new_id" in m.ROTATE_LINK_SUPERSEDES_QUERY


def test_rotate_returns_business_ids_and_links_supersedes(monkeypatch):
    repo = m.FalkorGraphRAGRepository()
    calls: list[tuple[str, dict]] = []
    responses = iter(
        [[["RELIANCE_2025Q2"]], [["RELIANCE_2025Q3"]], [["RELIANCE_2025Q3"]]]
    )

    def fake_run(query: str, params: dict) -> list:
        calls.append((query, params))
        return next(responses)

    monkeypatch.setattr(repo, "_run", fake_run)
    out = repo.rotate_validity_interval_node(
        "RELIANCE", 1_700_000_000, {"id": "RELIANCE_2025Q3"}
    )
    assert out == {"new_id": "RELIANCE_2025Q3", "old_id": "RELIANCE_2025Q2"}
    assert len(calls) == 3
    assert calls[0] == (
        m.ROTATE_CLOSE_OLD_QUERY,
        {"ticker": "RELIANCE", "new_ts": 1_700_000_000},
    )
    assert calls[2] == (
        m.ROTATE_LINK_SUPERSEDES_QUERY,
        {"new_id": "RELIANCE_2025Q3", "old_id": "RELIANCE_2025Q2"},
    )


def test_rotate_first_quarter_skips_supersedes_link(monkeypatch):
    repo = m.FalkorGraphRAGRepository()
    calls: list[tuple[str, dict]] = []
    # Close matches nothing (first quarter); create returns the new id.
    responses = iter([[], [["RELIANCE_2025Q3"]]])

    def fake_run(query: str, params: dict) -> list:
        calls.append((query, params))
        return next(responses)

    monkeypatch.setattr(repo, "_run", fake_run)
    out = repo.rotate_validity_interval_node("RELIANCE", 1, {"id": "RELIANCE_2025Q3"})
    assert out == {"new_id": "RELIANCE_2025Q3", "old_id": None}
    assert len(calls) == 2


def test_rotate_logs_error_when_new_snapshot_is_missing(monkeypatch):
    repo = m.FalkorGraphRAGRepository()
    responses = iter([[["RELIANCE_2025Q2"]], []])

    def fake_run(query: str, params: dict) -> list:
        return next(responses)

    monkeypatch.setattr(repo, "_run", fake_run)
    out = repo.rotate_validity_interval_node("RELIANCE", 1, {"id": "RELIANCE_2025Q3"})
    assert out == {"new_id": None, "old_id": "RELIANCE_2025Q2"}


def test_no_anomaly_branch_and_no_foreach():
    all_queries = "\n".join(
        [
            m.DIRECT_NEWS_QUERY,
            m.INDIRECT_NEWS_QUERY,
            m.DEALS_QUERY,
            m.MF_HOLDINGS_QUERY,
            m.QUARTERLY_QUERY,
            m.GUIDANCE_QUERY,
            m.ROTATE_CLOSE_OLD_QUERY,
            m.ROTATE_CREATE_NEW_QUERY,
            m.ROTATE_LINK_SUPERSEDES_QUERY,
        ]
    )
    assert "DailyAnomalyEvent" not in all_queries
    assert "TRIGGERED_ANOMALY" not in all_queries
    assert "FOREACH" not in all_queries
    assert "SUPERSEDES" in m.ROTATE_LINK_SUPERSEDES_QUERY


def test_window_predicates_present():
    assert "$start_ts" in m.DIRECT_NEWS_QUERY and "$end_ts" in m.DIRECT_NEWS_QUERY
    assert "valid_from_ts <= $end_ts" in m.QUARTERLY_QUERY
    assert "valid_to_ts >= $start_ts" in m.MF_HOLDINGS_QUERY


def test_vector_syntax_uses_vecf32():
    assert "vecf32($embedding)" in m.VECTOR_DUP_QUERY
    assert "vecf32($embedding)" in m.MERGE_NEWS_QUERY
