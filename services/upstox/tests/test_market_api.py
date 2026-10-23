"""Offline contract checks for read-only Upstox market endpoints."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from upstox_service.adapters.api.market_routes import create_market_router
from upstox_service.adapters.providers.upstox.client import ProviderError
from upstox_service.adapters.providers.upstox.market import (
    MarketInstrumentAmbiguous,
    MarketInstrumentNotFound,
    UpstoxMarketProvider,
)


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key] = value
        self.ttls[key] = ex


def app_with(provider, cache=None):
    app = FastAPI()
    app.include_router(create_market_router(provider, cache or MemoryRedis(), live_ttl_seconds=15))
    return app


@pytest.mark.asyncio
async def test_provider_resolves_index_and_equity_without_inventing_instrument_keys():
    client = AsyncMock()
    client.get.return_value = {
        "data": [
            {"trading_symbol": "NIFTY", "name": "Nifty 50", "segment": "NSE_INDEX",
             "instrument_key": "NSE_INDEX|Nifty 50"},
            {"trading_symbol": "NIFTY", "name": "Other", "segment": "BSE_INDEX",
             "instrument_key": "BSE_INDEX|Other"},
        ]
    }
    provider = UpstoxMarketProvider(client)
    assert (await provider.resolve_underlying("NIFTY", "NSE"))["instrument_key"] == "NSE_INDEX|Nifty 50"
    assert client.get.await_args.args[1]["segments"] == "EQ,INDEX"
    with pytest.raises(MarketInstrumentNotFound):
        await provider.resolve_underlying("UNKNOWN", "NSE")
    client.get.return_value = {"data": [
        {"trading_symbol": "ABC", "segment": "NSE_EQ", "instrument_key": "NSE_EQ|1"},
        {"trading_symbol": "ABC", "segment": "NSE_INDEX", "instrument_key": "NSE_INDEX|ABC"},
    ]}
    with pytest.raises(MarketInstrumentAmbiguous):
        await provider.resolve_underlying("ABC", "NSE")


@pytest.mark.asyncio
async def test_provider_uses_documented_option_and_analytics_paths():
    client = AsyncMock()
    client.get.side_effect = [
        {"data": [{"trading_symbol": "NIFTY", "segment": "NSE_INDEX",
                   "instrument_key": "NSE_INDEX|Nifty 50"}]},
        {"data": [{"expiry": "2030-01-31"}, {"expiry": "2030-01-31"},
                  {"expiry": "2030-02-28"}]},
        {"data": [{"trading_symbol": "NIFTY", "segment": "NSE_INDEX",
                   "instrument_key": "NSE_INDEX|Nifty 50"}]},
        {"data": {"total_put_change_oi": 12}},
    ]
    provider = UpstoxMarketProvider(client)
    expiries = await provider.option_expiries("NIFTY", "NSE")
    assert expiries["expiries"] == ["2030-01-31", "2030-02-28"]
    assert client.get.await_args_list[1].args == (
        "/option/contract", {"instrument_key": "NSE_INDEX|Nifty 50"}
    )
    result = await provider.derivatives_analytics(
        "change-oi", "NIFTY", "NSE", "2030-01-31", date(2026, 5, 7), interval=2
    )
    assert result["data"]["total_put_change_oi"] == 12
    assert client.get.await_args_list[3].args == (
        "/market/change-oi",
        {"instrument_key": "NSE_INDEX|Nifty 50", "expiry": "2030-01-31",
         "date": "2026-05-07", "interval": 2},
    )


def test_smartlist_validation_caching_and_provider_timestamp():
    provider = AsyncMock()
    provider.smartlist.return_value = {
        "asset_type": "INDEX", "category": "TOP_TRADED", "metric_key": "total_traded_value",
        "time_stamp": 1780045636752, "smartlist": [{"instrument_key": "NSE_FO|62329"}],
        "page_number": 1, "page_size": 20, "total_pages": 2,
    }
    cache = MemoryRedis()
    with TestClient(app_with(provider, cache)) as client:
        url = "/api/v1/market/smartlists/futures?asset_type=INDEX&category=TOP_TRADED"
        first = client.get(url)
        second = client.get(url)
        assert client.get("/api/v1/market/smartlists/mtf?category=TOP_TRADED").status_code == 422
        assert client.get(
            "/api/v1/market/smartlists/options?asset_type=COMMODITY&category=IV_GAINERS"
        ).status_code == 422
        assert client.get(
            "/api/v1/market/smartlists/futures?asset_type=INDEX&category=PREMIUM&page_size=51"
        ).status_code == 422
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["source"] == "UPSTOX"
    assert first.json()["provider_as_of"] is not None
    provider.smartlist.assert_awaited_once()
    assert list(cache.ttls.values()) == [15]


def test_flow_segments_and_market_routes_are_read_only():
    provider = AsyncMock()
    provider.institutional_flows.return_value = {
        "investor": "FII", "interval": "1D",
        "segments": {"NSE_FO|INDEX_OPTIONS": [{"time_stamp": 1780045636752, "buy_amount": 10}]},
    }
    provider.exchange_status.return_value = {
        "exchange": "NSE", "status": "NORMAL_OPEN", "last_updated": 1780045636752
    }
    provider.holidays.return_value = [{"date": "2026-10-02", "description": "Holiday"}]
    with TestClient(app_with(provider)) as client:
        flow = client.get(
            "/api/v1/market/institutional-flows?investor=FII&segment=NSE_FO%7CINDEX_OPTIONS"
        )
        assert flow.status_code == 200
        assert flow.json()["provider_as_of"] is not None
        assert client.get(
            "/api/v1/market/institutional-flows?investor=DII&segment=NSE_FO%7CINDEX_OPTIONS"
        ).status_code == 422
        assert client.get("/api/v1/market/status/NSE").json()["data"]["status"] == "NORMAL_OPEN"
        assert client.get("/api/v1/market/status/FAKE").status_code == 422
        assert client.get("/api/v1/market/holidays").json()["data"][0]["date"] == "2026-10-02"
        assert client.get("/api/v1/market/nonexistent").status_code == 404


def test_option_and_analytics_validation_and_dated_cache():
    provider = AsyncMock()
    provider.option_expiries.return_value = {
        "underlying": "NIFTY", "exchange": "NSE", "instrument_key": "NSE_INDEX|Nifty 50",
        "expiries": ["2030-01-31"],
    }
    provider.option_chain.return_value = {
        "underlying": "NIFTY", "exchange": "NSE", "instrument_key": "NSE_INDEX|Nifty 50",
        "expiry": "2030-01-31", "strikes": [{"strike_price": 25000}],
    }
    provider.derivatives_analytics.return_value = {
        "metric": "pcr", "underlying": "NIFTY", "exchange": "NSE",
        "instrument_key": "NSE_INDEX|Nifty 50", "date": "2026-05-07",
        "data": {"pcr": 0.8},
    }
    cache = MemoryRedis()
    with TestClient(app_with(provider, cache)) as client:
        assert client.get("/api/v1/option-chains/expiries?underlying=NIFTY").status_code == 200
        assert client.get(
            "/api/v1/option-chains?underlying=NIFTY&expiry=2030-01-31"
        ).json()["data"]["strikes"][0]["strike_price"] == 25000
        assert client.get("/api/v1/option-chains?underlying=NIFTY&expiry=2020-01-01").status_code == 422
        url = "/api/v1/market/pcr?underlying=NIFTY&expiry=2030-01-31&date=2026-05-07"
        assert client.get(url).status_code == 200
        assert client.get(url).status_code == 200
        assert client.get(url + "&interval=2").status_code == 422
    assert provider.derivatives_analytics.await_count == 1
    assert provider.derivatives_analytics.await_args.kwargs["bucket_interval"] == 60
    assert 3600 in cache.ttls.values()


def test_provider_failures_are_safe_and_distinct():
    provider = AsyncMock()
    provider.exchange_status.side_effect = ProviderError("private-token", status_code=403)
    with TestClient(app_with(provider)) as client:
        result = client.get("/api/v1/market/status/NSE")
    assert result.status_code == 503
    assert "private-token" not in result.text
    provider.exchange_status.side_effect = ProviderError("upstream", status_code=404)
    with TestClient(app_with(provider)) as client:
        assert client.get("/api/v1/market/status/NSE").status_code == 404
    provider.exchange_status.side_effect = ProviderError("upstream", status_code=429, retryable=True)
    with TestClient(app_with(provider)) as client:
        assert client.get("/api/v1/market/status/NSE").status_code == 503
