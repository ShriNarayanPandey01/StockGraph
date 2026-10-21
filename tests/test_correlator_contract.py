"""L4 correlator contract: paraphrase band, gating, candidate query shape."""

from src.config.settings import settings
from src.domain.enums import CorrelationType
from src.domain.schemas import InferredNewsCorrelation
from src.processors.news_correlator import (
    NewsCorrelationBatch,
    NewsCorrelator,
    build_correlation_prompt,
    in_paraphrase_band,
)


class _StubChat:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.payload


class _FakeRepo:
    def __init__(self, candidates):
        self.candidates = candidates
        self.links: list[tuple] = []

    def find_correlation_candidates(self, news_id, now_ts):
        return self.candidates

    def merge_news_correlation(self, *args):
        self.links.append(args)
        return {}


def _verdict(**kw):
    base = {
        "new_news_id": "n2",
        "prior_news_id": "n1",
        "correlation_type": CorrelationType.FOLLOW_UP,
        "confidence": 0.85,
        "rationale": "Same story, new filing",
        "event_ts": 1_790_000_000,
    }
    base.update(kw)
    return InferredNewsCorrelation(**base)


def _cand(cid="n1"):
    return {"id": cid, "headline": "RBI holds rate", "summary": "s", "event_ts": 1_789_000_000}


def test_paraphrase_band_bounds():
    assert in_paraphrase_band(0.68) is True
    assert in_paraphrase_band(0.80) is True
    assert in_paraphrase_band(0.92) is False  # dup band -> DUPLICATE_OF, not here
    assert in_paraphrase_band(0.50) is False
    assert settings.correlation_min_cosine == 0.68
    assert settings.correlation_window_days == 14


def test_prompt_lists_candidates_and_valid_types():
    prompt = build_correlation_prompt("New hike", "summary", [_cand("n1"), _cand("n0")])
    assert "n1" in prompt and "n0" in prompt
    for t in ("CAUSAL_CHAIN", "MACRO_CONTAGION", "SECTOR_RIPPLE", "FOLLOW_UP"):
        assert t in prompt


def test_correlate_persists_gated_verdicts():
    repo = _FakeRepo([_cand("n1")])
    corr = NewsCorrelator(_StubChat(NewsCorrelationBatch(correlations=[_verdict()])))
    out = corr.correlate(repo, "n2", "h", "s", 1_790_000_000, 1_790_000_000)
    assert len(out) == 1 and out[0].prior_news_id == "n1"
    assert repo.links and repo.links[0][2] == "FOLLOW_UP"


def test_correlate_drops_low_confidence_and_self_links():
    repo = _FakeRepo([_cand("n1")])
    batch = NewsCorrelationBatch(
        correlations=[
            _verdict(prior_news_id="n1", confidence=0.10),
            _verdict(prior_news_id="n2", confidence=0.90),
        ]
    )
    out = NewsCorrelator(_StubChat(batch)).correlate(
        repo, "n2", "h", "s", 1_790_000_000, 1_790_000_000
    )
    assert out == [] and repo.links == []


def test_correlate_rejects_raw_text_and_skips_empty_candidates():
    repo = _FakeRepo([_cand("n1")])
    corr = NewsCorrelator(_StubChat("prose, not JSON"))
    assert corr.correlate(repo, "n2", "h", "s", 1_790_000_000, 1_790_000_000) == []
    empty = NewsCorrelator(_StubChat(NewsCorrelationBatch(correlations=[_verdict()])))
    assert empty.correlate(_FakeRepo([]), "n2", "h", "s", 1_790_000_000, 1) == []


def test_candidate_query_shape():
    from src.repositories import falkor_repo as m

    q = m.CORRELATION_CANDIDATES_QUERY
    assert "CORRELATED_WITH" not in q  # candidates share entities, not prior links
    assert "DUPLICATE_OF" in q  # canonical-only, both sides
    assert "$window_secs" in q and "LIMIT {limit}" in q
    assert "p.id <> $news_id" in q
    rendered = m._render_section_query(q, 50)
    assert "LIMIT 50" in rendered
