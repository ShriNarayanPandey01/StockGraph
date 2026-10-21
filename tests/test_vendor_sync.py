"""Test vendor sync protocol, watermark advancement, vintage immutability & 2-row normalization (Rule 7)."""

import pytest
from datetime import date, datetime, timezone
from src.ingestion.chart_vendor_adapter import (
    CLOSE_SERIES,
    OPEN_SERIES,
    MockChartProviderAdapter,
    VendorSyncService,
    payload_hash,
    to_eod_bar,
)


class _FakeTimescaleRepo:
    def __init__(self):
        self.watermarks: dict[tuple[str, str, str], date] = {}
        self.raw_quotes: list[dict] = []
        self.daily_metrics: list[dict] = []

    async def get_watermark(self, vendor_id: str, ticker: str, series: str) -> date | None:
        return self.watermarks.get((vendor_id, ticker, series))

    async def advance_watermark(self, vendor_id: str, ticker: str, series: str, last_date: date) -> None:
        self.watermarks[(vendor_id, ticker, series)] = last_date

    async def stage_vendor_quote(self, vendor_id: str, ticker: str, trade_date: date, series: str, payload: dict, fetched_at=None) -> None:
        ts = fetched_at or datetime.now(timezone.utc)
        self.raw_quotes.append({
            "vendor_id": vendor_id,
            "ticker": ticker,
            "trade_date": trade_date,
            "series": series,
            "payload": payload,
            "fetched_at": ts,
        })

    async def get_latest_vintages(self, vendor_id: str, ticker: str, start: date, end: date) -> list[dict]:
        # Emulate DISTINCT ON (vendor_id, ticker, trade_date, series) ... ORDER BY fetched_at DESC
        filtered = [
            r for r in self.raw_quotes
            if r["vendor_id"] == vendor_id and r["ticker"] == ticker and start <= r["trade_date"] <= end
        ]
        filtered.sort(key=lambda r: r["fetched_at"], reverse=True)
        seen = set()
        out = []
        for r in filtered:
            key = (r["vendor_id"], r["ticker"], r["trade_date"], r["series"])
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    async def upsert_daily_metrics(self, rows: list[dict]) -> int:
        self.daily_metrics.extend(rows)
        return len(rows)


def test_payload_hash_stability():
    p1 = {"trade_date": "2026-10-15", "close": 150.0, "volume": 1000}
    p2 = {"volume": 1000, "close": 150.0, "trade_date": "2026-10-15"}
    assert payload_hash(p1) == payload_hash(p2)


def test_to_eod_bar_parsing():
    raw = {"trade_date": "2026-10-15", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 5000}
    bar = to_eod_bar(raw)
    assert bar is not None
    assert bar.trade_date == date(2026, 10, 15)
    assert bar.open_price == 100.0
    assert bar.close_price == 102.0
    assert bar.volume == 5000


@pytest.mark.asyncio
async def test_sync_advances_watermark():
    repo = _FakeTimescaleRepo()
    service = VendorSyncService(repo)
    data = {
        "TATASTEEL": [
            {"trade_date": date(2026, 10, 10), "open": 140.0, "close": 142.0, "volume": 1000},
            {"trade_date": date(2026, 10, 11), "open": 142.0, "close": 145.0, "volume": 1200},
        ]
    }
    adapter = MockChartProviderAdapter(data)

    res = await service.sync_ticker(adapter, "TATASTEEL", CLOSE_SERIES, date(2026, 10, 10), date(2026, 10, 11))
    assert res.staged_count == 2
    assert res.new_watermark == date(2026, 10, 11)
    assert repo.watermarks.get((adapter.vendor_id, "TATASTEEL", CLOSE_SERIES)) == date(2026, 10, 11)

    # Next sync from earlier start date does NOT regress watermark and does not duplicate
    res2 = await service.sync_ticker(adapter, "TATASTEEL", CLOSE_SERIES, date(2026, 10, 10), date(2026, 10, 11))
    assert res2.staged_count == 0


@pytest.mark.asyncio
async def test_revision_sweep_stages_new_vintage_without_moving_watermark():
    repo = _FakeTimescaleRepo()
    service = VendorSyncService(repo)
    t1 = date(2026, 10, 10)
    data_initial = {
        "TATASTEEL": [{"trade_date": t1, "open": 140.0, "close": 142.0, "volume": 1000}]
    }
    adapter = MockChartProviderAdapter(data_initial)

    await service.sync_ticker(adapter, "TATASTEEL", CLOSE_SERIES, t1, t1)
    assert len(repo.raw_quotes) == 1
    assert repo.raw_quotes[0]["payload"]["close"] == 142.0

    # Revision arrives: close adjusted to 142.50
    adapter.data["TATASTEEL"] = [{"trade_date": t1, "open": 140.0, "close": 142.50, "volume": 1000}]
    revisions = await service.check_revisions(adapter, "TATASTEEL", CLOSE_SERIES, end=t1, lookback_days=5)
    assert revisions == 1
    assert len(repo.raw_quotes) == 2

    # Latest vintage query resolves to the revised price
    vintages = await repo.get_latest_vintages(adapter.vendor_id, "TATASTEEL", t1, t1)
    assert len(vintages) == 1
    assert vintages[0]["payload"]["close"] == 142.50


@pytest.mark.asyncio
async def test_normalization_produces_two_rows_per_day_with_provenance():
    repo = _FakeTimescaleRepo()
    service = VendorSyncService(repo)
    t1 = date(2026, 10, 10)
    await service.stage_raw(
        vendor_id="vendor-test",
        ticker="TATASTEEL",
        trade_date=t1,
        series=CLOSE_SERIES,
        payload={"trade_date": t1, "open": 140.0, "high": 145.0, "low": 139.0, "close": 144.0, "volume": 50000, "delivery_pct": 45.5},
        fetched_at=datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc),
    )

    count = await service.normalize_ticker("TATASTEEL", t1, t1, "vendor-test")
    assert count == 2
    assert len(repo.daily_metrics) == 2

    open_row = next(r for r in repo.daily_metrics if r["session_type"] == OPEN_SERIES.split("_")[1])
    close_row = next(r for r in repo.daily_metrics if r["session_type"] == CLOSE_SERIES.split("_")[1])

    assert open_row["session_type"] == "OPEN"
    assert open_row["close_price"] == 140.0  # Opening price checkpoint
    assert open_row["vendor_id"] == "vendor-test"
    assert open_row["vendor_as_of"] is not None

    assert close_row["session_type"] == "CLOSE"
    assert close_row["close_price"] == 144.0
    assert close_row["delivery_pct"] == 45.5
    assert close_row["vendor_id"] == "vendor-test"
    assert close_row["vendor_as_of"] is not None
