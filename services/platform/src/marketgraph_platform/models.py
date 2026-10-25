"""Strict application inputs; source timestamps are never confused with platform knowledge."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Principal(Input):
    id: UUID
    name: str
    professional_verified: bool = False
    email: str | None = None
    email_verified: bool = False
    is_developer: bool = False
    disabled: bool = False
    roles: list[Literal["USER", "PROFESSIONAL", "REVIEWER"]] = Field(default_factory=lambda: ["USER"])
    plan: Literal["FREE", "PRO"] = "FREE"
    plan_expires_at: datetime | None = None
    active_selection_initialized: bool = False


class Citation(Input):
    url: HttpUrl
    title: str = Field(min_length=1, max_length=300)
    locator: str = Field(min_length=1, max_length=500)
    document_version_id: UUID | None = None

    @field_validator("url")
    @classmethod
    def no_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("citation URLs must not contain credentials")
        return value


class ContributionInput(Input):
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9&_.-]{0,39}$")
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    horizon: str = Field(min_length=1, max_length=200)
    event_at: datetime
    expires_at: datetime
    evidence: list[Citation] = Field(min_length=1, max_length=50)
    disclosures: str = Field(min_length=1, max_length=3000)

    @field_validator("event_at", "expires_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validity(self):
        if self.expires_at <= self.event_at:
            raise ValueError("expiry must follow the declared event time")
        return self


class VersionInput(ContributionInput):
    expected_revision: int = Field(ge=1)


class RevisionInput(Input):
    expected_revision: int = Field(ge=1)


class ReviewInput(RevisionInput):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=3000)


class RetractionInput(RevisionInput):
    reason: str = Field(min_length=1, max_length=3000)
