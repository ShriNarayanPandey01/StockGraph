"""Compose a deliberately small, public-facing market graph."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from stockgraph.application.graph_queries.presentation import public_props
from stockgraph.domain.context import (
    GraphEdge,
    GraphNode,
    PublicMarketGraphResponse,
    PublicMarketGraphSelection,
)

STOCK_TARGET = 15
DRIVER_LIMIT = 10
NEWS_LIMIT = 15
EDGE_LIMIT = 60
WINDOW_SECONDS = 30 * 24 * 60 * 60
DRIVER_KINDS = {"Commodity", "MacroFactor", "Sector"}
INTERNAL_PROPERTIES = {
    "embedding", "profile_embedding", "profile_json", "state_hash", "processing_state",
    "revision", "inference_revision", "metadata_json", "baseline", "is_latest",
    "valid_from_ts", "valid_to_ts",
}


def _identity(kind: str, props: dict[str, Any]) -> str:
    key = props.get("ticker") if kind == "Stock" else props.get("id")
    return f"{kind}:{key}"


def _safe_properties(props: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in public_props(props).items() if key not in INTERNAL_PROPERTIES}


def _edge_id(source: str, target: str, relation: str, props: dict[str, Any]) -> str:
    return props.get("edge_id") or hashlib.sha1(
        "|".join(
            (source, target, relation, str(props.get("event_ts", "")), str(props.get("valid_from_ts", "")))
        ).encode()
    ).hexdigest()


class PublicMarketGraphService:
    def __init__(self, repo):
        self._repo = repo

    def get_preview(self, now_ts: int | None = None) -> PublicMarketGraphResponse:
        end_ts = now_ts if now_ts is not None else int(datetime.now(UTC).timestamp())
        start_ts = end_ts - WINDOW_SECONDS
        data = self._repo.public_market_graph_data(start_ts, end_ts)
        candidates = sorted(
            data["candidates"],
            key=lambda item: (-item["news_count"], -item["ontology_count"], item["stock"].get("ticker", "")),
        )
        selected_stocks = self._choose_stocks(candidates, data["ontology"])
        stock_ids = {stock["ticker"] for stock in selected_stocks if stock.get("ticker")}

        driver_rows = [
            row for row in data["ontology"]
            if row["source"].get("ticker") in stock_ids and row["target_kind"] in DRIVER_KINDS
        ]
        driver_score: dict[str, float] = {}
        driver_props: dict[str, tuple[str, dict]] = {}
        for row in driver_rows:
            target_id = _identity(row["target_kind"], row["target"])
            driver_props[target_id] = (row["target_kind"], row["target"])
            driver_score[target_id] = driver_score.get(target_id, 0.0) + float(row["properties"].get("confidence", 0.0))
        selected_driver_ids = {
            identity for identity, _ in sorted(driver_score.items(), key=lambda item: (-item[1], item[0]))[:DRIVER_LIMIT]
        }

        impact_rows = [row for row in data["impacts"] if row["stock"].get("ticker") in stock_ids]
        news_rows: dict[str, dict] = {}
        for row in impact_rows:
            news_id = _identity("NewsEvent", row["news"])
            current = news_rows.get(news_id)
            if current is None or self._news_sort_key(row) < self._news_sort_key(current):
                news_rows[news_id] = row
        selected_news_ids = {
            identity
            for identity, _ in sorted(news_rows.items(), key=lambda item: self._news_sort_key(item[1]))[:NEWS_LIMIT]
        }

        nodes: dict[str, GraphNode] = {}
        for stock in selected_stocks:
            self._add_node(nodes, "Stock", stock)
        for driver_id in selected_driver_ids:
            kind, props = driver_props[driver_id]
            self._add_node(nodes, kind, props)
        for news_id in selected_news_ids:
            self._add_node(nodes, "NewsEvent", news_rows[news_id]["news"])

        edge_candidates: list[tuple[int, int, GraphEdge]] = []
        for row in data["ontology"]:
            source_id = row["source"].get("ticker")
            target_identity = _identity(row["target_kind"], row["target"])
            if source_id not in stock_ids:
                continue
            if row["target_kind"] == "Stock" and row["target"].get("ticker") not in stock_ids:
                continue
            if row["target_kind"] in DRIVER_KINDS and target_identity not in selected_driver_ids:
                continue
            edge_candidates.append((200, 0, self._edge("Stock", row["source"], row["target_kind"], row["target"], row["relation"], row["properties"])))
        for row in data["impacts"]:
            if row["stock"].get("ticker") not in stock_ids or _identity("NewsEvent", row["news"]) not in selected_news_ids:
                continue
            # Every retained news card should stay attached to the public graph.
            edge_candidates.append((300, int(row["news"].get("event_ts", 0)), self._edge("NewsEvent", row["news"], "Stock", row["stock"], row["relation"], row["properties"])))
        for row in data["shocks"]:
            if _identity("NewsEvent", row["news"]) not in selected_news_ids:
                continue
            if _identity(row["target_kind"], row["target"]) not in selected_driver_ids:
                continue
            edge_candidates.append((250, int(row["news"].get("event_ts", 0)), self._edge("NewsEvent", row["news"], row["target_kind"], row["target"], row["relation"], row["properties"])))
        for row in data["correlations"]:
            if _identity("NewsEvent", row["source"]) in selected_news_ids and _identity("NewsEvent", row["target"]) in selected_news_ids:
                edge_candidates.append((150, int(row["source"].get("event_ts", 0)), self._edge("NewsEvent", row["source"], "NewsEvent", row["target"], "CORRELATED_WITH", row["properties"])))
        for row in data["related"]:
            source = _identity("Commodity", row["source"])
            target = _identity("Commodity", row["target"])
            if source in selected_driver_ids and target in selected_driver_ids:
                edge_candidates.append((100, 0, self._edge("Commodity", row["source"], "Commodity", row["target"], "RELATED_TO", row["properties"])))

        edges: dict[str, GraphEdge] = {}
        for _, _, edge in sorted(edge_candidates, key=lambda item: (-item[0], -item[1], item[2].id)):
            if len(edges) >= EDGE_LIMIT:
                break
            edges.setdefault(edge.id, edge)
        return PublicMarketGraphResponse(
            generated_at=end_ts,
            start_ts=start_ts,
            end_ts=end_ts,
            selection=PublicMarketGraphSelection(
                stock_target=STOCK_TARGET,
                stock_count=len(selected_stocks),
                market_driver_count=len(selected_driver_ids),
                news_count=len(selected_news_ids),
                edge_count=len(edges),
                is_partial=(
                    len(selected_stocks) < STOCK_TARGET
                    or len(selected_driver_ids) < DRIVER_LIMIT
                    or len(selected_news_ids) < NEWS_LIMIT
                ),
            ),
            nodes=list(nodes.values()),
            edges=list(edges.values()),
        )

    def _choose_stocks(self, candidates: list[dict], ontology: list[dict]) -> list[dict]:
        if not candidates:
            return []
        candidate_by_ticker = {item["stock"].get("ticker"): item for item in candidates if item["stock"].get("ticker")}
        chosen = [candidates[0]["stock"]]
        chosen_ids = {chosen[0].get("ticker")}
        while len(chosen) < STOCK_TARGET:
            remaining = [item for ticker, item in candidate_by_ticker.items() if ticker not in chosen_ids]
            if not remaining:
                break
            selected_targets = {
                _identity(row["target_kind"], row["target"])
                for row in ontology
                if row["source"].get("ticker") in chosen_ids
            }
            def connection_score(item: dict) -> int:
                ticker = item["stock"].get("ticker")
                rows = [row for row in ontology if row["source"].get("ticker") == ticker]
                peer_links = sum(1 for row in rows if row["target_kind"] == "Stock" and row["target"].get("ticker") in chosen_ids)
                # Edge direction carries causal meaning, but connectivity for a
                # visual cluster is intentionally undirected: a selected stock
                # that points to this candidate is still a useful neighbour.
                peer_links += sum(
                    1
                    for row in ontology
                    if row["source"].get("ticker") in chosen_ids
                    and row["target_kind"] == "Stock"
                    and row["target"].get("ticker") == ticker
                )
                shared_targets = sum(1 for row in rows if _identity(row["target_kind"], row["target"]) in selected_targets)
                return peer_links * 100 + shared_targets
            next_item = min(
                remaining,
                key=lambda item: (-connection_score(item), -item["news_count"], -item["ontology_count"], item["stock"].get("ticker", "")),
            )
            chosen.append(next_item["stock"])
            chosen_ids.add(next_item["stock"].get("ticker"))
        return chosen

    @staticmethod
    def _news_sort_key(row: dict) -> tuple[int, float, str]:
        return (-int(row["news"].get("event_ts", 0)), -float(row["properties"].get("confidence", 0.0)), row["news"].get("id", ""))

    @staticmethod
    def _add_node(nodes: dict[str, GraphNode], kind: str, props: dict) -> None:
        identity = _identity(kind, props)
        nodes[identity] = GraphNode(id=identity, kind=kind, properties=_safe_properties(props))

    @staticmethod
    def _edge(source_kind: str, source: dict, target_kind: str, target: dict, relation: str, props: dict) -> GraphEdge:
        source_id, target_id = _identity(source_kind, source), _identity(target_kind, target)
        hidden = {"edge_id", "confidence", "rationale", "causal_rationale", "inferred_by", "source", "source_url", "vendor_id", "vendor_as_of", *INTERNAL_PROPERTIES}
        return GraphEdge(
            id=_edge_id(source_id, target_id, relation, props),
            source=source_id,
            target=target_id,
            relation=relation,
            confidence=props.get("confidence"),
            rationale=props.get("rationale") or props.get("causal_rationale"),
            provenance={key: props[key] for key in ("inferred_by", "source", "source_url", "vendor_id", "vendor_as_of") if key in props},
            properties={key: value for key, value in props.items() if key not in hidden},
        )
