"""Platform/source evidence contracts; intentionally independent of sibling packages."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlatformEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    event_id: UUID
    kind: Literal["professional.published", "professional.retracted", "professional.author-status", "document.extracted"]
    entity_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    occurred_at: datetime
    payload: dict

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("An explicit timezone is required")
        return value


class ProfessionalEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    contribution_id: UUID
    version_id: UUID
    author_id: UUID
    author_name: str = Field(min_length=1, max_length=200)
    ticker: str = Field(pattern=r"^[A-Z0-9&_.-]{1,40}$")
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    horizon: str = Field(min_length=1, max_length=200)
    disclosures: str = Field(default="", max_length=3000)
    event_at: datetime
    published_at: datetime
    known_at: datetime | None = None
    expires_at: datetime
    evidence: list[dict] = Field(min_length=1, max_length=50)
    future_access: Literal["PRO"] = "PRO"

    @field_validator("event_at", "published_at", "expires_at", "known_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("An explicit timezone is required")
        return value
