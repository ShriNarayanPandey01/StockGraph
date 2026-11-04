"""Equity directory and SQL-only stock data reads."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from upstox_service.adapters.api.stock_routes import create_stock_router
from upstox_service.adapters.providers.upstox.client import ProviderError
from upstox_service.adapters.providers.upstox.company import UpstoxCompanyProvider
from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider
from upstox_service.adapters.repositories.timescale.stock_data import StockDataRepository
from upstox_service.application import stock_data as stock_module
from upstox_service.domain.equity import is_company_equity

NOW = datetime.now(UTC)
INSTRUMENT = {
    "exchange": "NSE",
    "segment": "NSE_EQ",
    "instrument_type": "EQ",
    "instrument_key": "NSE_EQ|INE002A01018",
    "trading_symbol": "RELIANCE",
    "isin": "INE002A01018",
    "name": "Reliance Industries",
    "short_name": "Reliance",
    "source_as_of": NOW,
}


@pytest.mark.asyncio
async def test_bod_refresh_filters_derivatives_and_requires_both_exchanges():
    def handler(request):
        exchange = "NSE" if "NSE.json.gz" in str(request.url) else "BSE"
        rows = [
            {
                **INSTRUMENT,
                "exchange": exchange,
                "segment": f"{exchange}_EQ",
                "instrument_type": "A" if exchange == "BSE" else "EQ",
            },
            {"segment": f"{exchange}_FO", "instrument_type": "FUT", "trading_symbol": "X"},
            # Both exchanges label ETFs as cash equities. BSE also includes
            # fixed-income, government securities and closed-ended funds.
            {**INSTRUMENT, "exchange": exchange, "segment": f"{exchange}_EQ",
             "instrument_type": "B" if exchange == "BSE" else "EQ",
             "trading_symbol": "NIFTYBEES", "isin": "INF204KB14I2"},
        ]
        if exchange == "BSE":
            rows.extend([
                {**INSTRUMENT, "exchange": exchange, "segment": "BSE_EQ",
                 "instrument_type": "F", "trading_symbol": "07ABB", "isin": "INF204KB15Q2"},
                {**INSTRUMENT, "exchange": exchange, "segment": "BSE_EQ",
                 "instrument_type": "F", "trading_symbol": "001HCCL29", "isin": "INE549A08963"},
                {**INSTRUMENT, "exchange": exchange, "segment": "BSE_EQ",
                 "instrument_type": "G", "trading_symbol": "0795GOI32", "isin": "INY020020106"},
            ])
        return httpx.Response(200, content=gzip.compress(json.dumps(rows, default=str).encode()))

    provider = UpstoxStockDataProvider(
        AsyncMock(), AsyncMock(), bod_transport=httpx.MockTransport(handler)
    )
    try:
        rows = await provider.fetch_equity_universe()
    finally:
        await provider.close()
    assert len(rows) == 2
    assert {row["segment"] for row in rows} == {"NSE_EQ", "BSE_EQ"}
    assert {row["instrument_type"] for row in rows} == {"EQ", "A"}


@pytest.mark.parametrize("group", ["A", "B", "T", "X", "XT", "Z", "P", "ZP", "M", "MT", "MS", "TS"])
def test_bse_company_shares_keep_all_supported_trading_groups(group):
    assert is_company_equity({**INSTRUMENT, "exchange": "BSE", "segment": "BSE_EQ",
                              "instrument_type": group})


@pytest.mark.parametrize("exchange,kind,isin", [
    ("NSE", "EQ", "INF204KB14I2"),
    ("BSE", "B", "INF204KB14I2"),
    ("BSE", "F", "INF204KB15Q2"),
    ("BSE", "F", "INE549A08963"),
    ("BSE", "G", "INY020020106"),
    ("BSE", "IF", "INE041025011"),
])
@pytest.mark.asyncio
async def test_funds_and_debt_cannot_be_resolved_or_cached_as_stocks(exchange, kind, isin):
    instrument = {**INSTRUMENT, "exchange": exchange, "segment": f"{exchange}_EQ",
                  "instrument_type": kind, "isin": isin}
    client = AsyncMock()
    client.get.return_value = {"data": [instrument]}
    with pytest.raises(ProviderError, match="No official equity"):
        await UpstoxCompanyProvider(client).resolve("RELIANCE", exchange)
    repository = AsyncMock()
    with pytest.raises(ValueError, match="company equity"):
        await StockDataRepository(repository).upsert_instrument(instrument)
    repository.connect.assert_not_awaited()


def test_listed_asset_manager_is_a_stock_even_when_name_contains_mutual_fund():
    assert is_company_equity({**INSTRUMENT, "name": "An asset manager / mutual fund business"})


@pytest.mark.asyncio
async def test_bod_refresh_fails_without_second_exchange():
    def handler(request):
        if "BSE.json.gz" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, content=gzip.compress(json.dumps([INSTRUMENT], default=str).encode()))

    provider = UpstoxStockDataProvider(
        AsyncMock(), AsyncMock(), bod_transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ProviderError, match="BSE equity universe unavailable"):
            await provider.fetch_equity_universe()
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_provider_normalizes_shareholding_and_v3_daily_candles():
    v2 = AsyncMock()
    v3 = AsyncMock()
    v2.get.side_effect = [
        {"data": {"company_profile": "Energy and retail", "sector": "Refineries"}},
        {"data": []},
        {"data": []},
        {"data": []},
        {"data": []},
        {"data": [
            {"category": "promoters", "history": [{"period": "Mar 2026", "value": 50.0}]},
            {"category": "fii", "history": [{"period": "Mar 2026", "value": 18.67}]},
        ]},
    ]
    v3.get.return_value = {
        "data": {"candles": [["2026-10-21T00:00:00+05:30", 100, 110, 95, 107, 12345, 0]]}
    }
    provider = UpstoxStockDataProvider(v2, v3)
    try:
        assert (await provider.fetch_profile(INSTRUMENT["isin"]))["business_summary"] == (
            "Energy and retail"
        )
        shares = await provider.fetch_shareholding(INSTRUMENT["isin"])
        candles = await provider.fetch_daily_candles(
            INSTRUMENT["instrument_key"], date(2026, 10, 1), date(2026, 10, 22)
        )
    finally:
        await provider.close()
    assert shares == [
        {"period": "Mar 2026", "category": "promoters", "percentage": 50.0},
        {"period": "Mar 2026", "category": "fii", "percentage": 18.67},
    ]
    assert candles[0]["volume"] == 12345
    assert candles[0]["trade_date"] == date(2026, 10, 21)
    assert v2.get.await_args_list[5].args[0].endswith("/share-holdings")
    assert v3.get.await_args.args[0] == (
        "/historical-candle/NSE_EQ%7CINE002A01018/days/1/2026-10-22/2026-10-01"
    )


@pytest.mark.asyncio
async def test_cursor_pagination_is_bound_to_query_and_exchange(monkeypatch):
    repository = AsyncMock()
    repository.search_instruments.side_effect = [
        [{**INSTRUMENT, "registered": False},
         {**INSTRUMENT, "trading_symbol": "TCS", "registered": True}],
        [],
    ]
    monkeypatch.setattr(stock_module, "StockDataRepository", lambda _: repository)
    service = stock_module.StockDataService(AsyncMock(), AsyncMock())
    first = await service.list_stocks("Re", "NSE", limit=1)
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    second = await service.list_stocks("Re", "NSE", first["next_cursor"], 1)
    assert second["items"] == []
    assert repository.search_instruments.await_args_list[1].args[2] == (
        "NSE", "RELIANCE", INSTRUMENT["instrument_key"]
    )
    with pytest.raises(stock_module.InvalidCursor):
        await service.list_stocks("Tc", "NSE", first["next_cursor"], 1)


@pytest.mark.asyncio
async def test_unregistered_stock_read_persists_profile_without_registration(monkeypatch):
    repository = AsyncMock()
    repository.get_instrument.return_value = INSTRUMENT
    repository.get_profile.return_value = None
    repository.is_registered.return_value = False
    monkeypatch.setattr(stock_module, "StockDataRepository", lambda _: repository)
    provider = AsyncMock()
    provider.fetch_profile.return_value = {
        "business_summary": "Energy and retail", "sector": "Refineries"
    }
    original_repository = AsyncMock()
    service = stock_module.StockDataService(original_repository, provider)
    detail = await service.stock("RELIANCE", "NSE")
    assert detail["registered"] is False
    assert detail["profile"]["business_summary"] == "Energy and retail"
    repository.save_profile.assert_awaited_once()
    original_repository.create_job.assert_not_called()
    original_repository.commit_company.assert_not_called()


@pytest.mark.asyncio
async def test_shareholding_groups_categories_and_keeps_provenance(monkeypatch):
    repository = AsyncMock()
    repository.get_instrument.return_value = INSTRUMENT
    repository.get_shareholding.return_value = {
        "vendor_as_of": NOW,
        "rows": [
            {"period": "Mar 2026", "category": "promoters", "percentage": 50},
            {"period": "Mar 2026", "category": "fii", "percentage": 18},
            {"period": "Mar 2026", "category": "other_dii", "percentage": 10},
            {"period": "Mar 2026", "category": "mutual_funds", "percentage": 9},
            {"period": "Mar 2026", "category": "retail_and_other", "percentage": 13},
        ],
    }
    monkeypatch.setattr(stock_module, "StockDataRepository", lambda _: repository)
    service = stock_module.StockDataService(AsyncMock(), AsyncMock())
    result = await service.shareholding("RELIANCE", "NSE")
    assert result["periods"][0]["dii"] == 19
    assert result["periods"][0]["public"] == 13
    assert result["vendor_id"] == "UPSTOX"
    repository.save_shareholding.assert_not_awaited()


@pytest.mark.asyncio
async def test_candles_backfill_in_chunks_and_use_sql_cache(monkeypatch):
    repository = AsyncMock()
    repository.get_instrument.return_value = INSTRUMENT
    repository.has_candle_coverage.side_effect = [False, True]
    repository.get_candles.return_value = []
    monkeypatch.setattr(stock_module, "StockDataRepository", lambda _: repository)
    provider = AsyncMock()
    provider.fetch_daily_candles.return_value = []
    service = stock_module.StockDataService(AsyncMock(), provider)
    end = datetime.now(UTC).date() - timedelta(days=2)
    start = end - timedelta(days=6 * 365)
    await service.candles("RELIANCE", "NSE", start, end)
    await service.candles("RELIANCE", "NSE", start, end)
    assert provider.fetch_daily_candles.await_count == 2
    assert repository.save_candles.await_count == 1


def test_stock_routes_validate_exchange_and_candle_dates():
    app = FastAPI()
    app.include_router(create_stock_router(AsyncMock(), AsyncMock()))
    with TestClient(app) as client:
        assert client.get("/api/v1/stocks?exchange=MCX").status_code == 422
        assert client.get("/api/v1/stocks/TCS?exchange=MCX").status_code == 422
        assert client.get("/api/v1/stocks/TCS/candles?from=broken").status_code == 422
