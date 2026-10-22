"""HTTP anti-corruption boundary; no cross-service Python imports or database access."""

from typing import Any

import httpx


class DataServiceClient:
    def __init__(self, base_url: str, transport: Any | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        async with httpx.AsyncClient(
            base_url=self._base_url, transport=self._transport, timeout=30
        ) as client:
            response = await client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()

    async def register_stock(self, payload: dict) -> dict:
        return await self.request("POST", "/api/v1/stocks", payload)

    async def job_status(self, job_id: str) -> dict:
        return await self.request("GET", f"/api/v1/jobs/{job_id}")
