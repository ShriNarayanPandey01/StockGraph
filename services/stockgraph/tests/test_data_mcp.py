"""Contract checks for the SQL-owned read-only Data MCP wrapper."""
import pytest
from stockgraph.adapters.api import data_mcp


@pytest.mark.asyncio
async def test_financials_uses_data_rest(monkeypatch):
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, params))
        return {"source": "sql"}

    monkeypatch.setattr(data_mcp, "_get", fake_get)
    assert await data_mcp.get_stock_financial_history("RELIANCE", "LAST_1Y") == {"source": "sql"}
    assert calls == [("/api/v1/stocks/RELIANCE/financials", {"window": "LAST_1Y"})]


@pytest.mark.asyncio
async def test_candles_use_supported_date_parameters(monkeypatch):
    calls = []

    async def fake_get(path, params=None):
        calls.append((path, params))
        return {"candles": []}

    monkeypatch.setattr(data_mcp, "_get", fake_get)
    await data_mcp.get_stock_candles("INFY", "2026-01-01", "2026-02-01")
    assert calls == [("/api/v1/stocks/INFY/candles", {
        "from": "2026-01-01", "to": "2026-02-01"
    })]


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker,window", [("../bad", "LAST_6M"), ("INFY", "ALL_TIME")])
async def test_invalid_financial_arguments(ticker, window):
    with pytest.raises(ValueError):
        await data_mcp.get_stock_financial_history(ticker, window)


@pytest.mark.asyncio
async def test_invalid_candle_dates():
    with pytest.raises(ValueError):
        await data_mcp.get_stock_candles("INFY", "2026-02-01", "2026-01-01")
    with pytest.raises(ValueError):
        await data_mcp.get_stock_candles("INFY", "not-a-date")
