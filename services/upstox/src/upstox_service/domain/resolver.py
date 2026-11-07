"""Canonical entity resolution (Rule 4 gatekeeper).

Every LLM/scraper-produced entity string MUST pass through
`CanonicalEntityResolver` before any graph write. Unknown strings resolve to
`None` and the caller drops them â€” the resolver NEVER invents node IDs.

Bootstrap registry IDs live in the data service's packaged
`resources/ontology_seed.yaml` (Rule 4). There is NO
`:Currency` node type: USD/INR forex resolves to the `USD_INR_FX` macro
factor. Pure Python, no DB/LLM calls â€” fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[1] / "resources" / "ontology_seed.yaml"

RegistryKind = Literal["commodity", "macro", "sector"]

_FOREX_HINTS = re.compile(r"(usd|inr|dollar|rupee|forex|currenc|exchange rate|usd/?inr)")

# Indian exchange suffixes used by Yahoo-style provider symbols:
# Marketaux/FMP report `RELIANCE.NS` (NSE) and `RELIANCE.BO` (BSE).
# Stripped before resolution so provider symbols reach the registry.
_EXCHANGE_SUFFIX_RE = re.compile(r"\.(NS|BO|NSE|BSE)$", re.IGNORECASE)


def strip_exchange_suffix(text: str) -> str:
    """Remove a trailing Indian exchange suffix (`TATASTEEL.NS` -> `TATASTEEL`)."""
    return _EXCHANGE_SUFFIX_RE.sub("", text.strip())


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/extra whitespace for alias matching."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class ResolvedRegistry:
    kind: RegistryKind
    id: str


@dataclass
class CanonicalEntityResolver:
    """In-memory alias -> canonical-ID maps built once from the YAML registry."""

    _stocks_by_key: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # norm key -> ticker
    _tickers: set[str] = field(default_factory=set, init=False, repr=False)
    _isins: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # upper ISIN -> ticker
    _stock_names: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # ticker -> registry name
    _registry_by_key: dict[str, ResolvedRegistry] = field(default_factory=dict, init=False, repr=False)
    _registry_labels: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # registry id -> label
    _commodities: set[str] = field(default_factory=set, init=False, repr=False)
    _macros: set[str] = field(default_factory=set, init=False, repr=False)
    _sectors: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def from_catalog(cls, rows: list[dict]) -> CanonicalEntityResolver:
        """Build routing aliases from the committed SQL catalog, never startup YAML."""
        inst = cls()
        for row in rows:
            entity = row["payload"]
            if row["kind"] == "Stock":
                ticker = entity["ticker"]
                inst._tickers.add(ticker)
                inst._stock_names[ticker] = entity.get("name", ticker)
                for alias in [ticker, entity.get("name", ""), *entity.get("aliases", [])]:
                    if alias:
                        inst._stocks_by_key.setdefault(normalize(alias), ticker)
                if entity.get("isin"):
                    inst._isins[entity["isin"].upper()] = ticker
            else:
                kind = {"Commodity": "commodity", "MacroFactor": "macro", "Sector": "sector"}[
                    row["kind"]
                ]
                rid = entity["id"]
                getattr(
                    inst, {"commodity": "_commodities", "macro": "_macros", "sector": "_sectors"}[kind]
                ).add(rid)
                for alias in [rid, entity.get("name", ""), *entity.get("aliases", [])]:
                    if alias:
                        inst._registry_by_key.setdefault(
                            normalize(alias), ResolvedRegistry(kind, rid)
                        )
                inst._registry_labels[rid] = entity.get("name", rid)
        return inst

    @classmethod
    def from_seed(cls, seed_path: str | Path = DEFAULT_SEED_PATH) -> CanonicalEntityResolver:
        with open(seed_path, encoding="utf-8") as fh:
            seed = yaml.safe_load(fh)
        inst = cls()
        for stock in seed.get("stocks", []):
            ticker = stock["ticker"]
            inst._tickers.add(ticker)
            inst._stock_names[ticker] = str(stock.get("name") or ticker)
            inst._stocks_by_key[normalize(ticker)] = ticker
            if stock.get("isin"):
                inst._isins[str(stock["isin"]).upper()] = ticker
            for alias in [stock.get("name", ""), *stock.get("aliases", [])]:
                if alias and normalize(alias) not in inst._stocks_by_key:
                    inst._stocks_by_key[normalize(alias)] = ticker
        for section, kind in (
            ("commodities", "commodity"),
            ("macro_factors", "macro"),
            ("sectors", "sector"),
        ):
            for entry in seed.get(section, []):
                rid = entry["id"]
                getattr(inst, "_" + (kind + "s" if kind != "commodity" else "commodities")).add(rid)
                inst._registry_by_key.setdefault(normalize(rid), ResolvedRegistry(kind, rid))  # type: ignore[arg-type]
                for alias in [entry.get("name", ""), *entry.get("aliases", [])]:
                    if alias and normalize(alias) not in inst._registry_by_key:
                        inst._registry_by_key[normalize(alias)] = ResolvedRegistry(kind, rid)  # type: ignore[arg-type]
                # A human label for the prompt catalog: the name plus the one
                # line that explains what moves it.
                label = str(entry.get("name") or rid)
                if kind == "macro":
                    why = str(entry.get("why_it_moves") or "").strip()
                    if why:
                        label = f"{label} - {why[:140]}"
                elif kind == "commodity" and entry.get("unit"):
                    label = f"{label} ({entry['unit']})"
                inst._registry_labels[rid] = label
        return inst

    def resolve_stock(self, text: str) -> str | None:
        """Resolve to an NSE ticker via ticker/ISIN/alias. None if unknown.

        Provider symbols carrying an Indian exchange suffix
        (`TATASTEEL.NS`, `RELIANCE.BO`) are stripped first, so a market
        data provider's symbol resolves to the same canonical ticker the
        registry uses. Unknown symbols (indices like `^NSEI`, unlisted
        names) still return None - the resolver never invents node IDs.
        """
        if not text or not text.strip():
            return None
        raw = strip_exchange_suffix(text)
        if not raw:
            return None
        if raw.upper() in self._tickers:
            return raw.upper()
        if raw.upper() in self._isins:
            return self._isins[raw.upper()]
        return self._stocks_by_key.get(normalize(raw))

    def list_stock_names(self) -> dict[str, str]:
        """Canonical ticker -> the registry's company name.

        Used to build provider search queries: a company's NAME is what a
        news article says, and it discriminates far better than its ticker.
        """
        return dict(self._stock_names)

    def resolve_registry(self, text: str) -> ResolvedRegistry | None:
        """Resolve to a (kind, id) registry entry. None if unknown.

        Forex-flavoured strings that miss the alias map still land on the
        USD_INR_FX macro factor (there is no :Currency node type).
        """
        if not text or not text.strip():
            return None
        hit = self._registry_by_key.get(normalize(text))
        if hit is not None:
            return hit
        if _FOREX_HINTS.search(text.lower()) and "USD_INR_FX" in self._macros:
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
        return sorted(self._tickers)

    def list_commodities(self) -> list[str]:
        return sorted(self._commodities)

    def list_macros(self) -> list[str]:
        return sorted(self._macros)

    def list_sectors(self) -> list[str]:
        return sorted(self._sectors)

    def registry_catalog(self) -> list[dict[str, str]]:
        """The registry the LLM is allowed to name, with human context.

        The routing prompt must list the valid IDs explicitly: a model that
        is asked for "the canonical registry ID" without seeing the catalog
        invents plausible-looking ids (`OIL_PRICE`, `SECTOR:BANKING`), and an
        invented id is dropped downstream - silently losing the edge.
        """
        catalog: list[dict[str, str]] = []
        for kind, ids in (
            ("commodity", self._commodities),
            ("macro", self._macros),
            ("sector", self._sectors),
        ):
            for rid in sorted(ids):
                label = self._registry_labels.get(rid, rid)
                catalog.append({"id": rid, "kind": kind, "label": label})
        return catalog


class SeedResolverCache:
    """A resolver that reloads when the seed file changes on disk.

    The registry is an operator-editable YAML file, and long-lived
    processes (the API server, the scheduler worker) would otherwise keep
    the registry they loaded at startup forever: a stock added to the seed
    would exist in the graph but be invisible to every resolver, so the
    API would 404 on it and the news shortlist would never route to it.

    The cache is keyed on the seed file's mtime+size, so an edit is picked
    up on the next call without a restart and without re-parsing YAML on
    every request.
    """

    def __init__(self, seed_path: str | Path = DEFAULT_SEED_PATH) -> None:
        self._seed_path = Path(seed_path)
        self._resolver: CanonicalEntityResolver | None = None
        self._stamp: tuple[float, int] | None = None

    def _current_stamp(self) -> tuple[float, int] | None:
        try:
            stat = self._seed_path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    def get(self) -> CanonicalEntityResolver:
        """The current resolver, rebuilt if the seed file changed."""
        stamp = self._current_stamp()
        if self._resolver is None or stamp != self._stamp:
            self._resolver = CanonicalEntityResolver.from_seed(self._seed_path)
            self._stamp = stamp
        return self._resolver

    def invalidate(self) -> None:
        """Force a reload on the next `get()`."""
        self._resolver = None
        self._stamp = None
