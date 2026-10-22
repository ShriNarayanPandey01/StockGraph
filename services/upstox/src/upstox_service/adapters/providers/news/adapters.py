"""News provider adapters - the anti-corruption layer for external news APIs.

Each provider has its own wire format (URL shape, auth style, response
schema, timestamp format). This module hides ALL of that behind one port:

    NewsProviderAdapter.fetch(since, limit) -> ProviderFetchResult

so the rest of the system only ever sees `NewsArticle` from the data-service domain
and never a provider symbol, a `api_token` parameter, or a
`"published": "2026-10-21 14:02:23 +0000"` timestamp.

Design notes:

* **Template Method.** `fetch()` is final and owns the request loop, the
  quota-independent paging, and the normalization. Subclasses implement only
  `_build_url()` (wire format) and `_parse()` (response schema). The shared
  `_normalize()` therefore exists exactly once.
* **No exceptions escape.** A provider failure degrades to an empty result
  with a `ProviderStatus`, never a crash - ingestion must not crash.
* **Paywall detection.** Alpha Vantage and FMP answer with an HTTP 200 whose
  body says the endpoint is premium/restricted. That is detected and
  reported as `DEGRADED_PAYWALL` instead of being parsed as news.

Provider capabilities were verified live against the deployed keys on
2026-10-21; see the class docstrings for what each provider actually
supports on its free tier.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from urllib.parse import quote, urlencode

from upstox_service.adapters.providers.http_client import ResilientHttpClient
from upstox_service.config.settings import settings
from upstox_service.domain.entities import NewsArticle
from upstox_service.domain.enums import NewsCategory
from upstox_service.domain.resolver import CanonicalEntityResolver

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    """Outcome of one provider fetch attempt."""

    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DEGRADED_PAYWALL = "DEGRADED_PAYWALL"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class StagedNewsItem:
    """One provider item ready to be staged immutably in `news_raw`.

    Carries the provider's untouched payload alongside the identity fields
    the staging table needs, so the audit trail is exactly what the
    provider returned.
    """

    external_id: str
    published_at: datetime
    source_url: str
    payload: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ProviderFetchResult:
    """Outcome of one provider fetch - articles plus how it went.

    Immutable: a fetch result is a record of what happened, not a mutable
    accumulator. Before eligibility filtering, `staged` carries each
    provider's untouched item dict.  After filtering it contains only the
    approved pairs that may be written to SQL. `watermark_at` still records
    the newest parsed provider item so rejected stories are not re-fetched.
    """

    provider_id: str
    status: ProviderStatus
    articles: tuple[NewsArticle, ...] = ()
    requests_used: int = 0
    error: str | None = None
    staged: tuple[StagedNewsItem, ...] = field(default=(), repr=False)
    watermark_at: datetime | None = None
    approvals: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    eligibility_counts: dict[str, int] = field(default_factory=dict, repr=False)


class ProviderPaywalled(RuntimeError):
    """The provider's plan does not include the endpoint we called."""


# Providers answer a plan refusal either with HTTP 200 and a notice in the
# body, or with HTTP 402 and the same notice. Detect both from the body.
_PAYWALL_MARKERS: tuple[str, ...] = (
    "premium endpoint",
    "restricted endpoint",
    "premium query parameter",
    "not available under your current subscription",
    "subscribe to any of the premium plans",
)


def detect_paywall(body: str | None) -> str | None:
    """Return the paywall notice in `body`, or None if there is none."""
    if not body:
        return None
    lowered = body.lower()
    for marker in _PAYWALL_MARKERS:
        if marker in lowered:
            return body.strip()[:200]
    return None


# --------------------------------------------------------------------------
# Category classification
# --------------------------------------------------------------------------

