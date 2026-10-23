"""Read-through stock information backed only by the Data Service's SQL store."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.upstox.client import ProviderError
from upstox_service.adapters.repositories.timescale.stock_data import StockDataRepository


class StockNotFound(LookupError):
    pass


class InvalidCursor(ValueError):
    pass


def _encode_cursor(query: str, exchange: str | None, item: dict) -> str:
    payload = [query, exchange, item["exchange"], item["trading_symbol"], item["instrument_key"]]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, query: str, exchange: str | None) -> tuple[str, str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
        if (
            not isinstance(values, list) or len(values) != 5
            or values[0] != query or values[1] != exchange
            or not all(isinstance(value, str) for value in values[2:])
        ):
            raise ValueError("invalid cursor")
        return tuple(values[2:])
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise InvalidCursor("Cursor does not match the stock query") from exc


async def refresh_equity_universe(repository, provider) -> dict[str, int]:
    """Scheduler hook: fetch both BOD files before atomically replacing active rows."""
    rows = await provider.fetch_equity_universe()
    return await StockDataRepository(repository).refresh_universe(rows)


class StockDataService:
    def __init__(self, repository, provider):
        self._repo = StockDataRepository(repository)
        self._provider = provider

    async def list_stocks(
        self, query: str = "", exchange: str | None = None,
        cursor: str | None = None, limit: int = 50,
    ) -> dict:
        normalized = query.strip()
        after = _decode_cursor(cursor, normalized, exchange) if cursor else None
        rows = await self._repo.search_instruments(normalized, exchange, after, limit + 1)
        items = rows[:limit]
        return {
            "items": items,
            "next_cursor": _encode_cursor(normalized, exchange, items[-1])
            if len(rows) > limit else None,
        }

    async def _instrument(self, ticker: str, exchange: str) -> dict:
        instrument = await self._repo.get_instrument(ticker, exchange)
        if instrument is not None:
            return instrument
        try:
            resolved = await self._provider.resolve(ticker, exchange)
        except ProviderError as exc:
            if "No official equity" in str(exc):
                raise StockNotFound("No equity matched this symbol and exchange") from exc
            raise
        if resolved["trading_symbol"].upper() != ticker.upper():
            raise StockNotFound("No equity matched this symbol and exchange")
        await self._repo.upsert_instrument(resolved)
        found = await self._repo.get_instrument(ticker, exchange)
        if found is None:
            raise StockNotFound("Resolved instrument could not be loaded")
        return found

    async def stock(self, ticker: str, exchange: str) -> dict:
        instrument = await self._instrument(ticker, exchange)
        cached = await self._repo.get_profile(instrument["isin"])
        if cached is None or cached["vendor_as_of"] < datetime.now(UTC) - timedelta(days=1):
            profile = await self._provider.fetch_profile(instrument["isin"])
            now = datetime.now(UTC)
            await self._repo.save_profile(instrument["isin"], profile, now)
            cached = {"profile": profile, "vendor_id": "UPSTOX", "vendor_as_of": now}
        return {
            **instrument,
            "registered": await self._repo.is_registered(
                instrument["trading_symbol"], instrument["isin"]
            ),
            "profile": cached["profile"],
            "vendor_id": cached["vendor_id"],
            "vendor_as_of": cached["vendor_as_of"],
        }

    async def shareholding(self, ticker: str, exchange: str) -> dict:
        instrument = await self._instrument(ticker, exchange)
        stored = await self._repo.get_shareholding(instrument["isin"])
        if (
            stored["vendor_as_of"] is None
            or stored["vendor_as_of"] < datetime.now(UTC) - timedelta(days=1)
        ):
            rows = await self._provider.fetch_shareholding(instrument["isin"])
            now = datetime.now(UTC)
            await self._repo.save_shareholding(instrument["isin"], rows, now)
            stored = await self._repo.get_shareholding(instrument["isin"])
        periods: dict[str, dict] = {}
        for row in stored["rows"]:
            values = periods.setdefault(row["period"], {"period": row["period"], "breakdown": {}})
            values["breakdown"][row["category"]] = float(row["percentage"])
        for values in periods.values():
            breakdown = values["breakdown"]
            values["promoters"] = breakdown.get("promoters")
            values["fii"] = breakdown.get("fii")
            values["dii"] = round(
                breakdown.get("other_dii", 0) + breakdown.get("mutual_funds", 0), 4
            )
            values["public"] = breakdown.get("retail_and_other")
        return {
            "exchange": exchange,
            "ticker": instrument["trading_symbol"],
            "isin": instrument["isin"],
            "vendor_id": "UPSTOX",
            "vendor_as_of": stored["vendor_as_of"],
            "periods": sorted(
                periods.values(),
                key=lambda item: datetime.strptime(item["period"], "%b %Y"),
                reverse=True,
            ),
        }

    async def candles(
        self, ticker: str, exchange: str, start: date | None, end: date | None,
    ) -> dict:
        instrument = await self._instrument(ticker, exchange)
        completed_through = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)
        last = min(end or completed_through, completed_through)
        first = start or last - timedelta(days=365)
        if first > last:
            raise ValueError("No completed daily candles exist in the requested range")
        if (last - first).days > 3652:
            raise ValueError("Daily candle range cannot exceed ten years")
        if not await self._repo.has_candle_coverage(exchange, instrument["isin"], first, last):
            # Keep each provider request well below Upstox's decade/day limit.
            candles = []
            chunk_start = first
            while chunk_start <= last:
                chunk_end = min(chunk_start + timedelta(days=5 * 365), last)
                candles.extend(await self._provider.fetch_daily_candles(
                    instrument["instrument_key"], chunk_start, chunk_end
                ))
                chunk_start = chunk_end + timedelta(days=1)
            await self._repo.save_candles(
                exchange, instrument["isin"], first, last, candles, datetime.now(UTC)
            )
        return {
            "exchange": exchange,
            "ticker": instrument["trading_symbol"],
            "isin": instrument["isin"],
            "from_date": first,
            "to_date": last,
            "vendor_id": "UPSTOX",
            "candles": await self._repo.get_candles(exchange, instrument["isin"], first, last),
        }
