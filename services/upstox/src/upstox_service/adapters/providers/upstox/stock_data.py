"""Equity universe, company fundamentals, and completed daily chart candles."""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime
from urllib.parse import quote

import httpx

from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient
from upstox_service.adapters.providers.upstox.company import UpstoxCompanyProvider

_BOD_URLS = {
    "NSE": "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "BSE": "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
}


class UpstoxStockDataProvider:
    """Composes authenticated v2/v3 clients; the BOD file is public."""

    def __init__(
        self,
        v2_client: UpstoxClient,
        v3_client: UpstoxClient,
        *,
        bod_transport: httpx.AsyncBaseTransport | None = None,
        bod_timeout: float = 60,
    ) -> None:
        self._v2 = v2_client
        self._v3 = v3_client
        self._company = UpstoxCompanyProvider(v2_client)
        self._bod = httpx.AsyncClient(timeout=bod_timeout, transport=bod_transport)

    async def close(self) -> None:
        await self._bod.aclose()

    async def fetch_equity_universe(self) -> list[dict]:
        """Read both official daily files; return only active equity instruments."""
        instruments: list[dict] = []
        for exchange, url in _BOD_URLS.items():
            try:
                response = await self._bod.get(url)
                response.raise_for_status()
                content = response.content
                if content.startswith(b"\x1f\x8b"):
                    content = gzip.decompress(content)
                rows = json.loads(content)
            except (httpx.HTTPError, OSError, ValueError) as exc:
                raise ProviderError(f"{exchange} equity universe unavailable", retryable=True) from exc
            if not isinstance(rows, list):
                raise ProviderError(f"{exchange} equity universe malformed")
            # NSE labels cash equities ``EQ``. BSE supplies its equity group
            # classification (A/B/X/...) instead, while retaining ``BSE_EQ``
            # as the authoritative segment. Applying the NSE type predicate to
            # BSE would silently discard the whole BSE equity universe.
            exchange_rows = [
                row for row in rows
                if isinstance(row, dict)
                and row.get("segment") == f"{exchange}_EQ"
                and (exchange == "BSE" or row.get("instrument_type") == "EQ")
                and all(row.get(key) for key in ("trading_symbol", "isin", "instrument_key"))
            ]
            if not exchange_rows:
                raise ProviderError(f"{exchange} equity universe has no valid stocks")
            instruments.extend(exchange_rows)
        return instruments

    async def resolve(self, ticker: str, exchange: str) -> dict:
        return await self._company.resolve(ticker, exchange)

    async def fetch_profile(self, isin: str) -> dict:
        body = await self._v2.get(f"/fundamentals/{quote(isin, safe='')}/profile")
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("company_profile"), str):
            raise ProviderError("Upstox company profile is unavailable")
        return {
            "business_summary": data["company_profile"],
            "sector": data.get("sector"),
            "sector_market_cap_inr": data.get("sector_market_cap_inr"),
            "sector_market_cap_usd": data.get("sector_market_cap_usd"),
            "prospectus_links": await self._company.fetch_prospectus_links(isin),
        }

    async def fetch_shareholding(self, isin: str) -> list[dict]:
        body = await self._v2.get(f"/fundamentals/{quote(isin, safe='')}/share-holdings")
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderError("Upstox shareholding response is malformed")
        rows: list[dict] = []
        for category in data:
            if not isinstance(category, dict) or not isinstance(category.get("history"), list):
                raise ProviderError("Upstox shareholding response is malformed")
            name = str(category.get("category", "")).lower()
            if not name:
                raise ProviderError("Upstox shareholding category is missing")
            for entry in category["history"]:
                try:
                    period = str(entry["period"])
                    datetime.strptime(period, "%b %Y")
                    value = float(entry["value"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError("Upstox shareholding history is malformed") from exc
                if not 0 <= value <= 100:
                    raise ProviderError("Upstox shareholding percentage is invalid")
                rows.append({"period": period, "category": name, "percentage": value})
        return rows

    async def fetch_daily_candles(
        self, instrument_key: str, from_date: date, to_date: date
    ) -> list[dict]:
        path = (
            f"/historical-candle/{quote(instrument_key, safe='')}/days/1/"
            f"{to_date.isoformat()}/{from_date.isoformat()}"
        )
        body = await self._v3.get(path)
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("candles"), list):
            raise ProviderError("Upstox historical candle response is malformed")
        candles: list[dict] = []
        for row in data["candles"]:
            try:
                if not isinstance(row, list) or len(row) < 6:
                    raise ValueError("missing candle fields")
                trade_date = datetime.fromisoformat(row[0]).date()
                if not from_date <= trade_date <= to_date:
                    continue
                candle = {
                    "trade_date": trade_date,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": int(row[5]),
                }
                if candle["volume"] < 0 or candle["high"] < candle["low"]:
                    raise ValueError("invalid daily candle")
            except (ValueError, TypeError, IndexError) as exc:
                raise ProviderError("Upstox historical candle response is malformed") from exc
            candles.append(candle)
        return sorted(candles, key=lambda candle: candle["trade_date"])
