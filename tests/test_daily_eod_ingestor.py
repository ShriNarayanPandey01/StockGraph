"""Test 7:00 PM IST Daily EOD Bhavcopy & numerics ingestion (Rule 7)."""

import pytest
from datetime import date
from src.ingestion.chart_vendor_adapter import MockChartProviderAdapter
from src.ingestion.daily_eod_ingestor import DailyEodIngestor
from src.ingestion.source_adapter import FetchOutcome, ResilientHttpClient


SAMPLE_BHAVCOPY_CSV = (
    "SYMBOL, SERIES, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER\n"
    "TATASTEEL, EQ, 150.00, 153.00, 149.00, 152.00, 1000000, 600000, 60.00\n"
    "RELIANCE, EQ, 2800.00, 2850.00, 2790.00, 2840.00, 500000, 350000, 70.00\n"
)


class _FakeTimescale:
    def __init__(self):
        self.raw_quotes = []
        self.daily_metrics = []
        self.macro_rows = []
        self.runs = []
        self.watermarks = {}

    async def record_ingest_run(self, job_name, status, started_at=None, finished_at=None, error=None):
        run_id = len(self.runs) + 1
        self.runs.append({"id": run_id, "name": job_name, "status": status})
        return run_id

    async def update_ingest_run(self, run_id, status, finished_at=None, error=None):
        for r in self.runs:
            if r["id"] == run_id:
                r["status"] = status
                r["error"] = error

    async def stage_vendor_quote(self, vendor_id, ticker, trade_date, series, payload, fetched_at=None):
        self.raw_quotes.append({
            "vendor_id": vendor_id,
            "ticker": ticker,
            "trade_date": trade_date,
            "series": series,
            "payload": payload,
            "fetched_at": fetched_at or trade_date,
        })

    async def get_latest_vintages(self, vendor_id, ticker, start, end):
        return [
            r for r in self.raw_quotes
            if r["vendor_id"] == vendor_id and r["ticker"] == ticker and start <= r["trade_date"] <= end
        ]

    async def upsert_daily_metrics(self, rows):
        self.daily_metrics.extend(rows)
        return len(rows)

    async def upsert_macro_and_flows(self, rows):
        self.macro_rows.extend(rows)
        return len(rows)

    async def get_watermark(self, vendor_id, ticker, series):
        return self.watermarks.get((vendor_id, ticker, series))

    async def advance_watermark(self, vendor_id, ticker, series, last_date):
        self.watermarks[(vendor_id, ticker, series)] = last_date


@pytest.mark.asyncio
async def test_daily_eod_bhavcopy_primary_flow():
    timescale = _FakeTimescale()
    vendor = MockChartProviderAdapter()
    vendor.macro_data = [
        {"trade_date": date(2026, 10, 18), "brent_crude_usd": 78.5, "usd_inr": 84.15}
    ]

    ingestor = DailyEodIngestor(
        timescale_repo=timescale,
        vendor_adapter=vendor,
    )

    t_date = date(2026, 10, 18)
    res = await ingestor.run_eod(
        trade_date=t_date,
        active_tickers=["TATASTEEL"],
        bhavcopy_csv_text=SAMPLE_BHAVCOPY_CSV,
    )

    assert res.status == "COMPLETED"
    assert res.tickers_normalized == 1
    assert res.macro_synced is True
    assert res.vendor_used == "NSE_BHAVCOPY"

    # Verify 2 rows in daily_stock_metrics (OPEN and CLOSE)
    assert len(timescale.daily_metrics) == 2
    close_row = next(r for r in timescale.daily_metrics if r["session_type"] == "CLOSE")
    assert close_row["close_price"] == 152.00
    assert close_row["delivery_pct"] == 60.00
    assert close_row["vendor_id"] == "NSE_BHAVCOPY"

    assert len(timescale.macro_rows) == 1
    assert timescale.macro_rows[0]["brent_crude_usd"] == 78.5


@pytest.mark.asyncio
async def test_daily_eod_fallback_to_bse():
    timescale = _FakeTimescale()

    # Mock HTTP client where NSE fails but BSE succeeds
    class _FailingNSEClient(ResilientHttpClient):
        def fetch(self, url: str) -> FetchOutcome:
            if "nseindia" in url:
                return FetchOutcome(ok=False, status=403, error="Akamai 403 blocked")
            return FetchOutcome(ok=True, status=200, text=SAMPLE_BHAVCOPY_CSV)

    ingestor = DailyEodIngestor(
        timescale_repo=timescale,
        http_client=_FailingNSEClient(),
    )

    t_date = date(2026, 10, 18)
    res = await ingestor.run_eod(trade_date=t_date, active_tickers=["TATASTEEL"])

    assert res.status == "COMPLETED"
    assert res.vendor_used == "BSE_FALLBACK"
    assert timescale.runs[-1]["status"] == "COMPLETED"
