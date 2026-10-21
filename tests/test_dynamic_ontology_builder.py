"""DynamicOntologyBuilder contract & entity-gating tests (Rule 4)."""

import pytest
from src.config.settings import settings
from src.domain.enums import OntologyRelationType
from src.domain.schemas import InferredOntologyEdge, StockContextCard
from src.processors.dynamic_ontology_builder import (
    DynamicOntologyBuilder,
    OntologyEdgeBatch,
    build_ontology_prompt,
)
from src.processors.entity_resolver import CanonicalEntityResolver


def _card() -> StockContextCard:
    return StockContextCard(
        ticker="TATASTEEL",
        business_summary="Integrated steel manufacturer",
        revenue_segments=["Flat steel", "Long steel"],
        raw_material_inputs=["Coking coal", "Iron ore"],
        geographic_exposure="India, Europe",
        latest_quarter_summary="Margins compressed due to coal prices",
        latest_guidance_highlights=["Capex ongoing at Kalinganagar"],
        active_exposures=["COKING_COAL"],
    )


class _StubChat:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.payload


class _FakeFalkor:
    def __init__(self):
        self.edges = []

    def merge_ontology_edge(self, **kw):
        self.edges.append(kw)
        return {"rel": kw.get("relation")}

    def get_active_exposures(self, ticker):
        return ["COKING_COAL", "METALS"]


def test_ontology_prompt_injects_full_card():
    resolver = CanonicalEntityResolver.from_seed()
    available = list(resolver.commodities | resolver.macros | resolver.sectors)
    prompt = build_ontology_prompt(_card(), available)

    assert "Integrated steel manufacturer" in prompt
    assert "Flat steel" in prompt
    assert "Coking coal" in prompt
    assert "COKING_COAL" in prompt
    assert "USD_INR_FX" in prompt
    assert "TATASTEEL" in prompt


def test_infer_edges_gates_confidence_and_unknown_entities():
    resolver = CanonicalEntityResolver.from_seed()
    batch = OntologyEdgeBatch(
        edges=[
            # Valid commodity exposure
            InferredOntologyEdge(
                source_id="TATASTEEL",
                relation=OntologyRelationType.EXPOSED_TO,
                target_id="COKING_COAL",
                confidence=0.90,
                rationale="Essential raw material",
            ),
            # Low confidence -> must be dropped
            InferredOntologyEdge(
                source_id="TATASTEEL",
                relation=OntologyRelationType.EXPOSED_TO,
                target_id="HRC_STEEL",
                confidence=0.40,
                rationale="Output product",
            ),
            # Unknown entity -> must be dropped
            InferredOntologyEdge(
                source_id="TATASTEEL",
                relation=OntologyRelationType.EXPOSED_TO,
                target_id="UNOBTANIUM",
                confidence=0.95,
                rationale="Fictional",
            ),
            # Valid macro sensitivity (forex resolved to USD_INR_FX)
            InferredOntologyEdge(
                source_id="TATASTEEL",
                relation=OntologyRelationType.SENSITIVE_TO_MACRO,
                target_id="dollar",
                confidence=0.85,
                rationale="Exports and raw material import in USD",
            ),
            # Valid peer stock competitor
            InferredOntologyEdge(
                source_id="TATASTEEL",
                relation=OntologyRelationType.COMPETES_WITH,
                target_id="JSW Steel",
                confidence=0.88,
                rationale="Direct Indian steel competitor",
            ),
            # Valid commodity-to-commodity inter-link
            InferredOntologyEdge(
                source_id="COKING_COAL",
                relation=OntologyRelationType.RELATED_TO,
                target_id="HRC_STEEL",
                confidence=0.85,
                rationale="Coking coal is direct input to steel production",
            ),
        ]
    )

    builder = DynamicOntologyBuilder(_StubChat(batch), resolver)
    out = builder.infer_edges(_card(), now_ts=1780000000)

    # 4 valid edges kept
    assert len(out) == 4
    by_rel = {e.relation.value: e for e in out}

    assert "EXPOSED_TO" in by_rel
    assert by_rel["EXPOSED_TO"].target_id == "COKING_COAL"

    assert "SENSITIVE_TO_MACRO" in by_rel
    assert by_rel["SENSITIVE_TO_MACRO"].target_id == "USD_INR_FX"

    assert "COMPETES_WITH" in by_rel
    assert by_rel["COMPETES_WITH"].target_id == "JSWSTEEL"

    assert "RELATED_TO" in by_rel
    assert by_rel["RELATED_TO"].source_id == "COKING_COAL"
    assert by_rel["RELATED_TO"].target_id == "HRC_STEEL"


def test_persist_writes_ontology_edges():
    resolver = CanonicalEntityResolver.from_seed()
    edge = InferredOntologyEdge(
        source_id="TATASTEEL",
        relation=OntologyRelationType.EXPOSED_TO,
        target_id="COKING_COAL",
        confidence=0.92,
        rationale="Raw material",
        valid_from_ts=1780000000,
    )

    repo = _FakeFalkor()
    builder = DynamicOntologyBuilder(_StubChat(None), resolver)
    count = builder.persist(repo, [edge])

    assert count == 1
    assert len(repo.edges) == 1
    assert repo.edges[0]["source_id"] == "TATASTEEL"
    assert repo.edges[0]["relation"] == "EXPOSED_TO"
    assert repo.edges[0]["target_id"] == "COKING_COAL"


def test_get_active_exposures():
    repo = _FakeFalkor()
    exposures = repo.get_active_exposures("TATASTEEL")
    assert "COKING_COAL" in exposures
    assert "METALS" in exposures
