"""API request/response Pydantic models for the Stock Dossier (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from stockgraph.domain.enums import CorrelationType, MarketSession, OntologyRelationType, Window

APP_TZ = ZoneInfo("Asia/Kolkata")

WINDOW_DAYS: dict[Window, int] = {
    Window.LAST_6M: 180,
    Window.LAST_1Y: 365,
}


def resolve_window(window: Window, now: datetime | None = None) -> tuple[int, int]:
    """Resolve a fixed window to IST-aware UTC epoch bounds (Rule 3).

    `LAST_6M` -> [now-180d, now], `LAST_1Y` -> [now-365d, now].
    Start is Asia/Kolkata start-of-day; end is now.
    """
    end = now.astimezone(APP_TZ) if now is not None else datetime.now(APP_TZ)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    days = WINDOW_DAYS[window]
    from datetime import timedelta

    start = start - timedelta(days=days - 1)
    return int(start.timestamp()), int(end.timestamp())


class DossierRequest(BaseModel):
    ticker: str = Field(description="NSE ticker, e.g. TATASTEEL")
    window: Window = Window.LAST_6M


class DirectNewsItem(BaseModel):
    id: str
    event_date: str | None = None
    event_ts: int | None = None
    headline: str | None = None
    summary: str | None = None
    category: str | None = None
    sentiment: float | None = None
    impact_type: str | None = Field(
        default=None, description="DIRECTLY_IMPACTS | INDIRECTLY_IMPACTS"
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = None
    correlated_news_ids: list[str] = Field(default_factory=list)


class IndirectNewsItem(BaseModel):
    id: str
    event_date: str | None = None
    event_ts: int | None = None
    via_node: str | None = None
    exposure_type: str | None = None
    margin_impact: str | None = None
    headline: str | None = None
    sentiment: float | None = None
    exposure_nature: str | None = None
    exposure_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    exposure_rationale: str | None = None


class StockContextCard(BaseModel):
    """Complete company context injected into every LLM ontology/news prompt.

    Assembled by StockProfileProvider from the seeded business profile
    (ontology_seed.yaml), the latest QuarterlySnapshot, the latest
    GuidanceChunk highlights, and currently active graph exposures.
    """

    ticker: str = Field(description="NSE ticker, e.g. TATASTEEL")
    business_summary: str | None = None
    strengths: list[str] = Field(default_factory=list)
    business_exclusions: list[str] = Field(default_factory=list)
    revenue_segments: list[str] = Field(default_factory=list)
    raw_material_inputs: list[str] = Field(default_factory=list)
    geographic_exposure: str | None = None
    latest_quarter_summary: str | None = None
    latest_guidance_highlights: list[str] = Field(default_factory=list)
    active_exposures: list[str] = Field(
        default_factory=list,
        description="Canonical registry IDs the stock is currently linked to",
    )
    sector: str | None = Field(
        default=None,
        description="Canonical sector registry ID the stock belongs to, e.g. METALS",
    )


class InferredOntologyEdge(BaseModel):
    """Structured LLM output for DynamicOntologyBuilder edge discovery.

    Covers stock edges (source = ticker) AND commodity inter-links
    (source = commodity id with relation RELATED_TO).
    """

    source_id: str = Field(
        description="NSE ticker (stock edge) or commodity registry ID "
        "(commodity inter-link with relation RELATED_TO)"
    )
    source_ticker: str | None = Field(
        default=None,
        description="Deprecated alias of source_id for stock edges; use source_id",
    )
    relation: OntologyRelationType
    target_id: str = Field(
        description="Canonical registry ID (commodity/macro/sector) "
        "or peer stock ticker; must resolve via CanonicalEntityResolver"
    )
    exposure_nature: str | None = None
    margin_impact: str | None = Field(default=None, description="POSITIVE | NEGATIVE | MIXED")
    sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    valid_from_ts: int | None = None

    @field_validator("sensitivity", mode="before")
    @classmethod
    def _coerce_sensitivity(cls, value: Any) -> float | None:
        """Accept a qualitative label as well as a number.

        Models routinely answer "sensitivity" with HIGH / MEDIUM / LOW
        instead of a 0.0-1.0 score, and a schema that rejects the string
        takes the WHOLE edge batch down with it - one mislabelled field
        would have cost every relation for that stock.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip().lower()
        if not text:
            return None
        labels = {
            "very high": 0.9,
            "very low": 0.1,
            "high": 0.8,
            "medium": 0.5,
            "moderate": 0.5,
            "low": 0.2,
            "none": 0.0,
        }
        if text in labels:
            return labels[text]
        try:
            return float(text)
        except ValueError:
            return None


