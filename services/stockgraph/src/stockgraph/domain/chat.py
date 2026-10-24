"""Typed, frontend-agnostic conversational graph action contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stockgraph.domain.enums import Window


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    ticker: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._-]+$")
    window: Window = Window.LAST_6M


class GraphAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FOCUS_NODE", "HIGHLIGHT_PATH", "SHOW_NEWS", "RESET_VIEW"]
    node_ids: list[str] = Field(default_factory=list, max_length=30)


class ChatResponse(BaseModel):
    answer: str
    ticker: str
    window: Window
    actions: list[GraphAction] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    processing_status: str


class AgentDraft(BaseModel):
    """Untrusted model proposal, validated against retrieved graph data."""
    answer: str = Field(min_length=1, max_length=4000)
    actions: list[GraphAction] = Field(default_factory=list, max_length=8)
    citation_urls: list[str] = Field(default_factory=list, max_length=20)
