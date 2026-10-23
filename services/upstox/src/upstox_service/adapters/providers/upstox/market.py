"""Read-only Upstox market information and option-chain adapter.

All provider URLs and instrument keys stay inside the Data Service. The
credential-owning UpstoxClient is constructed and closed by the API lifespan.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from upstox_service.adapters.providers.upstox.client import UpstoxClient


class MarketInstrumentNotFound(ValueError):
    """No unambiguous official underlying matched a public identifier."""


class MarketInstrumentAmbiguous(ValueError):
    """The public identifier matches more than one official instrument."""


class MarketProductUnavailable(ValueError):
    """An official underlying has no currently listed option contracts."""


class UpstoxMarketProvider:
    def __init__(self, client: UpstoxClient):
        self._client = client

    async def resolve_underlying(self, query: str, exchange: str) -> dict[str, Any]:
        """Resolve an equity or index by official search; never invent a key."""
        body = await self._client.get(
            "/instruments/search",
            {"query": query, "exchanges": exchange, "segments": "EQ,INDEX", "records": 30},
        )
        rows = body.get("data", [])
        if not isinstance(rows, list):
            raise MarketInstrumentNotFound("Upstox returned no matching underlying")
        exact = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("segment") in {f"{exchange}_EQ", f"{exchange}_INDEX"}
            and row.get("instrument_key")
            and query.casefold()
            in {
                str(row.get(field, "")).casefold()
                for field in ("trading_symbol", "name", "short_name", "isin")
            }
        ]
        if len(exact) > 1:
            raise MarketInstrumentAmbiguous("Underlying matches multiple official instruments")
        if not exact:
            raise MarketInstrumentNotFound("No official equity or index matched the underlying")
        return exact[0]

    async def option_expiries(self, underlying: str, exchange: str) -> dict[str, Any]:
        instrument = await self.resolve_underlying(underlying, exchange)
        body = await self._client.get(
            "/option/contract", {"instrument_key": instrument["instrument_key"]}
        )
        rows = body.get("data", [])
        if not isinstance(rows, list):
            raise MarketProductUnavailable("Option contracts are unavailable for this underlying")
        expiries = sorted(
            {
                row["expiry"]
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("expiry"), str)
                and row.get("expiry")
            }
        )
        if not expiries:
            raise MarketProductUnavailable("No option expiries are listed for this underlying")
        return {
            "underlying": underlying.upper(),
            "exchange": exchange,
            "instrument_key": instrument["instrument_key"],
            "expiries": expiries,
        }

    async def option_chain(
        self, underlying: str, exchange: str, expiry: str
    ) -> dict[str, Any]:
        instrument = await self.resolve_underlying(underlying, exchange)
        body = await self._client.get(
            "/option/chain",
            {"instrument_key": instrument["instrument_key"], "expiry_date": expiry},
        )
        rows = body.get("data", [])
        if not isinstance(rows, list) or not rows:
            raise MarketProductUnavailable("No option chain is available for this expiry")
        return {
            "underlying": underlying.upper(),
            "exchange": exchange,
            "instrument_key": instrument["instrument_key"],
            "expiry": expiry,
            "strikes": rows,
        }

    async def smartlist(
        self,
        kind: str,
        *,
        asset_type: str | None,
        category: str | None,
        page_number: int,
        page_size: int,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"page_number": page_number, "page_size": page_size}
        if kind != "mtf":
            assert asset_type is not None and category is not None
            params.update(asset_type=asset_type, category=category)
        body = await self._client.get(f"/market/smartlist/{kind}", params)
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("smartlist"), list):
            raise MarketProductUnavailable("Upstox smartlist is unavailable")
        return data

    async def institutional_flows(
        self, investor: str, data_types: tuple[str, ...], interval: str, from_date: date | None
    ) -> dict[str, Any]:
        params = {"data_type": ",".join(data_types), "interval": interval}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        body = await self._client.get(f"/market/{investor.lower()}", params)
        data = body.get("data")
        if not isinstance(data, dict):
            raise MarketProductUnavailable("Institutional flow data is unavailable")
        return {"investor": investor, "interval": interval, "segments": data}

    async def holidays(self, for_date: date | None) -> Any:
        path = "/market/holidays"
        if for_date is not None:
            path += f"/{for_date.isoformat()}"
        body = await self._client.get(path)
        return body.get("data")

    async def exchange_status(self, exchange: str) -> dict[str, Any]:
        body = await self._client.get(f"/market/status/{exchange}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MarketProductUnavailable("Exchange status is unavailable")
        return data

    async def derivatives_analytics(
        self,
        metric: str,
        underlying: str,
        exchange: str,
        expiry: str,
        for_date: date,
        *,
        interval: int | None = None,
        bucket_interval: int | None = None,
    ) -> dict[str, Any]:
        instrument = await self.resolve_underlying(underlying, exchange)
        params: dict[str, str | int] = {
            "instrument_key": instrument["instrument_key"],
            "expiry": expiry,
            "date": for_date.isoformat(),
        }
        if interval is not None:
            params["interval"] = interval
        if bucket_interval is not None:
            params["bucket_interval"] = bucket_interval
        provider_metric = "change-oi" if metric == "change-oi" else metric
        body = await self._client.get(f"/market/{provider_metric}", params)
        data = body.get("data")
        if not isinstance(data, dict):
            raise MarketProductUnavailable("Derivatives analytics are unavailable")
        return {
            "metric": metric,
            "underlying": underlying.upper(),
            "exchange": exchange,
            "instrument_key": instrument["instrument_key"],
            "date": for_date.isoformat(),
            "data": data,
        }
