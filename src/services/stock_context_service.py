"""Stock Context Service (Milestone 3): read-only dossier orchestrator.

Merges one bounded FalkorDB temporal subgraph (Rule 3: window=LAST_6M |
LAST_1Y, canonical-only reads) with TimescaleDB quant checkpoints
(Rule 2: SQL-only numerics, every value cites vendor_id + vendor_as_of)
into a single `StockDossierResponse`.

Read-only: calls `aget_temporal_subgraph`, `get_daily_range`, and
`get_monthly_aggregates` only. No graph/SQL writes, no LLM calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Protocol

from src.domain.enums import MarketSession, Window
from src.domain.schemas import (
    DailyStockMetricItem,
    DirectNewsItem,
    GuidanceChunkItem,
    IndirectNewsItem,
    InstitutionalDealItem,
    MFShiftItem,
    MonthlyAggregate,
    QuantSummary,
    QuarterlySnapshotItem,
    StockDossierResponse,
    resolve_window,
)
from src.processors.entity_resolver import CanonicalEntityResolver

logger = logging.getLogger(__name__)

DEFAULT_SECTION_LIMIT = 50

_DIRECT_COLUMNS = (
    "id", "event_date", "event_ts", "headline", "summary",
    "category", "sentiment", "impact_type", "confidence", "rationale",
    "correlated_news_ids",
)
_INDIRECT_COLUMNS = (
    "id", "event_date", "event_ts", "via_node", "exposure_type",
    "margin_impact", "headline", "sentiment", "exposure_nature",
    "exposure_confidence", "exposure_rationale",
)
_DEALS_COLUMNS = (
    "actor", "actor_category", "deal_type", "side",
    "qty", "value_cr", "event_date", "event_ts",
)
_MF_COLUMNS = ("amc", "month", "delta_stake_pct", "valid_from_ts")
_GUIDANCE_COLUMNS = (
    "id", "quarter", "concall_summary", "order_book_cr", "valid_from_ts", "valid_to_ts",
)


class UnknownTickerError(ValueError):
    """Raised when a ticker is not in the canonical registry (Rule 4)."""


class FalkorDossierReader(Protocol):
    async def aget_temporal_subgraph(
        self, ticker: str, start_ts: int, end_ts: int, limit: int = DEFAULT_SECTION_LIMIT
    ) -> dict[str, list]: ...


class TimescaleDossierReader(Protocol):
    async def get_daily_range(
        self, ticker: str, start: date, end: date, session_type: str | None = None
    ) -> list[Any]: ...
    async def get_monthly_aggregates(self, ticker: str, window: Window) -> list[Any]: ...


def _row_to_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    """Map a driver row (tuple/list, Record, or dict) to a name->value dict."""
    if isinstance(row, dict):
        return {col: row.get(col) for col in columns}
    if hasattr(row, "keys"):
        try:
            keys = list(row.keys())
            if keys and all(isinstance(k, str) for k in keys):
                get = getattr(row, "__getitem__", None)
                if get is not None:
                    return {col: row[col] if col in keys else None for col in columns}
        except Exception:  # noqa: BLE001 - fall through to positional mapping
            pass
    try:
        values = list(row)
    except TypeError:
        values = [getattr(row, col, None) for col in columns]
    return {col: (values[i] if i < len(values) else None) for i, col in enumerate(columns)}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class StockContextService:
    """Core orchestrator merging FalkorDB + TimescaleDB into one dossier."""

    def __init__(self, falkor_repo, timescale_repo, resolver=None, section_limit=50):
        self._falkor = falkor_repo
        self._timescale = timescale_repo
        self._resolver = resolver or CanonicalEntityResolver.from_seed()
        self._section_limit = section_limit

    async def get_stock_dossier(self, ticker: str, window: Window) -> StockDossierResponse:
        canonical = self._resolver.resolve_stock(ticker or "")
        if canonical is None:
            raise UnknownTickerError(f"Unknown ticker {ticker!r}: not in registry")
        start_ts, end_ts = resolve_window(window)
        from src.repositories.timescale_repo import TimescaleRepository

        start_date, end_date = TimescaleRepository.window_dates(window)
        subgraph, daily_rows, monthly_rows = await asyncio.gather(
            self._falkor.aget_temporal_subgraph(canonical, start_ts, end_ts, self._section_limit),
            self._timescale.get_daily_range(canonical, start_date, end_date),
            self._timescale.get_monthly_aggregates(canonical, window),
        )
        return StockDossierResponse(
            ticker=canonical, window=window, start_ts=start_ts, end_ts=end_ts,
            direct_news=self._map_direct(subgraph.get("direct_news", [])),
            indirect_news=self._map_indirect(subgraph.get("indirect_news", [])),
            institutional_deals=self._map_deals(subgraph.get("institutional_deals", [])),
            mf_shifts=self._map_mf(subgraph.get("mf_shifts", [])),
            quarterly_snapshots=self._map_quarterly(subgraph.get("quarterly_snapshots", [])),
            guidance_chunks=self._map_guidance(subgraph.get("guidance_chunks", [])),
            quant_summary=self._build_quant(daily_rows, monthly_rows),
        )

    def _map_direct(self, rows: list[Any]) -> list[DirectNewsItem]:
        out = []
        for row in rows:
            d = _row_to_dict(row, _DIRECT_COLUMNS)
            c_ids = d.get("correlated_news_ids")
            if c_ids is None:
                c_ids = []
            elif isinstance(c_ids, str):
                c_ids = [c_ids]
            out.append(DirectNewsItem(
                id=str(d["id"]), event_date=d["event_date"],
                event_ts=_to_int(d["event_ts"]), headline=d["headline"],
                summary=d["summary"], category=d["category"],
                sentiment=_to_float(d["sentiment"]), impact_type=d["impact_type"],
                confidence=_to_float(d["confidence"]), rationale=d["rationale"],
                correlated_news_ids=list(c_ids)))
        return out

    def _map_indirect(self, rows: list[Any]) -> list[IndirectNewsItem]:
        out = []
        for row in rows:
            d = _row_to_dict(row, _INDIRECT_COLUMNS)
            out.append(IndirectNewsItem(
                id=str(d["id"]), event_date=d["event_date"],
                event_ts=_to_int(d["event_ts"]), via_node=d["via_node"],
                exposure_type=d["exposure_type"], margin_impact=d["margin_impact"],
                headline=d["headline"], sentiment=_to_float(d["sentiment"]),
                exposure_nature=d["exposure_nature"],
                exposure_confidence=_to_float(d["exposure_confidence"]),
                exposure_rationale=d["exposure_rationale"]))
        return out

    def _map_deals(self, rows: list[Any]) -> list[InstitutionalDealItem]:
        out = []
        for row in rows:
            d = _row_to_dict(row, _DEALS_COLUMNS)
            out.append(InstitutionalDealItem(
                actor=d["actor"], actor_category=d["actor_category"],
                deal_type=d["deal_type"], side=d["side"],
                qty=_to_int(d["qty"]), value_cr=_to_float(d["value_cr"]),
                event_date=d["event_date"], event_ts=_to_int(d["event_ts"])))
        return out

    def _map_mf(self, rows: list[Any]) -> list[MFShiftItem]:
        out = []
        for row in rows:
            d = _row_to_dict(row, _MF_COLUMNS)
            out.append(MFShiftItem(
                amc=d["amc"], month=d["month"],
                delta_stake_pct=_to_float(d["delta_stake_pct"]),
                valid_from_ts=_to_int(d["valid_from_ts"])))
        return out

    def _map_quarterly(self, rows: list[Any]) -> list[QuarterlySnapshotItem]:
        out = []
        for row in rows:
            props = row.get("props", row) if isinstance(row, dict) else {}
            if not props and not isinstance(row, dict):
                continue
            out.append(QuarterlySnapshotItem(
                quarter=props.get("quarter"),
                rev_yoy_pct=_to_float(props.get("rev_yoy_pct")),
                ebitda_margin_pct=_to_float(props.get("ebitda_margin_pct")),
                pat_cr=_to_float(props.get("pat_cr")),
                debt_to_equity=_to_float(props.get("debt_to_equity")),
                fcf_cr=_to_float(props.get("fcf_cr")),
                promoter_pledge_pct=_to_float(props.get("promoter_pledge_pct")),
                valid_from_ts=_to_int(props.get("valid_from_ts")),
                valid_to_ts=_to_int(props.get("valid_to_ts")),
                is_latest=props.get("is_latest")))
        return out

    def _map_guidance(self, rows: list[Any]) -> list[GuidanceChunkItem]:
        out = []
        for row in rows:
            d = _row_to_dict(row, _GUIDANCE_COLUMNS)
            out.append(GuidanceChunkItem(
                id=str(d["id"]) if d["id"] is not None else None,
                quarter=d["quarter"], concall_summary=d["concall_summary"],
                order_book_cr=_to_float(d["order_book_cr"]),
                valid_from_ts=_to_int(d["valid_from_ts"]),
                valid_to_ts=_to_int(d["valid_to_ts"])))
        return out

    def _build_quant(self, daily_rows: list[Any], monthly_rows: list[Any]):
        from src.domain.schemas import DailyStockMetricItem

        metrics: list[DailyStockMetricItem] = []
        for row in daily_rows or []:
            if isinstance(row, DailyStockMetricItem):
                metrics.append(row)
                continue
            if isinstance(row, dict):
                metrics.append(DailyStockMetricItem(
                    trade_date=str(row.get("trade_date") or ""),
                    session_type=row.get("session_type") or MarketSession.CLOSE,
                    close_price=_to_float(row.get("close_price")),
                    open_price=_to_float(row.get("open_price")),
                    delivery_pct=_to_float(row.get("delivery_pct")),
                    pe_ratio=_to_float(row.get("pe_ratio")),
                    pe_5yr_percentile=_to_float(row.get("pe_5yr_percentile")),
                    vendor_id=row.get("vendor_id"),
                    vendor_as_of=row.get("vendor_as_of")))
                continue
            td = getattr(row, "trade_date", "")
            metrics.append(DailyStockMetricItem(
                trade_date=td.isoformat() if hasattr(td, "isoformat") else str(td or ""),
                session_type=getattr(row, "session_type", MarketSession.CLOSE),
                close_price=_to_float(getattr(row, "close_price", None)),
                open_price=_to_float(getattr(row, "open_price", None)),
                delivery_pct=_to_float(getattr(row, "delivery_pct", None)),
                pe_ratio=_to_float(getattr(row, "pe_ratio", None)),
                pe_5yr_percentile=_to_float(getattr(row, "pe_5yr_percentile", None)),
                vendor_id=getattr(row, "vendor_id", None),
                vendor_as_of=getattr(row, "vendor_as_of", None)))
        aggregates = []
        for row in monthly_rows or []:
            if isinstance(row, MonthlyAggregate):
                aggregates.append(row)
            elif isinstance(row, dict):
                aggregates.append(MonthlyAggregate(
                    month=str(row.get("month")),
                    min_close=_to_float(row.get("min_close")),
                    max_close=_to_float(row.get("max_close")),
                    mean_close=_to_float(row.get("mean_close"))))
            else:
                aggregates.append(MonthlyAggregate(
                    month=str(getattr(row, "month", "")),
                    min_close=_to_float(getattr(row, "min_close", None)),
                    max_close=_to_float(getattr(row, "max_close", None)),
                    mean_close=_to_float(getattr(row, "mean_close", None))))
        if not metrics and not aggregates:
            return None
        opens = [m for m in metrics if m.session_type == MarketSession.OPEN]
        closes = [m for m in metrics if m.session_type == MarketSession.CLOSE]
        latest_close = closes[-1] if closes else None
        latest_open = opens[-1] if opens else None
        anchor = latest_close or latest_open
        if anchor is None:
            return QuantSummary(vendor_id="unknown", row_count=len(metrics),
                                monthly_aggregates=aggregates)
        open_px = None
        if latest_open is not None:
            open_px = latest_open.close_price if latest_open.close_price is not None else latest_open.open_price
        return QuantSummary(
            vendor_id=anchor.vendor_id or "unknown", vendor_as_of=anchor.vendor_as_of,
            row_count=len(metrics), latest_open=open_px,
            latest_close=latest_close.close_price if latest_close else None,
            latest_delivery_pct=(latest_close.delivery_pct if latest_close
                                 else anchor.delivery_pct),
            latest_pe=latest_close.pe_ratio if latest_close else anchor.pe_ratio,
            pe_5yr_percentile=(latest_close.pe_5yr_percentile if latest_close
                               else anchor.pe_5yr_percentile),
            monthly_aggregates=aggregates)
