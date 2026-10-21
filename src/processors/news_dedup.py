"""Multi-layered news deduplication L1-L3 orchestrator (Rule 5).

Thin orchestration over existing repository primitives - no new Cypher here:
- L1 exact URL match: canonicalize source_url and check Redis SETNX seen key.
- L2 near-duplicate before chunking: normalized headline match in the window
  via repo.find_text_dup - no embedding is spent on the dup.
- L3 semantic dedup during vector storage: repo.find_near_dup fan-out plus
  authoritative Python re-score via resolve_l3_duplicate
  (cosine >= dedup_cosine_threshold -> [:DUPLICATE_OF]).

Pure helpers are stdlib-only and fully unit-testable. Thresholds always come
from settings, never hardcoded.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.config.settings import settings

logger = logging.getLogger(__name__)

_TRACKING_EXACT = {"fbclid", "gclid", "msclkid", "yclid", "mc_cid", "mc_eid"}
_TRACKING_PREFIXES = ("utm_", "pk_", "matomo_", "igshid")
_SOURCE_SUFFIX_RE = re.compile(r"\s+[-|-\u2013\u2014]\s+[^-|-\u2013\u2014]{1,48}$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_MULTI_SPACE_RE = re.compile(r"\s+")

SOURCE_PRIORITY_ORDER = ("REG30", "BSE", "NSE", "RSS")
_SOURCE_RANK = {name: rank for rank, name in enumerate(reversed(SOURCE_PRIORITY_ORDER))}


def canonicalize_url(url: str) -> str:
    """Strip tracking params/fragment for stable L1 identity."""
    parts = urlsplit(url.strip())
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_EXACT and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def url_seen_key(canonical_url: str) -> str:
    """Redis L1 key for a canonical URL."""
    digest = hashlib.sha1(canonical_url.encode()).hexdigest()
    return f"seen:{digest}"


def normalize_headline(headline: str) -> str:
    """Lowercase, strip source suffix and punctuation for L2 matching."""
    text = headline.strip().lower()
    text = _SOURCE_SUFFIX_RE.sub("", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def deterministic_news_id(norm_headline: str, primary_entity: str, event_date: str) -> str:
    """Deterministic NewsEvent id: sha1(norm_headline|entity|date), 40 hex chars."""
    raw = f"{norm_headline}|{primary_entity.upper()}|{event_date}"
    return hashlib.sha1(raw.encode()).hexdigest()


def source_rank(source: str | None) -> int:
    """Priority rank; unknown sources rank lowest (-1)."""
    if not source:
        return -1
    return _SOURCE_RANK.get(source.strip().upper(), -1)


def higher_priority(new_source: str | None, canon_source: str | None) -> bool:
    """True when the new item outranks the canonical summary source."""
    return source_rank(new_source) > source_rank(canon_source)


def build_news_props(
    headline: str,
    primary_entity: str,
    event_date: str,
    event_ts: int,
    summary: str = "",
    source: str = "RSS",
    source_url: str = "",
    category: str = "OTHER",
    sentiment: float | None = None,
) -> dict[str, Any]:
    """Assemble deterministic NewsEvent props (embedding staged separately)."""
    norm = normalize_headline(headline)
    props: dict[str, Any] = {
        "id": deterministic_news_id(norm, primary_entity, event_date),
        "ticker": primary_entity.upper(),
        "headline": headline,
        "norm_headline": norm,
        "summary": summary,
        "source": source.upper(),
        "source_url": canonicalize_url(source_url) if source_url else "",
        "category": category,
        "event_ts": event_ts,
        "event_date": event_date,
    }
    if sentiment is not None:
        props["sentiment"] = sentiment
    return props


def _node_prop(node: Any, key: str) -> Any:
    """Best-effort prop read across dict rows and FalkorDB SDK Node objects."""
    if node is None:
        return None
    if isinstance(node, dict):
        return node.get(key)
    get = getattr(node, "get", None)
    if callable(get):
        try:
            return node.get(key)
        except Exception:  # noqa: BLE001 - fall through to .properties
            pass
    props = getattr(node, "properties", None)
    if isinstance(props, dict):
        return props.get(key)
    return getattr(node, key, None)


@dataclass(frozen=True)
class DedupOutcome:
    """Result of one item's L1-L3 pass."""

    action: str  # dropped_l1 | duplicate_l2 | duplicate_l3 | created
    news_id: str
    canonical_id: str | None = None


