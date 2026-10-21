"""Dynamic Ontology Builder (Rule 4: Context-Aware Dynamic Edge Synthesis).

LLM receives a StockContextCard (business summary, raw materials, segments,
latest quarterly snapshot, guidance highlights, active exposures) and infers:
1. Stock <-> Commodity (EXPOSED_TO)
2. Stock <-> MacroFactor (SENSITIVE_TO_MACRO)
3. Stock <-> Sector (BELONGS_TO)
4. Stock <-> Peer Stock (SUPPLIES_TO, COMPETES_WITH)
5. Commodity <-> Commodity (RELATED_TO)

Every entity must resolve via CanonicalEntityResolver - unresolvable strings
are dropped, never invented (Rule 4: forex -> USD_INR_FX, no :Currency).
Edges must have confidence >= ontology_min_confidence (0.65).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from src.config.settings import settings
from src.domain.enums import OntologyRelationType
from src.domain.schemas import InferredOntologyEdge, StockContextCard
from src.llm.tokens import truncate_to_tokens
from src.processors.news_graph_extractor import render_card

logger = logging.getLogger(__name__)

VALID_RELATIONS = tuple(r.value for r in OntologyRelationType)


class OntologyEdgeBatch(BaseModel):
    """Structured LLM output schema for dynamic ontology edge discovery."""

    edges: list[InferredOntologyEdge] = Field(default_factory=list)


def build_ontology_prompt(card: StockContextCard, available_registry: list[str]) -> str:
    """Assemble the prompt with mandatory context card injection."""
    registry_list = ", ".join(sorted(available_registry[:60]))
    prompt = (
        "You are an Indian equities domain expert building a financial knowledge graph.\n"
        "Analyze this company's fundamentals and determine dynamic market ontology relationships.\n\n"
        f"COMPANY CONTEXT:\n{render_card(card)}\n\n"
        "ALLOWED REGISTRY IDs (Commodities, MacroFactors, Sectors):\n"
        f"{registry_list}\n\n"
        "RELATION TYPES:\n"
        "- EXPOSED_TO: input commodity dependency or margin driver (target: Commodity ID)\n"
        "- SENSITIVE_TO_MACRO: macroeconomic factor sensitivity (target: MacroFactor ID, e.g. USD_INR_FX, RBI_REPO_RATE)\n"
        "- BELONGS_TO: primary or secondary sector (target: Sector ID)\n"
        "- SUPPLIES_TO: customer/supplier relationship to another NSE listed stock (target: NSE Ticker)\n"
        "- COMPETES_WITH: direct peer competitor in Indian markets (target: NSE Ticker)\n"
        "- RELATED_TO: input/substitute link between two commodities\n\n"
        "RULES:\n"
        "1. Use ONLY valid canonical registry IDs or known NSE tickers.\n"
        "2. Forex is the USD_INR_FX macro factor (no Currency nodes exist).\n"
        "3. Provide confidence between 0.0 and 1.0, and an explicit rationale citing the company context.\n"
        'Return JSON: {"edges": [{"source_id": ..., "relation": "EXPOSED_TO|SENSITIVE_TO_MACRO|BELONGS_TO|SUPPLIES_TO|COMPETES_WITH|RELATED_TO", '
        '"target_id": ..., "confidence": ..., "rationale": ..., "exposure_nature": ..., "margin_impact": "POSITIVE|NEGATIVE|MIXED", "sensitivity": ...}]}'
    )
    return truncate_to_tokens(prompt)


class DynamicOntologyBuilder:
    """Context-aware LLM ontology builder with canonical entity gating (Rule 4)."""

    def __init__(self, chat: Any, resolver: Any) -> None:
        self._chat = chat
        self._resolver = resolver

    @property
    def min_confidence(self) -> float:
        return settings.ontology_min_confidence

    def infer_edges(
        self, card: StockContextCard, now_ts: int | None = None
    ) -> list[InferredOntologyEdge]:
        """Prompt LLM with StockContextCard and return validated, resolver-gated edges."""
        now = now_ts or int(time.time())
        # Compile candidate registry IDs for prompt guidance
        available = list(self._resolver.commodities | self._resolver.macros | self._resolver.sectors)
        prompt = build_ontology_prompt(card, available)

        try:
            batch = self._chat.complete_json(prompt, OntologyEdgeBatch)
        except Exception as exc:
            logger.warning("DynamicOntologyBuilder LLM call failed for %s: %s", card.ticker, exc)
            return []

        if isinstance(batch, dict):
            try:
                batch = OntologyEdgeBatch.model_validate(batch)
            except Exception as exc:
                logger.warning("Ontology output invalid for %s: %s", card.ticker, exc)
                return []

        if not isinstance(batch, OntologyEdgeBatch):
            logger.warning("Ontology builder rejected non-structured output for %s", card.ticker)
            return []

        return self.filter_edges(card.ticker, batch.edges, now)

    def filter_edges(
        self, ticker: str, edges: list[InferredOntologyEdge], now_ts: int
    ) -> list[InferredOntologyEdge]:
        """Gate: confidence floor, canonical entity resolution, relationship validation."""
        kept: list[InferredOntologyEdge] = []
        for edge in edges:
            rel = edge.relation.value if isinstance(edge.relation, OntologyRelationType) else str(edge.relation)
            if rel not in VALID_RELATIONS:
                continue
            if edge.confidence < self.min_confidence:
                continue

            source_id = edge.source_id or edge.source_ticker or ticker
            target_id = edge.target_id

            # Validation by relationship type
            if rel == "RELATED_TO":
                # Commodity-to-Commodity inter-link
                src_hit = self._resolver.resolve_registry(source_id)
                tgt_hit = self._resolver.resolve_registry(target_id)
                if src_hit is None or src_hit.kind != "commodity":
                    continue
                if tgt_hit is None or tgt_hit.kind != "commodity":
                    continue
                source_id = src_hit.id
                target_id = tgt_hit.id
            elif rel in ("SUPPLIES_TO", "COMPETES_WITH"):
                # Peer stock to peer stock
                src_stock = self._resolver.resolve_stock(source_id)
                tgt_stock = self._resolver.resolve_stock(target_id)
                if src_stock is None or tgt_stock is None:
                    continue
                source_id = src_stock
                target_id = tgt_stock
            elif rel == "EXPOSED_TO":
                src_stock = self._resolver.resolve_stock(source_id)
                tgt_hit = self._resolver.resolve_registry(target_id)
                if src_stock is None or tgt_hit is None or tgt_hit.kind != "commodity":
                    continue
                source_id = src_stock
                target_id = tgt_hit.id
            elif rel == "SENSITIVE_TO_MACRO":
                src_stock = self._resolver.resolve_stock(source_id)
                tgt_hit = self._resolver.resolve_registry(target_id)
                if src_stock is None or tgt_hit is None or tgt_hit.kind != "macro":
                    continue
                source_id = src_stock
                target_id = tgt_hit.id
            elif rel == "BELONGS_TO":
                src_stock = self._resolver.resolve_stock(source_id)
                tgt_hit = self._resolver.resolve_registry(target_id)
                if src_stock is None or tgt_hit is None or tgt_hit.kind != "sector":
                    continue
                source_id = src_stock
                target_id = tgt_hit.id
            else:
                continue

            kept.append(
                InferredOntologyEdge(
                    source_id=source_id,
                    relation=OntologyRelationType(rel),
                    target_id=target_id,
                    confidence=edge.confidence,
                    rationale=edge.rationale,
                    exposure_nature=edge.exposure_nature,
                    margin_impact=edge.margin_impact,
                    sensitivity=edge.sensitivity,
                    valid_from_ts=now_ts,
                )
            )
        return kept

    def persist(self, repo: Any, edges: list[InferredOntologyEdge]) -> int:
        """Write validated dynamic ontology edges into FalkorDB. Returns count written."""
        count = 0
        for edge in edges:
            rel = edge.relation.value if isinstance(edge.relation, OntologyRelationType) else str(edge.relation)
            repo.merge_ontology_edge(
                source_id=edge.source_id,
                relation=rel,
                target_id=edge.target_id,
                confidence=edge.confidence,
                rationale=edge.rationale,
                exposure_nature=edge.exposure_nature,
                margin_impact=edge.margin_impact,
                sensitivity=edge.sensitivity,
                valid_from_ts=edge.valid_from_ts,
            )
            count += 1
        return count
