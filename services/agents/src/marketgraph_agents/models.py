"""Versioned agent outputs; Platform independently validates all references."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class EvidenceRef(StrictModel):
    kind: Literal['news', 'professional', 'document', 'financial', 'graph']
    id: str = Field(min_length=1, max_length=100)
    locator: str | None = Field(default=None, max_length=300)
    quote: str = Field(min_length=1, max_length=2000)
    ticker: str = Field(pattern=r'^[A-Z0-9][A-Z0-9&_.-]{0,39}$')
    material_version: str = Field(pattern=r'^[0-9a-f]{64}$')


class Opportunity(StrictModel):
    ticker: str = Field(pattern=r'^[A-Z0-9][A-Z0-9&_.-]{0,39}$')
    direction: Literal['BULLISH', 'BEARISH']
    horizon_sessions: int = Field(ge=2, le=30)
    title: str = Field(min_length=1, max_length=300)
    thesis: str = Field(min_length=1, max_length=6000)
    why_now: str = Field(min_length=1, max_length=3000)
    risks: str = Field(min_length=1, max_length=3000)
    invalidation: str = Field(min_length=1, max_length=3000)
    catalyst: EvidenceRef
    connections: list[EvidenceRef] = Field(min_length=1, max_length=6)
    corroboration: list[EvidenceRef] = Field(min_length=1, max_length=20)
    counter_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    material_change: bool = False
    change_summary: str = Field(default='', max_length=3000)

    @model_validator(mode='after')
    def valid_sources(self):
        refs = [self.catalyst, *self.connections, *self.corroboration, *self.counter_evidence]
        if any(ref.ticker != self.ticker for ref in refs):
            raise ValueError('All opportunity evidence must refer to its stock')
        if self.catalyst.kind != 'news' or any(ref.kind != 'graph' for ref in self.connections):
            raise ValueError('A news catalyst and graph relationship path are required')
        if not any(ref.kind != 'graph' and (ref.kind != 'news' or ref.id != self.catalyst.id)
                   for ref in self.corroboration):
            raise ValueError('A distinct corroborating source is required')
        if self.material_change and not self.change_summary:
            raise ValueError('Material changes require an explanation')
        return self


class ResearchClaim(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=20)


class ModelFinding(StrictModel):
    answer: str = Field(min_length=1, max_length=30000)
    status: Literal['supported', 'no_opportunity', 'insufficient_evidence']
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=30)
    opportunities: list[Opportunity] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def validate_status(self):
        if self.status == 'supported' and not (self.evidence or self.claims or self.opportunities):
            raise ValueError('A supported result requires evidence')
        if self.status != 'supported' and self.opportunities:
            raise ValueError('An opportunity requires supported status')
        return self
