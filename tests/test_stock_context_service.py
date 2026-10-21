"""Milestone 3: StockContextService with mock repos (no live DB)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.enums import MarketSession, Window
from src.domain.schemas import DailyStockMetricItem, MonthlyAggregate
from src.services.stock_context_service import StockContextService, UnknownTickerError


class FakeFalkor:
    def __init__(self, subgraph: dict[str, list] | None = None):
        self.calls: list[tuple] = []
        self.subgraph = subgraph if subgraph is not None else {
            "direct_news": [("n1", "2026-10-01", 100, "RBI holds rate", "Summary",
                             "MACRO", 0.5, "DIRECTLY_IMPACTS", 0.9, "Why")],
            "indirect_news": [("n2", "2026-10-02", 101, "HRC_STEEL",
                               "EXPOSED_TO", "NEGATIVE", "Steel up", 0.2,
                               "input cost", 0.8, "Because")],
            "institutional_deals": [("HDFC MF", "MUTUAL_FUND", "BULK", "BUY",
                                     1000, 12.5, "2026-10-03", 102)],
            "mf_shifts": [("HDFC AMC", "2026-09", 0.15, 103)],
            "quarterly_snapshots": [{"props": {"quarter": "Q2FY26", "pat_cr": 100.0,
                                               "valid_from_ts": 1, "valid_to_ts": 9999999999,
                                               "is_latest": True}}],
            "guidance_chunks": [("g1", "Q2FY26", "Demand strong", 500.0, 1)],
        }

    async def aget_temporal_subgraph(self, ticker, start_ts, end_ts, limit=50):
        self.calls.append((ticker, start_ts, end_ts, limit))
        return self.subgraph


class FakeTimescale:
    def __init__(self, daily: list[Any] | None = None, monthly: list[Any] | None = None):
        as_of = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
        self.daily = daily if daily is not None else [
            DailyStockMetricItem(trade_date="2026-10-16", session_type=MarketSession.OPEN,
                                 open_price=150.0, close_price=151.0,
                                 vendor_id="upstox", vendor_as_of=as_of),
            DailyStockMetricItem(trade_date="2026-10-16", session_type=MarketSession.CLOSE,
                                 close_price=152.5, delivery_pct=55.5, pe_ratio=18.0,
                                 pe_5yr_percentile=62.0,
                                 vendor_id="bhavcopy", vendor_as_of=as_of),
        ]
        self.monthly = monthly if monthly is not None else [
            MonthlyAggregate(month="2026-10", min_close=140.0, max_close=155.0, mean_close=148.0)]

    async def get_daily_range(self, ticker, start, end, session_type=None):
        return self.daily

    async def get_monthly_aggregates(self, ticker, window):
        return self.monthly


def _svc(**kw):
    return StockContextService(FakeFalkor(kw.get("subgraph")), FakeTimescale(kw.get("daily"), kw.get("monthly")))


async def test_dossier_maps_all_sections_with_provenance():
    d = await _svc().get_stock_dossier("tatasteel", Window.LAST_6M)
    assert d.ticker == "TATASTEEL" and d.start_ts < d.end_ts
    assert d.direct_news[0].id == "n1" and d.direct_news[0].impact_type == "DIRECTLY_IMPACTS"
    assert d.direct_news[0].correlated_news_ids == []
    assert d.indirect_news[0].via_node == "HRC_STEEL"
    assert d.indirect_news[0].exposure_type == "EXPOSED_TO"
    assert d.institutional_deals[0].actor == "HDFC MF"
    assert d.mf_shifts[0].amc == "HDFC AMC"
    assert d.quarterly_snapshots[0].quarter == "Q2FY26"
    assert d.guidance_chunks[0].id == "g1"
    q = d.quant_summary
    assert q.vendor_id == "bhavcopy" and q.vendor_as_of is not None
    assert q.latest_open == 151.0 and q.latest_close == 152.5
    assert q.latest_delivery_pct == 55.5 and q.row_count == 2
    assert q.monthly_aggregates[0].month == "2026-10"


async def test_dossier_window_bounds_flow_to_falkor():
    falkor, ts = FakeFalkor(), FakeTimescale()
    svc = StockContextService(falkor, ts)
    d = await svc.get_stock_dossier("RELIANCE", Window.LAST_1Y)
    assert falkor.calls and falkor.calls[0][0] == "RELIANCE"
    assert falkor.calls[0][1] == d.start_ts and falkor.calls[0][2] == d.end_ts


async def test_dossier_empty_window_returns_empty_sections():
    svc = _svc(subgraph={"direct_news": [], "indirect_news": [], "institutional_deals": [],
                         "mf_shifts": [], "quarterly_snapshots": [], "guidance_chunks": []},
               daily=[], monthly=[])
    d = await svc.get_stock_dossier("INFY", Window.LAST_6M)
    assert d.direct_news == [] and d.quant_summary is None


async def test_unknown_ticker_raises():
    with pytest.raises(UnknownTickerError):
        await _svc().get_stock_dossier("NOPE", Window.LAST_6M)
