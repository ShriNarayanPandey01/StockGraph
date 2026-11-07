"""Resolve the candidate stock set for one news article (Rule 4 gatekeeper).

Two different questions are answered here, and keeping them apart is what
stops the same story arriving from two providers becoming two graph nodes:

* `resolve()` - which registry stocks are worth routing this article to?
  Provider-tagged tickers first (a provider's entity tagging is more
  precise than text matching), then text matches in document order.

* `primary_entity()` - which dedup bucket does this article belong to?
  Derived from the TEXT ONLY. The provider's tagging is deliberately not
  used: the same story fetched from Marketaux (tagged `SBIN.NS`) and from
  Currents (untagged) must resolve to the same bucket, or the L2/L3 dedup
  layers cannot see them as duplicates and the graph gains two nodes for
  one story.

Only registry tickers are ever returned - the resolver never invents a
node ID.
"""

from __future__ import annotations

from stockgraph.application.processors.entity_resolver import CanonicalEntityResolver, normalize
from stockgraph.domain.entities import NewsArticle

#: Bucket for news that names no registry ticker (macro, sector, geopolitics).
BROAD_MARKET = "BROAD_MARKET"

#: Tickers considered per article - the LLM prompt carries one context card
#: per candidate, so this bounds prompt size and LLM cost.
DEFAULT_MAX_CANDIDATES = None


class NewsCandidateResolver:
    """Resolve candidate stocks and the dedup bucket for a news article."""

    def __init__(
        self,
        resolver: CanonicalEntityResolver | None = None,
        max_candidates: int | None = DEFAULT_MAX_CANDIDATES,
    ) -> None:
        if resolver is None:
            raise ValueError("A committed canonical registry is required")
        self._resolver = resolver
        self._max_candidates = max_candidates

    def resolve(self, article: NewsArticle) -> list[str]:
        """Canonical tickers worth routing this article to.

        Provider-tagged tickers first (they are already canonical - the
        adapter resolved them), then text matches in document order.
        """
        candidates: list[str] = []
        for ticker in article.tickers:
            canonical = self._resolver.resolve_stock(ticker)
            if canonical is not None and canonical not in candidates:
                candidates.append(canonical)
        for ticker in self._text_matches(article):
            if ticker not in candidates:
                candidates.append(ticker)
        return candidates if self._max_candidates is None else candidates[: self._max_candidates]

    def primary_entity(self, article: NewsArticle) -> str:
        """The dedup bucket for an article - text-derived, provider-independent.

        Falls back to `BROAD_MARKET` when the article names no registry
        ticker.
        """
        matches = self._text_matches(article)
        return matches[0] if matches else BROAD_MARKET

    def _text_matches(self, article: NewsArticle) -> list[str]:
        """Registry tickers named in the article, in document order.

        Both the haystack and the alias keys are NORMALIZED, so punctuation
        in a company name does not defeat the match: "Larsen & Toubro"
        normalizes to "larsen toubro" and matches the alias "Larsen &
        Toubro" the same way.
        """
        haystack = normalize(f"{article.headline} {article.summary}")
        if not haystack:
            return []
        # Pad so a match at either end of the text still has word
        # boundaries: "tata steel" must match at the start of the headline.
        haystack = f" {haystack} "

        hits: list[tuple[int, str]] = []
        for key, ticker in self._resolver.stock_aliases():
            position = haystack.find(f" {key} ")
            if position >= 0:
                hits.append((position, ticker))

        # ISINs appear in filings rather than headlines, but a token scan
        # catches them cheaply.
        for token in haystack.split():
            resolved = self._resolver.resolve_stock(token)
            if resolved is not None:
                position = haystack.find(f" {token} ")
                hits.append((position if position >= 0 else 0, resolved))

        # Earliest mention wins; the same ticker can be reached by several
        # aliases, so keep only its first (leftmost) position.
        best: dict[str, int] = {}
        for position, ticker in hits:
            if ticker not in best or position < best[ticker]:
                best[ticker] = position
        return sorted(best, key=lambda t: (best[t], t))
