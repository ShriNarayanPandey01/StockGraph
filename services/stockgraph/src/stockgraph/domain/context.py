"""Public graph context contract; numeric history is exposed by the data service."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class NewsCitation(BaseModel):
    """Canonical source attribution for a news-context card."""

    url: str = Field(description="Canonical URL of the main source article.")
    title: str | None = Field(default=None, description="Article headline at ingestion.")
    publisher: str | None = Field(default=None, description="Ingesting source or publisher.")
    event_date: str | None = Field(default=None, description="Article event date (YYYY-MM-DD).")


class ContextNewsItem(BaseModel):
    """Graph-ready news payload with an explicit main-article citation."""

    model_config = ConfigDict(extra="allow")

    citation: NewsCitation | None = Field(
        default=None,
        description="Main source article. Null only when the upstream source supplied no URL.",
    )


class GraphContextResponse(BaseModel):
    ticker: str
    window: Window
    start_ts: int
    end_ts: int
    processing_status: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    direct_news: list[ContextNewsItem]
    indirect_news: list[ContextNewsItem]
    pagination: dict


class PublicMarketGraphSelection(BaseModel):
    """Counts and completeness information for the public graph preview."""

    stock_target: int
    stock_count: int
    market_driver_count: int
    news_count: int
    edge_count: int
    is_partial: bool


class PublicMarketGraphResponse(BaseModel):
    """Small, frontend-ready market graph assembled from public FalkorDB data."""

    generated_at: int
    start_ts: int
    end_ts: int
    selection: PublicMarketGraphSelection
    nodes: list[GraphNode]
    edges: list[GraphEdge]
