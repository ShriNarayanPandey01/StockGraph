"""Milestone 2: ontology seeder (fake repo, no live DB) + profile provider."""

import pytest

from src.processors.stock_profile_provider import StockProfileProvider, load_stock_profile
from src.repositories import ontology_seeder as seeder


class FakeRepo:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.indexed = False

    def ensure_indexes_and_constraints(self):
        self.indexed = True
        return []

    def _run(self, query: str, params: dict):
        self.calls.append((query, params))
        return [["x"]]


def _queries(repo: FakeRepo) -> str:
    return "\n".join(q for q, _ in repo.calls)


def test_seed_counts_and_broad_baseline():
    repo = FakeRepo()
    counts = seeder.seed_ontology(repo, "src/config/ontology_seed.yaml")
    assert repo.indexed
    assert counts == {"sectors": 4, "commodities": 3, "macros": 7, "stocks": 3, "edges": 28}
    joined = _queries(repo)
    # BELONGS_TO per stock, RELATED_TO both directions, BROAD macros everywhere.
    assert joined.count("BELONGS_TO") == 3
    assert "RELATED_TO" in joined
    rel_calls = [p for q, p in repo.calls if "RELATED_TO" in q]
    assert {(p["source_id"], p["target_id"]) for p in rel_calls} == {
        ("HRC_STEEL", "COKING_COAL"),
        ("COKING_COAL", "HRC_STEEL"),
    }
    macro_calls = [p for q, p in repo.calls if "SENSITIVE_TO_MACRO" in q]
    by_ticker: dict[str, set[str]] = {}
    for p in macro_calls:
        by_ticker.setdefault(p["ticker"], set()).add(p["target_id"])
    broad = {"RBI_REPO_RATE", "INDIA_CPI", "INDIA_GDP_GROWTH", "INDIA_10Y_YIELD", "US_FED_RATE", "GOVT_CAPEX_SPEND"}
    for ticker in ("TATASTEEL", "RELIANCE", "INFY"):
        assert broad <= by_ticker[ticker], ticker
    assert "USD_INR_FX" in by_ticker["INFY"] and "USD_INR_FX" in by_ticker["RELIANCE"]
    assert "USD_INR_FX" not in by_ticker["TATASTEEL"]
    assert "Currency" not in joined
    for _, params in repo.calls:
        edge = params.get("edge")
        if edge:
            assert edge["confidence"] == 1.0 and edge["inferred_by"] == "seed"


def test_seed_is_idempotent_merge_only():
    repo = FakeRepo()
    seeder.seed_ontology(repo, "src/config/ontology_seed.yaml")
    joined = _queries(repo)
    assert "MERGE" in joined
    assert "CREATE (s:Stock" not in joined and "CREATE (n:" not in joined


def test_dangling_reference_fails_fast(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "commodities: []\nmacro_factors: []\nsectors: [{id: METALS}]\n"
        "stocks: [{ticker: X, sector: METALS, exposures: [NOPE]}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown id"):
        seeder.seed_ontology(FakeRepo(), bad)


def test_profile_provider_builds_card():
    card = StockProfileProvider().build_context_card("tatasteel")
    assert card.ticker == "TATASTEEL"
    assert card.business_summary and "steel" in card.business_summary.lower()
    assert "flat products" in card.revenue_segments
    assert "HRC_STEEL" in card.active_exposures and "METALS" in card.active_exposures
    assert card.latest_quarter_summary is None  # M2: no snapshot nodes yet
    with pytest.raises(KeyError):
        load_stock_profile("NOPE")