# Provider category/topic vocabularies -> the canonical NewsCategory enum.
#
# Split into two tiers. STRONG hints name a specific event type and win
# outright. WEAK hints only name the publisher's desk ("business",
# "technology"): they are the publisher's filing, not the event type, so
# they must not beat the text scan - otherwise every article on a business
# desk becomes SECTOR_UPDATE and the category carries no information.
_STRONG_HINT_CATEGORY: dict[str, NewsCategory] = {
    # earnings
    "earnings": NewsCategory.EARNINGS,
    "earnings_call": NewsCategory.EARNINGS,
    # corporate actions
    "ipo": NewsCategory.CORPORATE_ACTION,
    "mergers_acquisitions": NewsCategory.CORPORATE_ACTION,
    "merger": NewsCategory.CORPORATE_ACTION,
    "acquisition": NewsCategory.CORPORATE_ACTION,
    "client_relationships": NewsCategory.CORPORATE_ACTION,
    # macro
    "economy_macro": NewsCategory.MACRO,
    "economy_monetary": NewsCategory.MACRO,
    "monetary_policy": NewsCategory.MACRO,
    "fiscal_policy": NewsCategory.MACRO,
    "tax": NewsCategory.MACRO,
    "currency": NewsCategory.MACRO,
    "economy": NewsCategory.MACRO,
    # geopolitical
    "politics": NewsCategory.GEOPOLITICAL,
    "world": NewsCategory.GEOPOLITICAL,
    "geopolitics": NewsCategory.GEOPOLITICAL,
    "international": NewsCategory.GEOPOLITICAL,
    # commodity
    "commodities": NewsCategory.COMMODITY,
    "economy_commodities": NewsCategory.COMMODITY,
    "energy": NewsCategory.COMMODITY,
    "commodity": NewsCategory.COMMODITY,
}

# Keyword families for feeds that carry no usable category (Marketaux, FMP,
# and Currents items tagged only "general"). Order matters: the more
# specific earnings/corporate-action families are checked first.
#
# Patterns are word-boundary regexes, not bare substrings: a substring scan
# for "sector" matches "oil and gas sector" in a geopolitics story and
# mis-files it as SECTOR_UPDATE.
_TEXT_CATEGORIES: tuple[tuple[NewsCategory, tuple[str, ...]], ...] = (
    (
        NewsCategory.EARNINGS,
        (
            r"quarterly results",
            r"\bq[1-4] results\b",
            r"results today",
            r"reports profit",
            r"net profit",
            r"\bearnings\b",
            r"revenue (?:grew|fell|rose|slipped)",
            r"\bpat (?:rose|fell|jumped|declined)\b",
        ),
    ),
    (
        NewsCategory.CORPORATE_ACTION,
        (
            r"acquisition",
            r"acquires",
            r"to acquire",
            r"\bmerger\b",
            r"merges with",
            r"stake sale",
            r"sells stake",
            r"buyback",
            r"share buyback",
            r"bonus issue",
            r"rights issue",
            r"\bdividend\b",
            r"board approves",
            r"open offer",
            r"\bipo\b",
        ),
    ),
    (
        NewsCategory.COMMODITY,
        (
            r"\bcrude\b",
            r"\bbrent\b",
            r"oil price",
            r"coking coal",
            r"iron ore",
            r"steel price",
            r"coal price",
            r"commodity price",
        ),
    ),
    (
        NewsCategory.MACRO,
        (
            r"repo rate",
            r"monetary policy",
            r"\brbi\b",
            r"inflation",
            r"\bcpi\b",
            r"\bgdp\b",
            r"fiscal deficit",
            r"\bbudget\b",
            r"\bcapex\b",
            r"bond yield",
            r"usd/inr",
            r"\brupee\b",
            r"fed rate",
            r"\bfomc\b",
        ),
    ),
    (
        NewsCategory.TRADE,
        (
            r"\btrade war\b",
            r"\btrade deal\b",
            r"\btrade agreement\b",
            r"\bimport(?:s| duty| duties)?\b",
            r"\bexport(?:s| duty| duties)?\b",
            r"\btariff(?:s)?\b",
            r"supply chain",
            r"shipping route",
            r"freight rates?",
        ),
    ),
    (
        NewsCategory.GEOPOLITICAL,
        (
            r"\bsanction",
            r"\btariff",
            r"ceasefire",
            r"\bwar\b",
            r"diplomatic",
            r"\bsummit\b",
            r"\belection",
            r"geopolitic",
            r"\bdefen[cs]e\b",
            r"\bmilitary\b",
            r"\btreaty\b",
            r"bilateral",
            r"\bconflict\b",
            r"\bmissile",
            r"\bdrone strike",
            r"foreign minister",
        ),
    ),
    (
        NewsCategory.SECTOR_UPDATE,
        (
            r"auto sales",
            r"vehicle sales",
            r"\bmonsoon\b",
            r"cement demand",
            r"power demand",
            r"sectoral",
            r"\bnifty\b|\bsensex\b|\bnse\b|\bbse\b",
            r"\bshares?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
            r"\bstock(?:s)?\s+(?:rise|rises|rose|fall|falls|fell|jump|jumps|slip|slips|dip|dips|rally|rallies|trade)",
            r"\b(?:52[ -]?week|all[ -]?time)\s+(?:high|low)\b",
            r"\b(?:trading|trade)\s+volume\b",
        ),
    ),
)


