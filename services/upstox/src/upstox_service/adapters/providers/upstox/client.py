"""Small read-only Upstox client. Credentials never escape this adapter."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import SecretStr


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class UpstoxClient:
    def __init__(
        self,
        token: SecretStr,
        *,
        base_url: str = "https://api.upstox.com/v2",
        timeout: float = 30,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.__token = token
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict | None = None) -> Any:
        if not self.__token.get_secret_value():
            raise ProviderError("UPSTOX_ANALYTICS_TOKEN is not configured")
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    self._base_url + path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + self.__token.get_secret_value(),
                        "Accept": "application/json",
                    },
                )
            except httpx.TransportError:
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError("Upstox transport unavailable", retryable=True) from None
            if response.status_code in (401, 403):
                raise ProviderError(
                    "Upstox authorization rejected; check token and endpoint entitlement",
                    status_code=response.status_code,
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                raise ProviderError(
                    f"Upstox temporarily unavailable (HTTP {response.status_code})",
                    retryable=True,
                    status_code=response.status_code,
                )
            if response.status_code != 200:
                raise ProviderError(
                    f"Upstox endpoint unavailable (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except ValueError:
                raise ProviderError("Upstox returned invalid JSON") from None
            if body.get("status") != "success":
                raise ProviderError("Upstox returned an unsuccessful response")
            return body
        raise ProviderError("Upstox unavailable", retryable=True)
