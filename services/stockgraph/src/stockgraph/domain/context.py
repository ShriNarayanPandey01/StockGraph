"""Public graph context contract; numeric history is exposed by the data service."""

from typing import Any

from pydantic import BaseModel, Field

from stockgraph.domain.enums import Window


class GraphNode(BaseModel):
    id: str
    kind: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    confidence: float | None = None
    rationale: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphContextResponse(BaseModel):
    ticker: str
    window: Window
    start_ts: int
    end_ts: int
    processing_status: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    direct_news: list[dict]
    indirect_news: list[dict]
    pagination: dict