def classify_category(hint: str | None, text: str) -> NewsCategory:
    """Map a provider category hint (or the article text) to NewsCategory.

    A STRONG hint (a specific event type) always wins. Otherwise the text
    is scanned against deterministic keyword families. Publisher desk labels
    such as ``business`` or ``technology`` are deliberately ignored: they are
    not evidence that an item is financially material.

    Never an LLM, so the classification is reproducible and free.
    """
    normalized_hint = hint.strip().lower() if hint else ""
    strong = _STRONG_HINT_CATEGORY.get(normalized_hint)
    if strong is not None:
        return strong
    lowered = text.lower()
    for category, patterns in _TEXT_CATEGORIES:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return category
    return NewsCategory.OTHER


# --------------------------------------------------------------------------
# Timestamp parsing
# --------------------------------------------------------------------------

_TIMESTAMP_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S.%f%z",  # Marketaux: 2026-10-21T12:37:12.000000Z
    "%Y-%m-%dT%H:%M:%S%z",  # Alpha Vantage / ISO with offset
    "%Y-%m-%d %H:%M:%S %z",  # Currents: 2026-10-21 14:02:23 +0000
    "%Y-%m-%d %H:%M:%S",  # FMP: 2026-10-20 21:10:50 (no offset -> UTC)
    "%Y-%m-%dT%H:%M:%S",  # ISO without offset
    "%Y%m%dT%H%M%S",  # Alpha Vantage time_published: 20240101T120000
)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a provider timestamp into a tz-aware UTC datetime.

    Handles every format the four providers emit. A naive timestamp is
    assumed to be UTC. Returns None when the value cannot be parsed - the
    caller drops the item rather than guessing a time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    # `Z` is a valid offset for fromisoformat but not for strptime.
    iso_candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in _TIMESTAMP_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


# --------------------------------------------------------------------------
# The port
# --------------------------------------------------------------------------


