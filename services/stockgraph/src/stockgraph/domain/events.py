"""Versioned wire contract, duplicated intentionally rather than importing another service."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommittedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    event_id: UUID
    kind: Literal["registry.updated", "news.received"]
    entity_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    occurred_at: datetime
    job_id: UUID | None = None
    payload: dict

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must contain a timezone")
        return value
