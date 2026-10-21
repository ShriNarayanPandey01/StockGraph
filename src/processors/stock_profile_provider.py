"""Assemble StockContextCard from seed profile + live graph state (docs/01 Flow A).

In Milestone 2 no quarterly/guidance nodes exist yet, so snapshot/guidance
fields degrade gracefully to None/empty. M5 backfills them with zero rework
for M3/M4 LLM consumers (DynamicOntologyBuilder, NewsGraphExtractor).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.domain.schemas import StockContextCard
from src.processors.entity_resolver import DEFAULT_SEED_PATH


def load_stock_profile(ticker: str, seed_path: str | Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    with open(seed_path, encoding="utf-8") as fh:
        seed = yaml.safe_load(fh)
    for stock in seed.get("stocks", []):
        if stock.get("ticker") == ticker.upper():
            return stock
    raise KeyError(f"Unknown ticker {ticker!r}: not in ontology_seed.yaml registry")


class StockProfileProvider:
    """Build LLM-ready context cards. `repo` is optional in M2 (active
    exposures + snapshot/guidance backfilled once those writers exist)."""

    def __init__(self, repo: Any | None = None, seed_path: str | Path = DEFAULT_SEED_PATH) -> None:
        self._repo = repo
        self._seed_path = seed_path

    def build_context_card(self, ticker: str) -> StockContextCard:
        profile = load_stock_profile(ticker, self._seed_path)
        active_exposures: list[str] = list(profile.get("exposures", []))
        active_exposures += list(profile.get("macro_exposures", []))
        if profile.get("sector"):
            active_exposures.append(profile["sector"])
        latest_quarter_summary: str | None = None
        latest_guidance_highlights: list[str] = []
        if self._repo is not None:
            try:
                exposures = self._repo.get_active_exposures(ticker.upper())
                if exposures:
                    active_exposures = exposures
            except AttributeError:
                pass  # M2 repo has no exposure reader yet; seed fallback stands.
            try:
                latest = self._repo.get_latest_quarterly_snapshot(ticker.upper())
                if latest:
                    fields = (
                        ("quarter", "quarter"),
                        ("rev_yoy_pct", "revenue YoY %"),
                        ("ebitda_margin_pct", "EBITDA margin %"),
                        ("pat_cr", "PAT Rs cr"),
                        ("debt_to_equity", "debt/equity"),
                        ("fcf_cr", "FCF Rs cr"),
                        ("promoter_pledge_pct", "promoter pledge %"),
                    )
                    latest_quarter_summary = "; ".join(
                        f"{label}: {latest[key]}" for key, label in fields
                        if latest.get(key) is not None
                    ) or None
            except AttributeError:
                pass
            try:
                latest_guidance_highlights = self._repo.get_latest_guidance_highlights(ticker.upper())
            except AttributeError:
                pass
        return StockContextCard(
            ticker=ticker.upper(),
            business_summary=profile.get("business_summary"),
            revenue_segments=list(profile.get("revenue_segments", [])),
            raw_material_inputs=list(profile.get("raw_material_inputs", [])),
            geographic_exposure=profile.get("geographic_exposure"),
            latest_quarter_summary=latest_quarter_summary,
            latest_guidance_highlights=latest_guidance_highlights,
            active_exposures=active_exposures,
        )