class NewsProviderAdapter(ABC):
    """Abstract news provider.

    Subclasses implement `_build_url()` and `_parse()`. Everything else -
    the request loop, paging, symbol resolution, category classification,
    sentiment clamping and summary truncation - is shared, so a provider
    cannot accidentally skip it.
    """

    provider_id: str = "provider"
    #: Lower is fetched first. The richer provider should claim the L1 URL
    #: slot first, because the first provider to see a URL owns the
    #: canonical NewsEvent.
    priority: int = 100
    #: Articles the plan returns per request (the free tiers clamp these).
    page_size: int = 20
    #: Free-tier daily request ceiling for this provider.
    plan_daily_cap: int = 100

    def __init__(
        self,
        api_key: str | None = None,
        resolver: CanonicalEntityResolver | None = None,
        http_client: ResilientHttpClient | None = None,
        summary_max_chars: int | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._resolver = resolver or CanonicalEntityResolver.from_seed()
        self._http = http_client or ResilientHttpClient()
        self._summary_max_chars = (
            summary_max_chars if summary_max_chars is not None else settings.news_summary_max_chars
        )

    # -- public API -------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """True when this provider has the credentials it needs."""
        return bool(self._api_key)

    def fetch(self, since: datetime, limit: int) -> ProviderFetchResult:
        """Fetch articles published since `since`. Never raises.

        Walks the provider's query plan (see `_query_plan`): each query kind
        is paged independently, up to its own page budget.
        """
        if not self.is_configured:
            return ProviderFetchResult(
                provider_id=self.provider_id,
                status=ProviderStatus.NOT_CONFIGURED,
                error="No API key configured",
            )

        articles: list[NewsArticle] = []
        staged: list[StagedNewsItem] = []
        requests_used = 0
        status = ProviderStatus.AVAILABLE
        error: str | None = None

        for query, pages in self._query_plan().items():
            for page in range(1, pages + 1):
                url = self._build_url(since, limit, page, query)
                outcome = self._http.fetch(url, extra_headers=self._auth_headers())
                requests_used += 1
                if not outcome.ok:
                    # A plan refusal can arrive as HTTP 402/403 with the notice
                    # in the body - that is a paywall, not a transport failure.
                    paywall = detect_paywall(outcome.text)
                    if paywall is not None:
                        status = ProviderStatus.DEGRADED_PAYWALL
                        error = paywall
                        logger.warning(
                            "%s is paywalled on this plan: %s", self.provider_id, paywall
                        )
                        break
                    status = ProviderStatus.ERROR
                    error = outcome.error
                    logger.warning("%s fetch failed: %s", self.provider_id, error)
                    break
                try:
                    items = self._parse(outcome.text)
                except ProviderPaywalled as exc:
                    status = ProviderStatus.DEGRADED_PAYWALL
                    error = str(exc)
                    logger.warning("%s is paywalled on this plan: %s", self.provider_id, exc)
                    break
                except (ValueError, KeyError, TypeError) as exc:
                    status = ProviderStatus.ERROR
                    error = f"unparseable response: {type(exc).__name__}: {exc}"
                    logger.warning("%s returned an unparseable body: %s", self.provider_id, exc)
                    break

                for article, stageable in self._normalize(items):
                    articles.append(article)
                    staged.append(stageable)
                if len(items) < self.page_size:
                    break
                if len(articles) >= limit:
                    break
            if status is not ProviderStatus.AVAILABLE or len(articles) >= limit:
                break

        return ProviderFetchResult(
            provider_id=self.provider_id,
            status=status,
            articles=tuple(articles[:limit]),
            requests_used=requests_used,
            error=error,
            staged=tuple(staged),
            watermark_at=max((item.published_at for item in staged), default=None),
        )

    # -- template method hooks -------------------------------------------

    def _query_plan(self) -> dict[str, int]:
        """Query kind -> number of pages to fetch for it this cycle.

        Most providers run a single query. A provider that wants both a
        targeted and a broad feed declares two kinds with their own page
        budgets, so a cheap broad sweep cannot crowd out the targeted one.
        """
        return {"default": settings.news_requests_per_run}

    @abstractmethod
    def _build_url(self, since: datetime, limit: int, page: int, query: str = "default") -> str:
        """Build the request URL for one page of one query kind."""

    @abstractmethod
    def _parse(self, body: str) -> list[dict[str, Any]]:
        """Parse a response body into raw item dicts.

        Each item dict uses the canonical intermediate keys:
        `id, title, description, url, published, source, category_hint,
        symbols, sentiments`, plus `raw` - the provider's untouched item
        dict, staged verbatim into `news_raw` for audit and replay.

        Raise `ProviderPaywalled` when the body says the endpoint is not
        included in the current plan.
        """

    def _auth_headers(self) -> dict[str, str] | None:
        """Extra HTTP headers for authentication. None when the key is a
        query parameter."""
        return None

    # -- shared normalization ---------------------------------------------

    def replay_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the canonical intermediate item from a STAGED payload.

        The staging table keeps the provider's untouched item, so a replay
        (re-running dedup, LLM routing and correlation over an already
        fetched corpus) never re-spends metered API quota. The default
        assumes the payload already uses the canonical keys; providers
        override it.
        """
        return dict(payload)

    def _normalize(
        self, items: Sequence[dict[str, Any]]
    ) -> list[tuple[NewsArticle, StagedNewsItem]]:
        """Convert raw provider items into (article, stageable) pairs.

        This is the anti-corruption boundary: provider symbols become
        canonical NSE tickers here, and anything that does not resolve is
        dropped rather than invented (Rule 4).
        """
        pairs: list[tuple[NewsArticle, StagedNewsItem]] = []
        for item in items:
            headline = str(item.get("title") or "").strip()
            if not headline:
                continue
            published = parse_timestamp(item.get("published"))
            if published is None:
                logger.debug("%s: dropping article without a usable timestamp", self.provider_id)
                continue

            summary = self._truncate(str(item.get("description") or ""))
            tickers, ticker_sentiment = self._resolve_symbols(item)
            article_sentiment = self._article_sentiment(item, ticker_sentiment)
            text = f"{headline} {summary}"
            external_id = str(item.get("id") or headline)[:160]
            source_url = str(item.get("url") or "")
            article = NewsArticle(
                external_id=external_id,
                headline=headline,
                summary=summary,
                source_url=source_url,
                source=self.provider_id,
                published_at=published,
                category=classify_category(item.get("category_hint"), text),
                sentiment=article_sentiment,
                tickers=tickers,
                ticker_sentiment=ticker_sentiment,
            )
            staged = StagedNewsItem(
                external_id=external_id,
                published_at=published,
                source_url=source_url,
                payload=item.get("raw") if isinstance(item.get("raw"), dict) else dict(item),
            )
            pairs.append((article, staged))
        return pairs

    def _resolve_symbols(self, item: dict[str, Any]) -> tuple[tuple[str, ...], dict[str, float]]:
        """Provider symbols -> (canonical tickers, per-ticker sentiment).

        Symbols that do not resolve through the Rule 4 gatekeeper are
        dropped, so an unlisted company never becomes a graph entity.
        """
        raw_symbols = item.get("symbols") or []
        sentiments = item.get("sentiments") or {}
        tickers: list[str] = []
        per_ticker: dict[str, float] = {}
        for symbol in raw_symbols:
            canonical = self._resolver.resolve_stock(str(symbol))
            if canonical is None:
                continue
            if canonical not in tickers:
                tickers.append(canonical)
            score = sentiments.get(symbol)
            if score is None:
                score = sentiments.get(canonical)
            if score is not None:
                per_ticker[canonical] = _clamp_sentiment(score)
        return tuple(tickers), per_ticker

    def _article_sentiment(
        self, item: dict[str, Any], ticker_sentiment: dict[str, float]
    ) -> float | None:
        """Article-level sentiment (-1..+1), if the provider supplied one."""
        score = item.get("sentiment")
        if score is None and ticker_sentiment:
            # Fall back to the dominant entity tone.
            score = max(ticker_sentiment.values(), key=abs)
        return None if score is None else _clamp_sentiment(score)

    def _truncate(self, text: str) -> str:
        """Clamp a summary to the configured length.

        Provider terms grant headline + snippet + deep link, not full-text
        redistribution, so summaries are stored truncated.
        """
        text = " ".join(text.split())
        if len(text) <= self._summary_max_chars:
            return text
        return text[: self._summary_max_chars - 1].rstrip() + "â€¦"


def _clamp_sentiment(value: Any) -> float:
    """Coerce a provider sentiment score into (-1.0, 1.0)."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, score))


#: Corporate suffixes stripped when a registry company name is used as a
#: search term - a news article says "Tata Steel", not "Tata Steel Ltd".
_CORPORATE_SUFFIXES: tuple[str, ...] = (
    " Ltd",
    " Limited",
    " Ltd.",
    " Corporation",
    " Company",
    " Ltd",
)


def clean_company_name(name: str) -> str:
    """Strip a trailing corporate suffix from a registry company name."""
    out = name.strip()
    for suffix in _CORPORATE_SUFFIXES:
        if out.endswith(suffix):
            out = out[: -len(suffix)].strip()
            break
    return out


# --------------------------------------------------------------------------
# Concrete providers
# --------------------------------------------------------------------------


class MarketauxNewsAdapter(NewsProviderAdapter):
    """Marketaux - the precision source (ticker + sentiment tagged).

    Verified live 2026-10-21: `symbols=` requires the exchange suffix
    (`TATASTEEL.NS`, not `TATASTEEL`), `countries=in` works, per-entity
    `sentiment_score` is present, and the FREE TIER CLAMPS `limit` to 3
    articles per request regardless of what is asked. The index also lags
    ~60-90 minutes behind `published_at`, which is why the fetch lookback
    is 180 minutes.
    """

    provider_id = "MARKETAUX"
    priority = 10
    page_size = 3
    plan_daily_cap = 100
    base_url = "https://api.marketaux.com/v1/news/all"

    def _build_url(self, since: datetime, limit: int, page: int, query: str = "default") -> str:
        symbols = [
            s
            for s in (self._resolver.provider_symbol(t) for t in self._resolver.list_stocks())
            if s
        ]
        params = {
            "api_token": self._api_key,
            "symbols": ",".join(symbols),
            "countries": "in",
            "entity_types": "equity",
            "must_have_entities": "true",
            "filter_entities": "true",
            "published_after": since.strftime("%Y-%m-%dT%H:%M:%S"),
            "limit": str(max(1, min(limit, self.page_size))),
        }
        return f"{self.base_url}?{urlencode(params)}"

    def _parse(self, body: str) -> list[dict[str, Any]]:
        payload = json.loads(body)
        items: list[dict[str, Any]] = []
        for raw in payload.get("data") or []:
            entities = [
                e
                for e in (raw.get("entities") or [])
                if str(e.get("type") or "").lower() == "equity"
            ]
            symbols = [str(e.get("symbol")) for e in entities if e.get("symbol")]
            sentiments = {
                str(e.get("symbol")): e.get("sentiment_score")
                for e in entities
                if e.get("symbol") and e.get("sentiment_score") is not None
            }
            items.append(
                {
                    "id": raw.get("uuid"),
                    "title": raw.get("title"),
                    "description": raw.get("description") or raw.get("snippet"),
                    "url": raw.get("url"),
                    "published": raw.get("published_at"),
                    "source": raw.get("source"),
                    "category_hint": None,  # Marketaux carries no article category.
                    "symbols": symbols,
                    "sentiments": sentiments,
                    "raw": raw,
                }
            )
        return items

    def replay_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the intermediate item from a staged Marketaux payload."""
        entities = [
            e
            for e in (payload.get("entities") or [])
            if str(e.get("type") or "").lower() == "equity"
        ]
        return {
            "id": payload.get("uuid"),
            "title": payload.get("title"),
            "description": payload.get("description") or payload.get("snippet"),
            "url": payload.get("url"),
            "published": payload.get("published_at"),
            "source": payload.get("source"),
            "category_hint": None,
            "symbols": [str(e.get("symbol")) for e in entities if e.get("symbol")],
            "sentiments": {
                str(e.get("symbol")): e.get("sentiment_score")
                for e in entities
                if e.get("symbol") and e.get("sentiment_score") is not None
            },
            "raw": payload,
        }


class CurrentsNewsAdapter(NewsProviderAdapter):
    """Currents - the breadth source (broad India feed, no ticker tags).

    Verified live 2026-10-21: `country=in` and `category=business` work,
    `page_size` is capped at 20 on the free tier (25 returns HTTP 400), and
    `/v1/search` accepts a strict-RFC3339 `start_date`/`end_date` window.
    The `published` field is space-separated (`2026-10-21 14:02:23 +0000`),
    not RFC3339.

    Two query kinds are run:

    * **targeted** - a boolean OR over the registry's COMPANY NAMES. This
      is what makes the feed routable: a broad India feed almost never
      names one of the tracked stocks, so most of its articles end up
      unattached. Measured live over a 24h window, the targeted query made
      10 of 20 returned articles routable, against 1 of 20 for the broad
      feed. Company NAMES discriminate far better than tickers: adding the
      tickers to the same query collapsed routability from 10 back to 3.
    * **broad** - the general India feed, for macro / geopolitics coverage
      that names no listed company.

    Only the company names are used, and the whole set is one request: the
    free plan's 250 requests/day leaves room for the broad sweep alongside.
    """

    provider_id = "CURRENTS"
    priority = 20
    page_size = 20
    plan_daily_cap = 250
    base_url = "https://api.currentsapi.services/v1/search"

    def _query_plan(self) -> dict[str, int]:
        plan = {"targeted": settings.news_requests_per_run}
        if settings.news_currents_include_broad:
            plan["broad"] = 1
        return plan

    def _auth_headers(self) -> dict[str, str] | None:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _build_url(self, since: datetime, limit: int, page: int, query: str = "targeted") -> str:
        params = {
            "start_date": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "language": "en",
            "page_number": str(page),
            "page_size": str(max(1, min(limit, self.page_size))),
        }
        if query == "targeted":
            params["query"] = self._targeted_query()
            params["country"] = settings.news_currents_country
        else:
            categories = [
                c.strip() for c in settings.news_currents_categories.split(",") if c.strip()
            ]
            if categories:
                params["category"] = ",".join(categories)
            params["country"] = settings.news_currents_country
        # `quote_via=quote` encodes spaces as %20 rather than '+': the
        # provider documents the parameter as URL-encoded.
        return f"{self.base_url}?{urlencode(params, quote_via=quote)}"

    def _targeted_query(self) -> str:
        """Boolean OR over the registry's company names.

        Company names, not tickers: a news article says "Tata Steel", and
        short tickers ("LT", "ITC", "INFY") match unrelated words.
        """
        terms = [clean_company_name(name) for name in self._resolver.list_stock_names().values()]
        terms = [t for t in dict.fromkeys(terms) if t]
        if not terms:
            return ""
        return "(" + " OR ".join(f'"{t}"' for t in terms) + ")"

    def _parse(self, body: str) -> list[dict[str, Any]]:
        payload = json.loads(body)
        if str(payload.get("status") or "").lower() == "error":
            raise ValueError(f"Currents error: {payload.get('message') or payload}")
        items: list[dict[str, Any]] = []
        for raw in payload.get("news") or []:
            categories = raw.get("category") or []
            items.append(
                {
                    "id": raw.get("id"),
                    "title": raw.get("title"),
                    "description": raw.get("description"),
                    "url": raw.get("url"),
                    "published": raw.get("published"),
                    "source": raw.get("source") or raw.get("site"),
                    "category_hint": categories[0] if categories else None,
                    "symbols": [],  # Currents does not tag entities.
                    "sentiments": {},
                    "raw": raw,
                }
            )
        return items

    def replay_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the intermediate item from a staged Currents payload."""
        categories = payload.get("category") or []
        return {
            "id": payload.get("id"),
            "title": payload.get("title"),
            "description": payload.get("description"),
            "url": payload.get("url"),
            "published": payload.get("published"),
            "source": payload.get("source") or payload.get("site"),
            "category_hint": categories[0] if categories else None,
            "symbols": [],
            "sentiments": {},
            "raw": payload,
        }


class AlphaVantageNewsAdapter(NewsProviderAdapter):
    """Alpha Vantage NEWS_SENTIMENT - ticker-scoped news with sentiment.

    NOT LIVE-VERIFIED: on the deployed key the endpoint answers
    `"This is a premium endpoint"`, so the request/response shape below is
    implemented from the published documentation and exercised only by
    frozen-fixture tests. The adapter detects the paywall body and reports
    `DEGRADED_PAYWALL` instead of raising, so it goes live unchanged once
    a premium key is configured.

    The Indian symbol suffix (`.BSE` by default) is a setting because the
    format could not be confirmed against a live response.
    """

    provider_id = "ALPHAVANTAGE"
    priority = 30
    page_size = 50
    plan_daily_cap = 25
    base_url = "https://www.alphavantage.co/query"

    def _build_url(self, since: datetime, limit: int, page: int, query: str = "default") -> str:
        tickers = [
            t
            for t in (
                f"{s}{settings.news_alpha_vantage_symbol_suffix}"
                for s in self._resolver.list_stocks()
            )
        ]
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ",".join(tickers),
            "limit": str(max(1, min(limit, self.page_size))),
            "apikey": self._api_key,
        }
        return f"{self.base_url}?{urlencode(params)}"

    def _parse(self, body: str) -> list[dict[str, Any]]:
        payload = json.loads(body)
        if "Information" in payload:
            raise ProviderPaywalled(str(payload["Information"])[:200])
        if "Error Message" in payload:
            raise ValueError(str(payload["Error Message"])[:200])
        items: list[dict[str, Any]] = []
        for raw in payload.get("feed") or []:
            sentiments = raw.get("ticker_sentiment") or []
            symbols = [str(s.get("ticker")) for s in sentiments if s.get("ticker")]
            per_ticker = {
                str(s.get("ticker")): s.get("ticker_sentiment_score")
                for s in sentiments
                if s.get("ticker") and s.get("ticker_sentiment_score") is not None
            }
            topics = [str(t.get("topic")) for t in (raw.get("topics") or []) if t.get("topic")]
            overall = raw.get("overall_sentiment_score")
            # `overall_sentiment_score` is documented on a 0..1 scale.
            article_sentiment = None if overall is None else (float(overall) * 2.0 - 1.0)
            items.append(
                {
                    "id": raw.get("url") or raw.get("title"),
                    "title": raw.get("title"),
                    "description": raw.get("summary"),
                    "url": raw.get("url"),
                    "published": raw.get("time_published") or raw.get("published_at"),
                    "source": raw.get("source"),
                    "category_hint": topics[0] if topics else None,
                    "symbols": symbols,
                    "sentiments": per_ticker,
                    "sentiment": article_sentiment,
                    "raw": raw,
                }
            )
        return items


