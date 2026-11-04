"""Bounded breadth-first exploration, independent of evidence pagination."""

import hashlib
import json

from stockgraph.adapters.repositories.falkor.repository import public_props
from stockgraph.domain.context import GraphEdge, GraphExploration, GraphNode


def _node_properties(props: dict) -> dict:
    """Expose the same descriptive profile fields for the root and its peers."""
    profile = props.get("profile_json")
    profile = json.loads(profile) if isinstance(profile, str) else profile
    profile = profile if isinstance(profile, dict) else {}
    return public_props({**profile, **props})


def stock_exploration(repo, stock: dict, start: int, end: int, hops: int) -> GraphExploration:
    if hops not in (1, 2, 3):
        raise ValueError("Graph depth must be between one and three hops")
    node_limit, edge_limit, candidate_limit = 200, 500, 1000
    root_id = f"Stock:{stock['ticker']}"
    nodes = {root_id: GraphNode(id=root_id, kind="Stock", properties=_node_properties(stock))}
    edges = {}
    additional_edges = {}
    distances = {root_id: 0}
    frontier = [root_id]
    truncated = False

    def identity(kind, props):
        return f"{kind}:{props.get('ticker') if kind == 'Stock' else props.get('id')}"

    def node(kind, props, hop):
        key = identity(kind, props)
        if key not in nodes:
            nodes[key] = GraphNode(id=key, kind=kind, properties=_node_properties(props))
            distances[key] = hop
        return key

    for depth in range(1, hops + 1):
        if not frontier:
            break
        rows = repo.exploration_neighbors(frontier, start, end, candidate_limit)
        truncated = truncated or len(rows) > candidate_limit
        following = []
        for _, source_kind, source, relation, props, target_kind, target in rows[:candidate_limit]:
            source_id, target_id = identity(source_kind, source), identity(target_kind, target)
            key = props.get("edge_id") or hashlib.sha1(
                f"{source_id}|{target_id}|{relation}|{props.get('valid_from_ts', '')}|{props.get('baseline', '')}".encode()
            ).hexdigest()
            if key in edges or key in additional_edges:
                continue
            new_ids = {source_id, target_id} - nodes.keys()
            if len(nodes) + len(new_ids) > node_limit or len(edges) >= edge_limit:
                truncated = True
                continue
            for kind, properties in ((source_kind, source), (target_kind, target)):
                key_id = identity(kind, properties)
                if key_id not in nodes:
                    following.append(node(kind, properties, depth))
            if relation == "DEVELOPER_LINK":
                relation = props.get("relation") or relation
                props = {**props, "inferred_by": "developer_api",
                         "metadata": json.loads(props.get("metadata_json") or "{}")}
            view = GraphEdge(
                id=key, source=source_id, target=target_id, relation=relation,
                confidence=props.get("confidence"),
                rationale=props.get("causal_rationale") or props.get("rationale"),
                provenance={k: props[k] for k in (
                    "inferred_by", "source", "source_url", "vendor_id", "vendor_as_of",
                ) if k in props},
                properties=public_props(props),
            )
            # Reserve room for reaching the next layer before filling the
            # drawing with parallel versions and cross-links at this layer.
            if new_ids:
                edges[key] = view
            else:
                additional_edges[key] = view
        frontier = following
    for key, view in additional_edges.items():
        if len(edges) >= edge_limit:
            truncated = True
            break
        edges[key] = view
    return GraphExploration(
        hops=hops, nodes=list(nodes.values()), edges=list(edges.values()),
        distances=distances, truncated=truncated, node_limit=node_limit, edge_limit=edge_limit,
    )