class NewsDeduper:
    """L1-L3 gatekeeper. repo/redis_client accept injectable fakes in tests."""

    def __init__(self, repo: Any | None = None, redis_client: Any | None = None) -> None:
        self._repo = repo
        self._redis = redis_client

    @property
    def window_secs(self) -> int:
        return settings.dedup_window_hours * 3600

    def check_l1_seen(self, source_url: str) -> tuple[bool, str]:
        """L1: True (drop) when the canonical URL was already ingested."""
        canonical = canonicalize_url(source_url)
        if self._redis is None or not canonical:
            return False, canonical
        key = url_seen_key(canonical)
        try:
            is_new = self._redis.set(key, "1", nx=True, ex=self.window_secs)
        except Exception as exc:  # fail open: ledger unreadable, keep ingesting
            logger.warning("L1 Redis unavailable (%s); failing open", exc)
            return False, canonical
        return (not bool(is_new)), canonical

    def check_l2_text_dup(self, norm_headline: str, ticker: str, now_ts: int) -> dict | None:
        """L2: normalized-headline hit within the window (no embedding spent)."""
        if self._repo is None:
            return None
        row = self._repo.find_text_dup(norm_headline, ticker.upper(), self.window_secs)
        if row is None:
            return None
        node = row[0] if isinstance(row, (list, tuple)) else row
        return {"canon_id": _node_prop(node, "id")}

    def link_duplicate(self, dup_id: str, canon_id: str) -> None:
        if self._repo is None:
            return
        self._repo.link_duplicate(dup_id, canon_id)

    def _maybe_upgrade_canonical(
        self, canon_id: str, new_props: dict[str, Any], canon_source: Any
    ) -> None:
        """Higher-priority source (Reg-30 > RSS) refreshes canonical summary."""
        if self._repo is None:
            return
        if not higher_priority(new_props.get("source"), str(canon_source or "")):
            return
        self._repo.merge_news_event(
            {
                "id": canon_id,
                "summary": new_props.get("summary", ""),
                "source": (new_props.get("source") or "").upper(),
                "source_url": new_props.get("source_url", ""),
            }
        )
        logger.info("Canonical %s summary upgraded by %s", canon_id, new_props.get("source"))

    def semantic_link_or_create(
        self, props: dict[str, Any], embedding: list[float], now_ts: int
    ) -> DedupOutcome:
        """L3: vector gate - DUPLICATE_OF on cosine >= threshold, else MERGE."""
        from src.repositories.falkor_repo import FalkorGraphRAGRepository

        ticker = str(props.get("ticker", "")).upper()
        if self._repo is None:
            return DedupOutcome(action="created", news_id=str(props["id"]))
        hit = self._repo.find_near_dup(embedding, ticker, now_ts)
        if hit is not None:
            node = hit[0] if isinstance(hit, (list, tuple)) else hit
            gate = FalkorGraphRAGRepository.resolve_l3_duplicate(
                embedding, _node_prop(node, "embedding")
            )
            if bool(gate["is_duplicate"]):
                canon_id = _node_prop(node, "id")
                if canon_id:
                    self.link_duplicate(str(props["id"]), str(canon_id))
                    self._maybe_upgrade_canonical(str(canon_id), props, _node_prop(node, "source"))
                    return DedupOutcome(
                        action="duplicate_l3",
                        news_id=str(props["id"]),
                        canonical_id=str(canon_id),
                    )
                logger.warning("L3 hit without canonical id; creating %s", props["id"])
        created = self._repo.merge_news_event(dict(props), embedding=embedding)
        created_id = _node_prop(created, "id") or props["id"]
        return DedupOutcome(action="created", news_id=str(created_id))

    def process(
        self, props: dict[str, Any], embedding: list[float] | None, now_ts: int
    ) -> DedupOutcome:
        """Full L1 to L3 pass for one candidate item."""
        news_id = str(props["id"])
        ticker = str(props.get("ticker", "")).upper()
        source_url = str(props.get("source_url", ""))
        if source_url:
            is_dup, _ = self.check_l1_seen(source_url)
            if is_dup:
                return DedupOutcome(action="dropped_l1", news_id=news_id)
        l2 = self.check_l2_text_dup(str(props.get("norm_headline", "")), ticker, now_ts)
        if l2 is not None and l2.get("canon_id"):
            self.link_duplicate(news_id, str(l2["canon_id"]))
            return DedupOutcome(
                action="duplicate_l2", news_id=news_id, canonical_id=str(l2["canon_id"])
            )
        if embedding is None:
            created = self._repo.merge_news_event(dict(props)) if self._repo is not None else {}
            created_id = _node_prop(created, "id") or news_id
            return DedupOutcome(action="created", news_id=str(created_id))
        return self.semantic_link_or_create(props, embedding, now_ts)