class FmpNewsAdapter(NewsProviderAdapter):
    """FMP - ticker-scoped stock news.

    NOT LIVE-VERIFIED on the deployed plan: `stable/news/stock` answers
    `"Restricted Endpoint"`, so the adapter detects that and reports
    `DEGRADED_PAYWALL` instead of raising, and goes live unchanged once a
    plan with the news endpoints is configured.

    The ticker-scoped endpoint is used deliberately. FMP's free
    `fmp-articles` endpoint DOES respond, but it ignores any symbol filter
    and returns US analyst notes (SO, NTRS, CSX) that can never resolve to
    an Indian ticker - noise, not signal. `news/stock` is the endpoint
    that actually returns news for the tracked universe.
    """

    provider_id = "FMP"
    priority = 40
    page_size = 20
    plan_daily_cap = 250
    base_url = "https://financialmodelingprep.com/stable/news/stock"

    def _build_url(self, since: datetime, limit: int, page: int, query: str = "default") -> str:
        symbols = [
            s
            for s in (self._resolver.provider_symbol(t) for t in self._resolver.list_stocks())
            if s
        ]
        params = {
            "symbols": ",".join(symbols),
            "page": str(page - 1),  # FMP pages are 0-based.
            "limit": str(max(1, min(limit, self.page_size))),
            "apikey": self._api_key,
        }
        return f"{self.base_url}?{urlencode(params)}"

    def _parse(self, body: str) -> list[dict[str, Any]]:
        text = body.strip()
        if text.startswith("Restricted Endpoint") or text.startswith("Premium Query"):
            raise ProviderPaywalled(text[:200])
        payload = json.loads(text)
        if isinstance(payload, dict) and "Error Message" in payload:
            raise ValueError(str(payload["Error Message"])[:200])
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        items: list[dict[str, Any]] = []
        for raw in rows:
            symbols = raw.get("symbols") or raw.get("tickers") or []
            items.append(
                {
                    "id": raw.get("url") or raw.get("title"),
                    "title": raw.get("title"),
                    "description": raw.get("text") or raw.get("content"),
                    "url": raw.get("url") or raw.get("link"),
                    "published": raw.get("publishedDate") or raw.get("date"),
                    "source": raw.get("publisher") or raw.get("site"),
                    "category_hint": None,
                    "symbols": [str(s) for s in symbols],
                    "sentiments": {},
                    "raw": raw,
                }
            )
        return items
