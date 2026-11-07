"""NSE Bhavcopy source for checkpoint ingestion."""

import asyncio
from datetime import date

from upstox_service.adapters.providers.exchanges.bhavcopy import parse_bhavcopy_csv
from upstox_service.adapters.providers.http_client import ResilientHttpClient


class NseBhavcopyAdapter:
    def __init__(self, client: ResilientHttpClient) -> None:
        self._client = client

    async def fetch(self, trade_date: date) -> dict[str, dict]:
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{trade_date:%d%m%Y}.csv"
        outcome = await asyncio.to_thread(self._client.fetch, url)
        if outcome.ok and outcome.text:
            try:
                return {r["SYMBOL"].strip(): r for r in parse_bhavcopy_csv(outcome.text).rows}
            except ValueError:
                pass
        return {}