class InferredNewsStockImpact(BaseModel):
    """Structured LLM output for NewsGraphExtractor 1-hop/2-hop routing.

    The LLM's job is to JUDGE, not to transport. Everything the caller
    already knows (`news_id`) is defaulted and overwritten by the
    extractor, and every LLM-owned field is defaulted too, so one
    malformed verdict degrades to "that verdict is dropped" instead of
    failing the whole batch and losing the article's routing entirely.
    The processors enforce the real rules: known impact type, canonical
    ticker, confidence floor, non-empty rationale.

    `news_id` is in particular NOT the model's to decide - a 40-character
    sha1 is exactly the kind of opaque token a model mangles.
    """

    news_id: str = Field(default="")
    ticker: str = Field(default="", description="NSE ticker of the impacted stock")
    impact_type: str = Field(default="", description="DIRECTLY_IMPACTS | INDIRECTLY_IMPACTS")
    confidence: float = Field(default=0.0, description="0.0-1.0, enforced by the extractor")
    rationale: str = Field(default="", description="Causal rationale for the routing decision")
    shocked_entity_id: str | None = Field(
        default=None,
        description="Canonical commodity/macro/sector ID for 2-hop shocks",
    )

    @field_validator("news_id", mode="before")
    @classmethod
    def _coerce_news_id(cls, value: Any) -> str:
        """Accept a mangled (e.g. numeric) id without failing the batch."""
        return "" if value is None else str(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        """Accept an explicit null without failing the batch.

        A default only applies when a field is ABSENT; a model that emits
        `"confidence": null` would otherwise fail the whole batch.
        """
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


class InferredNewsMarketImpact(BaseModel):
    """Structured LLM output for MARKET-level news routing (no stock named).

    Most market-moving news does not name a tracked company: crude prices,
    the rupee, bond yields, a policy decision, a sector-wide move. Those
    articles are the ones that connect `:NewsEvent` to `:Commodity`,
    `:MacroFactor` and `:Sector` - without a market-level router they
    reach the graph as isolated nodes (BROAD_MARKET bucket) and the
    registry half of the ontology stays disconnected from news.

    `entity_id` must be a canonical registry ID; the extractor resolves it
    through CanonicalEntityResolver and drops it when unknown, so the model
    can never invent a node.
    """

    news_id: str = Field(default="")
    entity_id: str = Field(
        default="",
        description="Canonical registry ID: commodity, macro factor or sector",
    )
    impact_type: str = Field(
        default="",
        description="SHOCKS (commodity) | ALTERS_MACRO (macro) | IMPACTS_SECTOR (sector)",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(default="")

    @field_validator("news_id", mode="before")
    @classmethod
    def _coerce_news_id(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


class MacroFactorDetail(BaseModel):
    """Explainer card for a :MacroFactor node.

    Seeded from ontology_seed.yaml (description, why_it_moves,
    equity_transmission). The numeric series lives in TimescaleDB;
    the *why it changed* narrative arrives via macro news ingestion
    (MoSPI/RBI releases + :NewsEvent -[:ALTERS_MACRO]-> :MacroFactor).
    """

    id: str = Field(description="Canonical macro registry ID, e.g. INDIA_GDP_GROWTH")
    name: str | None = None
    unit: str | None = None
    description: str | None = None
    why_it_moves: str | None = Field(
        default=None, description="Drivers sourced from official releases + news"
    )
    equity_transmission: str | None = Field(
        default=None, description="How moves transmit to Indian equities"
    )
    default_scope: str | None = Field(
        default=None, description="BROAD (all stocks) | SELECTIVE (listed only)"
    )


class InferredNewsCorrelation(BaseModel):
    """Structured LLM output for NewsCorrelator L4 cross-news linking.

    As with `InferredNewsStockImpact`, the ids are plumbing the caller
    owns: `new_news_id` is set by the correlator and `prior_news_id` is
    validated against the candidate set. The model only judges the
    relationship, not the identity - so every field is defaulted and a
    malformed verdict is dropped individually rather than failing the
    whole batch.
    """

    new_news_id: str = Field(default="")
    prior_news_id: str = Field(default="")
    correlation_type: CorrelationType | None = Field(default=None)
    confidence: float = Field(default=0.0, description="0.0-1.0, enforced by the correlator")
    rationale: str = Field(default="")
    event_ts: int = Field(default=0, description="Set by the correlator, not the model")

    @field_validator("new_news_id", "prior_news_id", mode="before")
    @classmethod
    def _coerce_ids(cls, value: Any) -> str:
        """Accept a mangled (e.g. numeric) id without failing the batch."""
        return "" if value is None else str(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        """Accept an explicit null without failing the batch."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("event_ts", mode="before")
    @classmethod
    def _coerce_event_ts(cls, value: Any) -> int:
        """Accept an explicit null without failing the batch."""
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class InstitutionalDealItem(BaseModel):
    actor: str | None = None
    actor_category: str | None = None
    deal_type: str | None = None
    side: str | None = None
    qty: int | None = None
    value_cr: float | None = None
    event_date: str | None = None
    event_ts: int | None = None


class MFShiftItem(BaseModel):
    amc: str | None = None
    month: str | None = None
    delta_stake_pct: float | None = None
    valid_from_ts: int | None = None


class QuarterlySnapshotItem(BaseModel):
    quarter: str | None = None
    rev_yoy_pct: float | None = None
    ebitda_margin_pct: float | None = None
    pat_cr: float | None = None
    debt_to_equity: float | None = None
    fcf_cr: float | None = None
    promoter_pledge_pct: float | None = None
    valid_from_ts: int | None = None
    valid_to_ts: int | None = None
    is_latest: bool | None = None


class GuidanceChunkItem(BaseModel):
    id: str | None = None
    quarter: str | None = None
    concall_summary: str | None = None
    order_book_cr: float | None = None
    valid_from_ts: int | None = None
    valid_to_ts: int | None = None


class MonthlyAggregate(BaseModel):
    month: str
    min_close: float | None = None
    max_close: float | None = None
    mean_close: float | None = None


class DailyStockMetricItem(BaseModel):
    trade_date: str
    session_type: MarketSession = MarketSession.CLOSE
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: int | None = None
    delivery_qty: int | None = None
    delivery_pct: float | None = None
    delivery_20d_zscore: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ev_ebitda: float | None = None
    pe_5yr_percentile: float | None = None
    vendor_id: str | None = None
    vendor_as_of: datetime | None = None


class QuantSummary(BaseModel):
    vendor_id: str
    vendor_as_of: datetime | None = None
    row_count: int = 0
    latest_open: float | None = None
    latest_close: float | None = None
    latest_delivery_pct: float | None = None
    latest_pe: float | None = None
    pe_5yr_percentile: float | None = None
    monthly_aggregates: list[MonthlyAggregate] = Field(default_factory=list)


class StockDossierResponse(BaseModel):
    ticker: str
    window: Window
    start_ts: int
    end_ts: int
    direct_news: list[DirectNewsItem] = Field(default_factory=list)
    indirect_news: list[IndirectNewsItem] = Field(default_factory=list)
    institutional_deals: list[InstitutionalDealItem] = Field(default_factory=list)
    mf_shifts: list[MFShiftItem] = Field(default_factory=list)
    quarterly_snapshots: list[QuarterlySnapshotItem] = Field(default_factory=list)
    guidance_chunks: list[GuidanceChunkItem] = Field(default_factory=list)
    quant_summary: QuantSummary | None = None
