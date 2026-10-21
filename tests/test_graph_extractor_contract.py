"""NewsGraphExtractor contract: context injection, gating, structured I/O."""

from src.config.settings import settings
from src.domain.schemas import InferredNewsStockImpact, StockContextCard
from src.processors.entity_resolver import CanonicalEntityResolver
from src.processors.news_graph_extractor import (
    NewsGraphExtractor,
    NewsImpactBatch,
    build_routing_prompt,
    render_card,
)


def _card() -> StockContextCard:
    return StockContextCard(
        ticker="TATASTEEL",
        business_summary="Integrated steelmaker",
        revenue_segments=["Steel"],
        raw_material_inputs=["Coking coal"],
        geographic_exposure="India",
        latest_quarter_summary="Q2 margin 18%",
        latest_guidance_highlights=["Demand strong"],
        active_exposures=["COKING_COAL"],
    )


class _StubChat:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.payload


class _FakeRepo:
    def __init__(self):
        self.impacts: list[tuple] = []
        self.shocks: list[tuple] = []

    def merge_stock_impact(self, *args):
        self.impacts.append(args)
        return {}

    def merge_news_shock(self, *args):
        self.shocks.append(args)
        return {}


def _ext(payload):
    return NewsGraphExtractor(_StubChat(payload), CanonicalEntityResolver.from_seed())


def _imp(**kw):
    base = {
        "news_id": "n1",
        "ticker": "TATASTEEL",
        "impact_type": "DIRECTLY_IMPACTS",
        "confidence": 0.9,
        "rationale": "Names the company",
    }
    base.update(kw)
    return InferredNewsStockImpact(**base)


def test_prompt_injects_full_context_card():
    prompt = build_routing_prompt("Steel up", "Prices rise", [_card()])
    for needle in (
        "Integrated steelmaker",
        "Coking coal",
        "Q2 margin 18%",
        "Demand strong",
        "COKING_COAL",
        "TATASTEEL",
    ):
        assert needle in prompt


def test_render_card_degrades_gracefully():
    text = render_card(StockContextCard(ticker="INFY"))
    assert "TICKER: INFY" in text and "n/a" in text


def test_infer_gates_unknown_ticker_and_low_confidence():
    batch = NewsImpactBatch(
        impacts=[
            _imp(ticker="TATASTEEL", confidence=0.9),
            _imp(ticker="FAKECORP", confidence=0.95),
            _imp(ticker="RELIANCE", confidence=0.10),
            _imp(ticker="INFY", impact_type="BOGUS", confidence=0.9),
        ]
    )
    out = _ext(batch).infer("n1", "h", "s", [_card()])
    assert [i.ticker for i in out] == ["TATASTEEL"]


def test_infer_resolves_alias_and_forex_shock():
    batch = NewsImpactBatch(
        impacts=[_imp(ticker="Tata Steel", shocked_entity_id="dollar", confidence=0.8)]
    )
    out = _ext(batch).infer("n1", "h", "s", [_card()])
    assert len(out) == 1
    assert out[0].ticker == "TATASTEEL"
    assert out[0].shocked_entity_id == "USD_INR_FX"


def test_infer_drops_unresolvable_shock():
    batch = NewsImpactBatch(impacts=[_imp(shocked_entity_id="not-a-real-thing")])
    assert _ext(batch).infer("n1", "h", "s", [_card()]) == []


def test_infer_rejects_raw_text_output():
    ext = _ext("just some prose, not JSON")
    assert ext.infer("n1", "h", "s", [_card()]) == []


def test_infer_rejects_invalid_schema_dict():
    ext = _ext({"impacts": [{"ticker": "TATASTEEL"}]})
    assert ext.infer("n1", "h", "s", [_card()]) == []


def test_infer_empty_cards_skips_llm():
    chat = _StubChat(NewsImpactBatch(impacts=[]))
    assert (
        NewsGraphExtractor(chat, CanonicalEntityResolver.from_seed()).infer("n1", "h", "s", [])
        == []
    )
    assert chat.prompts == []


def test_confidence_floor_from_settings():
    assert settings.ontology_min_confidence == 0.65
    ext = _ext(NewsImpactBatch(impacts=[]))
    assert ext.min_confidence == 0.65


def test_persist_writes_impact_plus_shock():
    repo = _FakeRepo()
    ext = _ext(NewsImpactBatch(impacts=[]))
    n = ext.persist(repo, [_imp(shocked_entity_id="COKING_COAL")])
    assert n == 2
    assert len(repo.impacts) == 1 and len(repo.shocks) == 1
    assert repo.shocks[0][1] == "commodity"
    assert repo.shocks[0][2] == "COKING_COAL"


def test_impact_query_shapes_use_merge_and_causal_rationale():
    from src.repositories import falkor_repo as m

    for q in (
        m.MERGE_STOCK_DIRECT_IMPACT_QUERY,
        m.MERGE_STOCK_INDIRECT_IMPACT_QUERY,
        m.MERGE_NEWS_SHOCKS_COMMODITY_QUERY,
        m.MERGE_NEWS_ALTERS_MACRO_QUERY,
        m.MERGE_NEWS_IMPACTS_SECTOR_QUERY,
        m.MERGE_NEWS_CORRELATION_QUERY,
    ):
        assert q.strip().startswith("MATCH")
        assert "MERGE (n)-[r:" in q
        assert "CREATE (n:" not in q
    assert "DIRECTLY_IMPACTS" in m.MERGE_STOCK_DIRECT_IMPACT_QUERY
    assert "causal_rationale" in m.MERGE_STOCK_DIRECT_IMPACT_QUERY
    assert "SHOCKS" in m.MERGE_NEWS_SHOCKS_COMMODITY_QUERY
    assert "CORRELATED_WITH" in m.MERGE_NEWS_CORRELATION_QUERY
    assert "correlation_type" in m.MERGE_NEWS_CORRELATION_QUERY
