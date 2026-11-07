"""Translate Upstox quote and candle payloads into checkpoint observations."""

from datetime import UTC, date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.upstox.client import UpstoxClient


class UpstoxPriceCheckpointAdapter:
    def __init__(self, client: UpstoxClient) -> None:
        self._client = client

    async def fetch_checkpoint(
        self, instrument_key: str, trade_date: date, session: str, today: date
    ):
        metric = None
        if session == "OPEN" and trade_date == today:
            body = await self._client.get(
                "/market-quote/quotes", {"instrument_key": instrument_key}
            )
            quotes = list(body.get("data", {}).values())
            if len(quotes) == 1:
                record = quotes[0]
                stamp = float(record.get("last_trade_time", 0)) / 1000
                last_trade = (
                    datetime.fromtimestamp(stamp, UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
                )
                price = record.get("ohlc", {}).get("open")
                if last_trade == trade_date and price is not None:
                    metric = {
                        "open_price": price,
                        "close_price": record.get("last_price", price),
                        "volume": record.get("volume", 0),
                    }
        else:
            body = await self._client.get(
                f"/historical-candle/{quote(instrument_key, safe='')}/day/{trade_date.isoformat()}"
            )
            candles = [
                r
                for r in body.get("data", {}).get("candles", [])
                if datetime.fromisoformat(r[0]).date() == trade_date
            ]
            if candles:
                candle = candles[0]
                metric = {
                    "open_price": candle[1],
                    "close_price": candle[1] if session == "OPEN" else candle[4],
                    "volume": 0 if session == "OPEN" else candle[5],
                }
                if session == "CLOSE":
                    metric.update(high_price=candle[2], low_price=candle[3])
        return metric, body
