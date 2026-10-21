"""Milestone 2: CanonicalEntityResolver (Rule 4). No live DB required."""

import pytest

from src.processors.entity_resolver import CanonicalEntityResolver, normalize


@pytest.fixture(scope="module")
def resolver() -> CanonicalEntityResolver:
    return CanonicalEntityResolver.from_seed()


def test_normalize_strips_noise():
    assert normalize("Tata-Steel Ltd.") == "tata steel ltd"


def test_resolve_stock_ticker_alias_isin(resolver):
    assert resolver.resolve_stock("TATASTEEL") == "TATASTEEL"
    assert resolver.resolve_stock("tatasteel") == "TATASTEEL"
    assert resolver.resolve_stock("Reliance") == "RELIANCE"
    assert resolver.resolve_stock("RIL") == "RELIANCE"
    assert resolver.resolve_stock("INE002A01018") == "RELIANCE"
    assert resolver.resolve_stock("Unknown Corp XYZ") is None
    assert resolver.resolve_stock("") is None


def test_resolve_registry_commodity_macro_sector(resolver):
    hit = resolver.resolve_registry("coking coal")
    assert hit is not None and (hit.kind, hit.id) == ("commodity", "COKING_COAL")
    hit = resolver.resolve_registry("repo rate")
    assert hit is not None and (hit.kind, hit.id) == ("macro", "RBI_REPO_RATE")
    hit = resolver.resolve_registry("banking")
    assert hit is not None and (hit.kind, hit.id) == ("sector", "BANKING")


def test_forex_strings_resolve_to_macro_not_currency(resolver):
    for text in ["USD/INR", "dollar", "rupee depreciation", "forex", "currency movement"]:
        hit = resolver.resolve_registry(text)
        assert hit is not None, text
        assert (hit.kind, hit.id) == ("macro", "USD_INR_FX"), text
    assert "USD_INR_FX" in resolver.list_macros()


def test_resolve_any_unknown_returns_none(resolver):
    assert resolver.resolve_any("Tata Steel") == "TATASTEEL"
    assert resolver.resolve_any("brent") == "BRENT_CRUDE"
    assert resolver.resolve_any("not a real entity 123") is None


def test_catalog_lists_cover_seed(resolver):
    assert {"TATASTEEL", "RELIANCE", "INFY"} <= set(resolver.list_stocks())
    assert {"BRENT_CRUDE", "HRC_STEEL", "COKING_COAL"} <= set(resolver.list_commodities())
    for mid in (
        "RBI_REPO_RATE",
        "INDIA_CPI",
        "INDIA_GDP_GROWTH",
        "USD_INR_FX",
        "INDIA_10Y_YIELD",
        "US_FED_RATE",
        "GOVT_CAPEX_SPEND",
    ):
        assert mid in resolver.list_macros()
