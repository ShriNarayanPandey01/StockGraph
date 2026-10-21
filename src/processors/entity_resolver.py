"""Canonical entity resolution (Rule 4 gatekeeper).

Every LLM/scraper-produced entity string MUST pass through
`CanonicalEntityResolver` before any graph write. Unknown strings resolve to
`None` and the caller drops them — the resolver NEVER invents node IDs.

Registry IDs live in `src/config/ontology_seed.yaml` (Rule 4). There is NO
`:Currency` node type: USD/INR forex resolves to the `USD_INR_FX` macro
factor. Pure Python, no DB/LLM calls — fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_SEED_PATH = Path("src/config/ontology_seed.yaml")

RegistryKind = Literal["commodity", "macro", "sector"]

_FOREX_HINTS = re.compile(r"(usd|inr|dollar|rupee|forex|currenc|exchange rate|usd/?inr)")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/extra whitespace for alias matching."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class ResolvedRegistry:
    kind: RegistryKind
    id: str


@dataclass
class CanonicalEntityResolver:
    """In-memory alias -> canonical-ID maps built once from the YAML registry."""

    stocks_by_key: dict[str, str] = field(default_factory=dict)  # norm key -> ticker
    tickers: set[str] = field(default_factory=set)
    isins: dict[str, str] = field(default_factory=dict)  # upper ISIN -> ticker
    registry_by_key: dict[str, ResolvedRegistry] = field(default_factory=dict)
    commodities: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    sectors: set[str] = field(default_factory=set)

    @classmethod
    def from_seed(cls, seed_path: str | Path = DEFAULT_SEED_PATH) -> CanonicalEntityResolver:
        with open(seed_path, encoding="utf-8") as fh:
            seed = yaml.safe_load(fh)
        inst = cls()
        for stock in seed.get("stocks", []):
            ticker = stock["ticker"]
            inst.tickers.add(ticker)
            inst.stocks_by_key[normalize(ticker)] = ticker
            if stock.get("isin"):
                inst.isins[str(stock["isin"]).upper()] = ticker
            for alias in [stock.get("name", ""), *stock.get("aliases", [])]:
                if alias and normalize(alias) not in inst.stocks_by_key:
                    inst.stocks_by_key[normalize(alias)] = ticker
        for section, kind in (
            ("commodities", "commodity"),
            ("macro_factors", "macro"),
            ("sectors", "sector"),
        ):
            for entry in seed.get(section, []):
                rid = entry["id"]
                getattr(inst, kind + "s" if kind != "commodity" else "commodities").add(rid)
                inst.registry_by_key.setdefault(normalize(rid), ResolvedRegistry(kind, rid))  # type: ignore[arg-type]
                for alias in [entry.get("name", ""), *entry.get("aliases", [])]:
                    if alias and normalize(alias) not in inst.registry_by_key:
                        inst.registry_by_key[normalize(alias)] = ResolvedRegistry(kind, rid)  # type: ignore[arg-type]
        return inst

    def resolve_stock(self, text: str) -> str | None:
        """Resolve to an NSE ticker via ticker/ISIN/alias. None if unknown."""
        if not text or not text.strip():
            return None
        raw = text.strip()
        if raw.upper() in self.tickers:
            return raw.upper()
        if raw.upper() in self.isins:
            return self.isins[raw.upper()]
        return self.stocks_by_key.get(normalize(raw))

    def resolve_registry(self, text: str) -> ResolvedRegistry | None:
        """Resolve to a (kind, id) registry entry. None if unknown.

        Forex-flavoured strings that miss the alias map still land on the
        USD_INR_FX macro factor (there is no :Currency node type).
        """
        if not text or not text.strip():
            return None
        hit = self.registry_by_key.get(normalize(text))
        if hit is not None:
            return hit
        if _FOREX_HINTS.search(text.lower()) and "USD_INR_FX" in self.macros:
            return ResolvedRegistry("macro", "USD_INR_FX")
        return None

    def resolve_any(self, text: str) -> str | None:
        """Ticker first, else registry id. None if unresolvable (drop)."""
        ticker = self.resolve_stock(text)
        if ticker is not None:
            return ticker
        reg = self.resolve_registry(text)
        return reg.id if reg is not None else None

    def list_stocks(self) -> list[str]:
        return sorted(self.tickers)

    def list_commodities(self) -> list[str]:
        return sorted(self.commodities)

    def list_macros(self) -> list[str]:
        return sorted(self.macros)

    def list_sectors(self) -> list[str]:
        return sorted(self.sectors)
