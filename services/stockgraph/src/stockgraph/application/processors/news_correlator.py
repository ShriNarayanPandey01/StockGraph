"""L4 cross-news correlator: link related canonical NewsEvents (Rule 5).

Candidate priors share an impacted :Stock/:Commodity/:MacroFactor/:Sector in
the trailing correlation_window_days (or cosine in [correlation_min_cosine,
dedup_cosine_threshold)). The LLM judges each pair; links persist as
(new)-[:CORRELATED_WITH {...}]->(prior). Thresholds from settings only.
The dup band (>= dedup_cosine_threshold) links [:DUPLICATE_OF], never here.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from stockgraph.adapters.llm.tokens import truncate_to_tokens
from stockgraph.domain.enums import CorrelationType, NewsCategory
from stockgraph.domain.schemas import InferredNewsCorrelation
from stockgraph.runtime.settings import settings

logger = logging.getLogger(__name__)

VALID_CORRELATION_TYPES = tuple(t.value for t in CorrelationType)
MAX_CANDIDATES_PER_PROMPT = 10

#: Only market-relevant stories may be correlated. The broad news feed
#: carries a large amount of non-market copy (sport, weather, crime,
#: celebrity); the paraphrase band puts two such articles next to each
#: other often enough that the model starts linking them, and the graph
#: ends up with a "correlated" sports story.
MARKET_CATEGORIES = frozenset(
    {
        NewsCategory.EARNINGS.value,
        NewsCategory.SECTOR_UPDATE.value,
        NewsCategory.MACRO.value,
        NewsCategory.TRADE.value,
        NewsCategory.GEOPOLITICAL.value,
        NewsCategory.REG30.value,
        NewsCategory.COMMODITY.value,
        NewsCategory.CORPORATE_ACTION.value,
    }
)


class NewsCorrelationBatch(BaseModel):
    """Structured LLM envelope: correlation verdicts for candidate pairs."""

    correlations: list[InferredNewsCorrelation] = Field(default_factory=list)


def in_paraphrase_band(cosine: float) -> bool:
    """True when cosine falls in [min_cosine, dedup_threshold): correlate it."""
    return settings.correlation_min_cosine <= cosine < settings.dedup_cosine_threshold


def build_correlation_prompt(
    new_headline: str,
    new_summary: str,
    candidates: list[dict[str, Any]],
) -> str:
    """Assemble the L4 verdict prompt for one new item vs its candidates."""
    lines = [
        "You link ONE new financial news item to PRIOR related stories.",
        f"NEW: {new_headline} || {new_summary}",
        "",
        "CANDIDATE PRIORS (id | date-ts | headline | summary):",
    ]
    for cand in candidates[:MAX_CANDIDATES_PER_PROMPT]:
        lines.append(
            f"- {cand.get('id')} | {cand.get('event_ts')} | "
            f"{cand.get('headline')} || {cand.get('summary')}"
        )
    lines += [
        "",
        "RULES:",
        "- CAUSAL_CHAIN: prior event caused/triggered the new one.",
        "- MACRO_CONTAGION: same macro/commodity shock propagating.",
        "- SECTOR_RIPPLE: same sector theme spreading across companies.",
        "- FOLLOW_UP: same story with new developments.",
        "- Link ONLY stories about the same market story. If the two items "
        "are not about markets, or are about different markets, link "
        "nothing - sports, weather, crime and celebrity coverage is never "
        "a market correlation.",
        "- Omit unrelated pairs. confidence 0.0-1.0 with a rationale.",
        'Return JSON: {"correlations": [{"new_news_id": ..., "prior_news_id": '
        '..., "correlation_type": "CAUSAL_CHAIN|MACRO_CONTAGION|SECTOR_RIPPLE|'
        'FOLLOW_UP", "confidence": ..., "rationale": ..., "event_ts": ...}]}',
    ]
    return truncate_to_tokens("\n".join(lines))


class NewsCorrelator:
    """L4 judge: candidate fetch (graph) + verdict (LLM) + persist."""

    def __init__(self, chat: Any) -> None:
        self._chat = chat

    @property
    def min_confidence(self) -> float:
        return settings.ontology_min_confidence

    def correlate(
        self,
        repo: Any,
        news_id: str,
        headline: str,
        summary: str,
        event_ts: int,
        now_ts: int,
        embedding: list[float] | None = None,
    ) -> list[InferredNewsCorrelation]:
        """Fetch candidates, judge pairs, persist links. Returns kept links."""
        try:
            if embedding is not None:
                candidates = repo.find_correlation_candidates(news_id, now_ts, embedding=embedding)
            else:
                candidates = repo.find_correlation_candidates(news_id, now_ts)
        except Exception as exc:
            # A failed read is not an empty successful candidate set. The event
            # remains pending and can retry without refetching metered providers.
            raise RuntimeError("News correlation candidate query failed") from exc
        rows = [self._row_to_dict(r) for r in candidates or []]
        rows = [r for r in rows if r.get("id") and r["id"] != news_id]
        # Only market-relevant stories may be correlated (see
        # MARKET_CATEGORIES): the broad feed's non-market copy otherwise
        # gets paired by the paraphrase band and linked as "correlated".
        rows = [r for r in rows if self._is_market_category(r.get("category"))]
        if not rows:
            return []
        prompt = build_correlation_prompt(headline, summary, rows)
        try:
            batch = self._chat.complete_json(prompt, NewsCorrelationBatch)
        except Exception as exc:
            logger.warning("L4 LLM call failed for %s: %s", news_id, exc)
            return []
        if isinstance(batch, dict):
            try:
                batch = NewsCorrelationBatch.model_validate(batch)
            except Exception as exc:
                logger.warning("L4 output invalid for %s: %s", news_id, exc)
                return []
        if not isinstance(batch, NewsCorrelationBatch):
            logger.warning("L4 rejected non-structured output for %s", news_id)
            return []
        return self.filter_and_persist(
            repo, news_id, event_ts, batch.correlations, valid_prior_ids=[r["id"] for r in rows]
        )

    def filter_and_persist(
        self,
        repo: Any,
        news_id: str,
        event_ts: int,
        verdicts: list[InferredNewsCorrelation],
        valid_prior_ids: list[str] | None = None,
    ) -> list[InferredNewsCorrelation]:
        """Gate verdicts (type, confidence, self-link, known prior) and persist links.

        The ids are plumbing the caller owns: `new_news_id` is set from the
        known article, and `prior_news_id` must be one of the candidates we
        actually offered. A model that invents or mangles an id cannot
        attach a correlation edge to an unrelated article.
        """
        kept: list[InferredNewsCorrelation] = []
        allowed = set(valid_prior_ids) if valid_prior_ids is not None else None
        for v in verdicts:
            raw = v.correlation_type
            ctype = raw.value if isinstance(raw, CorrelationType) else raw
            if ctype not in VALID_CORRELATION_TYPES:
                continue
            if not v.rationale.strip():
                continue
            if not 0.0 <= v.confidence <= 1.0:
                continue
            if v.confidence < self.min_confidence:
                continue
            if not v.prior_news_id or v.prior_news_id == news_id:
                continue
            if allowed is not None and v.prior_news_id not in allowed:
                logger.debug("Dropping correlation to unknown prior %r", v.prior_news_id)
                continue
            repo.merge_news_correlation(
                news_id, v.prior_news_id, ctype, v.confidence, v.rationale, event_ts
            )
            kept.append(
                InferredNewsCorrelation(
                    new_news_id=news_id,
                    prior_news_id=v.prior_news_id,
                    correlation_type=CorrelationType(ctype),
                    confidence=v.confidence,
                    rationale=v.rationale,
                    event_ts=event_ts,
                )
            )
        return kept

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return row
        if hasattr(row, "keys"):
            try:
                keys = list(row.keys())
                if keys and all(isinstance(k, str) for k in keys):
                    return {k: row[k] for k in keys}
            except Exception:  # noqa: BLE001 - fall through to positional
                pass
        try:
            values = list(row)
        except TypeError:
            return {}
        cols = ("id", "headline", "summary", "event_ts", "category")
        return {c: (values[i] if i < len(values) else None) for i, c in enumerate(cols)}

    @staticmethod
    def _is_market_category(category: Any) -> bool:
        """True when the story's category is market-relevant.

        An unknown/absent category is allowed through: a missing label must
        not silently drop a legitimate correlation.
        """
        if category is None:
            return True
        return str(category) in MARKET_CATEGORIES
