"""Validated public inputs and provider-independent immutable data contracts."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EntityKind(str, Enum):
    STOCK = "Stock"
    COMMODITY = "Commodity"
    MACRO = "MacroFactor"
    SECTOR = "Sector"


class StockRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=50)
    exchange: Literal["NSE", "BSE"] = "NSE"
    strengths: list[str] = Field(default_factory=list)
    business_exclusions: list[str] = Field(default_factory=list)


class EntityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    name: str = Field(min_length=1, max_length=240)
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    unit: str | None = None
    why_it_moves: str = ""
    equity_transmission: str = ""
    related_ids: list[str] = Field(default_factory=list)
    related_rationale: str = ""


class CompanyBundle(BaseModel):
    model_config = ConfigDict(frozen=True)
    entity: dict[str, Any]
    raw: dict[str, Any]
    statements: dict[str, Any] = Field(default_factory=dict)
    checkpoint: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


def event(
    kind: str, entity_id: str, revision: int, payload: dict, job_id: str | None = None
) -> dict:
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "kind": kind,
        "entity_id": entity_id,
        "revision": revision,
        "occurred_at": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "payload": payload,
    }
