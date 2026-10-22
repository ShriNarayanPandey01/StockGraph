"""Canonical-ID gate built from the current committed graph projection."""

import re
from dataclasses import dataclass, field
from typing import Literal


def strip_exchange_suffix(text: str) -> str:
    return re.sub(r"\.(NS|BO|NSE|BSE)$", "", text.strip(), flags=re.I)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@dataclass(frozen=True)
class ResolvedRegistry:
    kind: Literal["commodity", "macro", "sector"]
    id: str


@dataclass
class CanonicalEntityResolver:
    stocks_by_key: dict[str, str] = field(default_factory=dict)
    tickers: set[str] = field(default_factory=set)
    isins: dict[str, str] = field(default_factory=dict)
    stock_names: dict[str, str] = field(default_factory=dict)
    registry_by_key: dict[str, ResolvedRegistry] = field(default_factory=dict)
    registry_labels: dict[str, str] = field(default_factory=dict)
    commodities: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    sectors: set[str] = field(default_factory=set)

    @classmethod
    def from_catalog(cls, catalog: dict[str, list[dict]]) -> "CanonicalEntityResolver":
        resolver = cls()
        for stock in catalog.get("Stock", []):
            ticker = stock["ticker"]
            resolver.tickers.add(ticker)
            resolver.stock_names[ticker] = stock.get("name") or ticker
            if stock.get("isin"):
                resolver.isins[stock["isin"].upper()] = ticker
            for alias in [ticker, stock.get("name", ""), *stock.get("aliases", [])]:
                if alias:
                    resolver.stocks_by_key.setdefault(normalize(alias), ticker)
        for label, kind, bucket in (
            ("Commodity", "commodity", resolver.commodities),
            ("MacroFactor", "macro", resolver.macros),
            ("Sector", "sector", resolver.sectors),
        ):
            for entity in catalog.get(label, []):
                entity_id = entity["id"]
                bucket.add(entity_id)
                resolver.registry_labels[entity_id] = entity.get("name") or entity_id
                for alias in [entity_id, entity.get("name", ""), *entity.get("aliases", [])]:
                    if alias:
                        resolver.registry_by_key.setdefault(
                            normalize(alias), ResolvedRegistry(kind, entity_id)
                        )
        return resolver

    def resolve_stock(self, text: str) -> str | None:
        raw = strip_exchange_suffix(text or "")
        return self.isins.get(raw.upper()) or self.stocks_by_key.get(normalize(raw))

    def resolve_registry(self, text: str) -> ResolvedRegistry | None:
        return self.registry_by_key.get(normalize(text or ""))

    def resolve_any(self, text: str) -> str | None:
        stock = self.resolve_stock(text)
        registry = self.resolve_registry(text)
        return stock or (registry.id if registry else None)

    def list_stocks(self) -> list[str]:
        return sorted(self.tickers)

    def list_stock_names(self) -> dict[str, str]:
        return dict(self.stock_names)

    def registry_catalog(self) -> list[dict[str, str]]:
        return [
            {"kind": kind, "id": entity_id, "label": self.registry_labels[entity_id]}
            for kind, ids in (
                ("commodity", self.commodities),
                ("macro", self.macros),
                ("sector", self.sectors),
            )
            for entity_id in sorted(ids)
        ]
