"""Small read-only Upstox client. Credentials never escape this adapter."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import httpx
from pydantic import SecretStr

from upstox_service.application.errors import ProviderError


class UpstoxClient:
    def __init__(
        self,
        token: SecretStr,
        *,
        base_url: str = "https://api.upstox.com/v2",
        timeout: float = 30,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        redis_client=None,
        requests_per_minute: int = 120,
    ):
        self.__token = token
        self._redis = redis_client
        self._requests_per_minute = requests_per_minute
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def _reserve_request(self):
        # Same credential has one budget across API replicas, workers and users.
        identity = hashlib.sha256(self.__token.get_secret_value().encode()).hexdigest()
        key = f"upstox:credential-budget:v1:{identity}:{int(time.time()) // 60}"
        try:
            count = await self._redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n",
                1, key,
            )
            if int(count) > self._requests_per_minute:
                raise ProviderError("Upstox credential request budget exceeded", retryable=True, status_code=429)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("Upstox credential budget unavailable", retryable=True) from None

    async def get(self, path: str, params: dict | None = None) -> Any:
        if not self.__token.get_secret_value():
            raise ProviderError("UPSTOX_ANALYTICS_TOKEN is not configured")
        for attempt in range(self._max_retries + 1):
            if self._redis is not None:
                await self._reserve_request()
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
