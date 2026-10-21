"""API request/response Pydantic models for the Stock Dossier (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.domain.enums import CorrelationType, MarketSession, OntologyRelationType, Window

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
    revenue_segments: list[str] = Field(default_factory=list)
    raw_material_inputs: list[str] = Field(default_factory=list)
    geographic_exposure: str | None = None
    latest_quarter_summary: str | None = None
    latest_guidance_highlights: list[str] = Field(default_factory=list)
    active_exposures: list[str] = Field(
        default_factory=list,
        description="Canonical registry IDs the stock is currently linked to",
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
    margin_impact: str | None = Field(
        default=None, description="POSITIVE | NEGATIVE | MIXED"
    )
    sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    valid_from_ts: int | None = None


class InferredNewsStockImpact(BaseModel):
    """Structured LLM output for NewsGraphExtractor 1-hop/2-hop routing."""

    news_id: str
    ticker: str = Field(description="NSE ticker of the impacted stock")
    impact_type: str = Field(
        description="DIRECTLY_IMPACTS | INDIRECTLY_IMPACTS"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Causal rationale for the routing decision")
    shocked_entity_id: str | None = Field(
        default=None,
        description="Canonical commodity/macro/sector ID for 2-hop shocks",
    )


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
    """Structured LLM output for NewsCorrelator L4 cross-news linking."""

    new_news_id: str
    prior_news_id: str
    correlation_type: CorrelationType
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    event_ts: int


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
