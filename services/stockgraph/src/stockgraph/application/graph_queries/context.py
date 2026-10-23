"""Assemble a graph-ready JSON page, including indirect causal paths."""

import hashlib

from stockgraph.adapters.repositories.falkor.repository import public_props
from stockgraph.domain.context import (
    ContextNewsItem,
    GraphContextResponse,
    GraphEdge,
    GraphNode,
    NewsCitation,
)
from stockgraph.domain.enums import Window
from stockgraph.domain.schemas import resolve_window


class GraphContextService:
    def __init__(self, repo):
        self._repo = repo

    def get_context(
        self,
        ticker: str,
        window: Window,
        offset: int = 0,
        limit: int = 50,
        as_of_ts: int | None = None,
    ) -> GraphContextResponse:
        ticker = ticker.upper()
        stock = self._repo.get_entity("Stock", ticker)
        if stock is None:
            raise KeyError(ticker)
        from datetime import UTC, datetime

        now = datetime.fromtimestamp(as_of_ts, UTC) if as_of_ts is not None else None
        start, end = resolve_window(window, now)
        page = self._repo.context_page(ticker, start, end, offset, limit)
        nodes, edges = {}, {}
        direct, indirect = [], []

        def node(kind: str, props: dict) -> str:
            identity = f"{kind}:{props.get('ticker') if kind == 'Stock' else props.get('id')}"
            nodes[identity] = GraphNode(id=identity, kind=kind, properties=public_props(props))
            return identity

        def edge(source: str, target: str, relation: str, props: dict) -> None:
            identity = (
                props.get("edge_id")
                or hashlib.sha1(
                    f"{source}|{target}|{relation}|{props.get('valid_from_ts', '')}|{props.get('baseline', '')}".encode()
                ).hexdigest()
            )
            provenance = {
                k: props[k]
                for k in ("inferred_by", "source", "source_url", "vendor_id", "vendor_as_of")
                if k in props
            }
            edges[identity] = GraphEdge(
                id=identity,
                source=source,
                target=target,
                relation=relation,
                confidence=props.get("confidence"),
                rationale=props.get("causal_rationale") or props.get("rationale"),
                provenance=provenance,
                properties=props,
            )

        def citation(news: dict) -> NewsCitation | None:
            source_url = news.get("source_url")
            if not isinstance(source_url, str) or not source_url.strip():
                return None
            return NewsCitation(
                url=source_url,
                title=news.get("headline"),
                publisher=news.get("source"),
                event_date=news.get("event_date") or news.get("date"),
            )

        stock_id = node("Stock", stock)
        for kind, target, relation, props in page["ontology"][:limit]:
            edge(stock_id, node(kind, target), relation, props)
        for news, relation, props in page["direct"][:limit]:
            edge(node("NewsEvent", news), stock_id, relation, props)
            direct.append(
                ContextNewsItem(
                    **{
                        **public_props(news),
                        "impact_type": relation,
                        "confidence": props.get("confidence"),
                        "rationale": props.get("causal_rationale") or props.get("rationale"),
                        "sentiment": props.get("sentiment"),
                        "citation": citation(news),
                    }
                )
            )
        for news, kind, target, exposure, exp_props, shock, shock_props in page["indirect"][:limit]:
            target_id = node(kind, target)
            edge(stock_id, target_id, exposure, exp_props)
            edge(node("NewsEvent", news), target_id, shock, shock_props)
            indirect.append(
                ContextNewsItem(
                    **{
                        **public_props(news),
                        "via_node": target_id,
                        "exposure_type": exposure,
                        "exposure_confidence": exp_props.get("confidence"),
                        "exposure_rationale": exp_props.get("rationale"),
                        "confidence": shock_props.get("confidence"),
                        "rationale": shock_props.get("causal_rationale")
                        or shock_props.get("rationale"),
                        "citation": citation(news),
                    }
                )
            )
        more = {section: len(rows) > limit for section, rows in page.items()}
        return GraphContextResponse(
            ticker=ticker,
            window=window,
            start_ts=start,
            end_ts=end,
            processing_status=stock.get("processing_state", "graph_processing"),
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            direct_news=direct,
            indirect_news=indirect,
            pagination={
                "offset": offset,
                "limit": limit,
                "has_more": more,
                "next_offset": offset + limit if any(more.values()) else None,
                "as_of_ts": end,
            },
        )
