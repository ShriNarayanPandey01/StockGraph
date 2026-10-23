"""Developer-only graph-mutation request and response contracts.

Developer links are deliberately represented by one physical FalkorDB
relationship type (``DEVELOPER_LINK``).  The requested semantic relation is a
property, so its value stays parameterized and cannot become Cypher syntax.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeveloperNodeRef(BaseModel):
    """Reference an existing graph node by one of its labels and its business ID."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
    id: str = Field(min_length=1, max_length=160)


class DeveloperEdgeCreate(BaseModel):
    """A manual, auditable link between two existing FalkorDB nodes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: DeveloperNodeRef
    target: DeveloperNodeRef
    relation: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]{0,63}$",
        description="Developer-defined semantic relation stored as edge metadata",
    )
    rationale: str = Field(min_length=1, max_length=2000)
    actor: str = Field(min_length=1, max_length=120)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeveloperEdgeResponse(BaseModel):
    edge_id: str
    source: DeveloperNodeRef
    target: DeveloperNodeRef
    relation: str
    rationale: str
    actor: str
    confidence: float | None = None
    event_ts: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeveloperEdgeDeleteResponse(BaseModel):
    edge_id: str
    deleted: bool
