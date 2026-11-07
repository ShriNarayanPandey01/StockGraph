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
    _stocks_by_key: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _tickers: set[str] = field(default_factory=set, init=False, repr=False)
    _isins: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _stock_names: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _registry_by_key: dict[str, ResolvedRegistry] = field(default_factory=dict, init=False, repr=False)
    _registry_labels: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _commodities: set[str] = field(default_factory=set, init=False, repr=False)
    _macros: set[str] = field(default_factory=set, init=False, repr=False)
    _sectors: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def from_catalog(cls, catalog: dict[str, list[dict]]) -> "CanonicalEntityResolver":
        resolver = cls()
        for stock in catalog.get("Stock", []):
            ticker = stock["ticker"]
            resolver._tickers.add(ticker)
            resolver._stock_names[ticker] = stock.get("name") or ticker
            if stock.get("isin"):
                resolver._isins[stock["isin"].upper()] = ticker
            for alias in [ticker, stock.get("name", ""), *stock.get("aliases", [])]:
                if alias:
                    resolver._stocks_by_key.setdefault(normalize(alias), ticker)
        for label, kind, bucket in (
            ("Commodity", "commodity", resolver._commodities),
            ("MacroFactor", "macro", resolver._macros),
            ("Sector", "sector", resolver._sectors),
        ):
            for entity in catalog.get(label, []):
                entity_id = entity["id"]
                bucket.add(entity_id)
                resolver._registry_labels[entity_id] = entity.get("name") or entity_id
                for alias in [entity_id, entity.get("name", ""), *entity.get("aliases", [])]:
                    if alias:
                        resolver._registry_by_key.setdefault(
                            normalize(alias), ResolvedRegistry(kind, entity_id)
                        )
        return resolver

    def resolve_stock(self, text: str) -> str | None:
        raw = strip_exchange_suffix(text or "")
        return self._isins.get(raw.upper()) or self._stocks_by_key.get(normalize(raw))

    def resolve_registry(self, text: str) -> ResolvedRegistry | None:
        return self._registry_by_key.get(normalize(text or ""))

    def resolve_any(self, text: str) -> str | None:
        stock = self.resolve_stock(text)
        registry = self.resolve_registry(text)
        return stock or (registry.id if registry else None)

    def list_stocks(self) -> list[str]:
        return sorted(self._tickers)

    def list_stock_names(self) -> dict[str, str]:
        return dict(self._stock_names)

    def stock_aliases(self) -> tuple[tuple[str, str], ...]:
        """Return a snapshot so callers cannot mutate the identity index."""
        return tuple(self._stocks_by_key.items())

    def all_entity_ids(self) -> list[str]:
        return sorted(self._commodities | self._macros | self._sectors | self._tickers)

    def registry_catalog(self) -> list[dict[str, str]]:
        return [
            {"kind": kind, "id": entity_id, "label": self._registry_labels[entity_id]}
            for kind, ids in (
                ("commodity", self._commodities),
                ("macro", self._macros),
                ("sector", self._sectors),
            )
            for entity_id in sorted(ids)
        ]
