"""Internal caller authentication and per-user read-only broker isolation."""

from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from upstox_service.adapters.api.main import create_app
from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient
from upstox_service.config.settings import Settings


class Cache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value

    async def eval(self, *args):
        return 1


def test_data_boundary_is_failclosed_and_health_is_available():
    app = create_app(AsyncMock(), Cache(), Settings(_env_file=None))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/entities").status_code == 401
        assert client.get("/api/v1/entities", headers={"X-Internal-Service-Key": "wrong"}).status_code == 401
    config = Settings(_env_file=None).model_copy(update={"internal_service_key": SecretStr("")})
    with TestClient(create_app(AsyncMock(), Cache(), config)) as client:
        assert client.get("/api/v1/entities").status_code == 503
        assert client.get("/openapi.json").status_code == 200


def test_personal_market_clients_and_caches_are_isolated(monkeypatch):
    import upstox_service.adapters.api.credentials as module
    calls = []

    class Client:
        def __init__(self, token, **kwargs):
            self.token = token.get_secret_value()

        async def get(self, path, params=None):
            calls.append((self.token, path))
            if self.token == "rejected":
                raise ProviderError("rejected", status_code=401)
            return {"data": {"exchange": "NSE", "status": "OPEN" if self.token == "one" else "CLOSED"}}

        async def close(self):
            pass

    monkeypatch.setattr(module, "UpstoxClient", Client)
    cache = Cache()
    app = create_app(AsyncMock(), cache, Settings(_env_file=None))
    with TestClient(app, headers={"X-Internal-Service-Key": "test-internal-key"}) as client:
        for token, expected in (("one", "OPEN"), ("two", "CLOSED")):
            headers = {"X-Upstox-Access-Token": token, "X-MarketGraph-Credential-Scope": f"{uuid4()}:1"}
            response = client.get("/api/v1/market/status/NSE", headers=headers)
            assert response.status_code == 200
            assert response.json()["data"]["status"] == expected
            assert client.get("/api/v1/market/status/NSE", headers=headers).status_code == 200
        bad = {"X-Upstox-Access-Token": "rejected", "X-MarketGraph-Credential-Scope": f"{uuid4()}:2"}
        response = client.get("/api/v1/market/status/NSE", headers=bad)
        assert response.status_code == 401 and "broker_reconnect_required" in response.json()["detail"]
        assert client.post("/api/v1/stocks", json={"query": "TCS"}, headers=bad).status_code == 403
        assert client.get("/api/v1/market/status/NSE", headers={"X-Upstox-Access-Token": "one"}).status_code == 422
    assert len(calls) == 3
    assert len(cache.values) == 2
    assert all("one" not in key and "two" not in key for key in cache.values)


def test_token_validation_never_returns_the_credential(monkeypatch):
    import upstox_service.adapters.api.main as module

    class Client:
        def __init__(self, token, **kwargs):
            self.token = token.get_secret_value()

        async def get(self, path, params=None):
            assert path == "/market-quote/quotes"
            if self.token == "bad":
                raise ProviderError("rejected", status_code=401)
            if self.token == "temporary":
                raise ProviderError("unavailable", retryable=True)
            return {"data": {}}

        async def close(self):
            pass

    app = create_app(AsyncMock(), Cache(), Settings(_env_file=None))
    monkeypatch.setattr(module, "UpstoxClient", Client)
    with TestClient(app, headers={"X-Internal-Service-Key": "test-internal-key"}) as client:
        path = "/internal/v1/upstox/validate-credential"
        response = client.post(path, json={"access_token": "sensitive-value"})
        assert response.status_code == 200
        assert "sensitive-value" not in response.text
        assert response.json()["trading_enabled"] is False
        assert client.post(path, json={"access_token": "bad"}).status_code == 401
        assert client.post(path, json={"access_token": "temporary"}).status_code == 503
        oversized = "private-token" * 1000
        invalid = client.post(path, json={"access_token": oversized})
        assert invalid.status_code == 422 and "private-token" not in invalid.text


async def test_provider_budget_is_bound_to_actual_credential_and_failclosed():
    budget = AsyncMock()
    budget.eval.return_value = 2
    client = UpstoxClient(SecretStr("sensitive"), redis_client=budget, requests_per_minute=1)
    try:
        import pytest
        with pytest.raises(ProviderError, match="budget exceeded"):
            await client.get("/market/status/NSE")
        assert "sensitive" not in budget.eval.await_args.args[2]
    finally:
        await client.close()


async def test_personal_stock_reads_never_write_shared_provider_data(monkeypatch):
    from datetime import UTC, date, datetime

    from upstox_service.application import stock_data as module
    repo = AsyncMock()
    repo.get_instrument.return_value = {"trading_symbol": "TCS", "isin": "isin", "instrument_key": "NSE_EQ|isin", "source_as_of": datetime.now(UTC)}
    repo.is_registered.return_value = True
    provider = AsyncMock()
    provider.fetch_profile.return_value = {"business_summary": "Personal provider result"}
    provider.fetch_shareholding.return_value = [{"period": "Sep 2026", "category": "promoters", "percentage": 60}]
    provider.fetch_daily_candles.return_value = [{"trade_date": date(2026, 1, 1), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    monkeypatch.setattr(module, "StockDataRepository", lambda unused: repo)
    service = module.StockDataService(object(), provider, persist_provider_results=False)
    assert (await service.stock("TCS", "NSE"))["profile"]["business_summary"] == "Personal provider result"
    assert (await service.shareholding("TCS", "NSE"))["periods"][0]["promoters"] == 60
    assert len((await service.candles("TCS", "NSE", date(2026, 1, 1), date(2026, 1, 1)))["candles"]) == 1
    repo.save_profile.assert_not_called()
    repo.save_shareholding.assert_not_called()
    repo.save_candles.assert_not_called()
    repo.upsert_instrument.assert_not_called()
