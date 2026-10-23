"""Public manual-ingestion API schemas owned by the graph service.

These duplicate wire-level fields owned by the Data Service on purpose: service
packages must not import each other.  They are a proxy contract, not a second
catalog or a direct graph-write model.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stockgraph.domain.enums import NewsCategory

ManualEntityKind = Literal["Commodity", "MacroFactor", "Sector"]


class ManualEntityInput(BaseModel):
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


class ManualNewsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: str | None = Field(default=None, min_length=1, max_length=120)
    headline: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=4000)
    source_url: str = Field(min_length=1, max_length=2048)
    source: str = Field(default="MANUAL", min_length=1, max_length=120)
    published_at: datetime
    category: NewsCategory = NewsCategory.OTHER
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    tickers: list[str] = Field(default_factory=list, max_length=100)
    ticker_sentiment: dict[str, float] = Field(default_factory=dict)

    @field_validator("published_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("published_at must include a timezone")
        return value

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            ticker = value.strip().upper()
            if ticker and ticker not in normalized:
                normalized.append(ticker)
        return normalized

    @field_validator("ticker_sentiment")
    @classmethod
    def _normalize_ticker_sentiment(cls, values: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for ticker, score in values.items():
            value = float(score)
            if not -1.0 <= value <= 1.0:
                raise ValueError("ticker_sentiment scores must be between -1.0 and 1.0")
            normalized[ticker.strip().upper()] = value
        return normalized
