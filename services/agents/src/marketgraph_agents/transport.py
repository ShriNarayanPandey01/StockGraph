"""Scoped Platform REST access for a single leased job."""

import asyncio
from uuid import UUID

import httpx

from marketgraph_agents.platform_client import PlatformClient


class PlatformCallError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


class HttpPlatformClient(PlatformClient):
    def __init__(self, base_url: str, service_key: str, *, client=None):
        self._owned = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=15,
                                                    headers={'X-Agent-Key': service_key})

    async def _request(self, method, path, *, lease=None, params=None, body=None):
        headers = {'X-Job-Lease': str(lease)} if lease else None
        response = None
        for attempt in range(2 if method == 'GET' else 1):
            try:
                response = await self._client.request(method, path, headers=headers, params=params, json=body)
                if response.status_code < 500 or attempt:
                    break
            except httpx.HTTPError:
                if method != 'GET' or attempt:
                    raise PlatformCallError(503, 'Platform service unavailable') from None
            await asyncio.sleep(0.2)
        if response is None:
            raise PlatformCallError(503, 'Platform service unavailable')
        if not response.is_success:
            try:
                detail = response.json().get('detail', 'Platform request failed')
            except ValueError:
                detail = 'Platform request failed'
            raise PlatformCallError(response.status_code, detail if isinstance(detail, str) else 'Platform request failed')
        return response.json() if response.content else None

    async def claim(self):
        return await self._request('POST', '/internal/v1/agent/jobs/claim',
                                   params={'developer_only': 'true', 'contract_version': 2})

    async def worker_heartbeat(self, worker_id, enabled):
        return await self._request('POST', '/internal/v1/agent/workers/heartbeat',
                                   body={'worker_id': str(worker_id), 'enabled': enabled})

    async def heartbeat(self, job_id: UUID, lease: UUID):
        return await self._request('POST', f'/internal/v1/agent/jobs/{job_id}/heartbeat', lease=lease)

    async def context(self, job_id: UUID, lease: UUID, ticker: str, as_of_ts=None):
        params = {'limit': 50}
        if as_of_ts is not None:
            params['as_of_ts'] = as_of_ts
        return await self._request('GET', f'/internal/v1/agent/jobs/{job_id}/context/{ticker}',
                                   lease=lease, params=params)

    async def documents(self, job_id, lease, ticker, question):
        return await self._request('GET', f'/internal/v1/agent/jobs/{job_id}/documents/{ticker}',
                                   lease=lease, params={'q': question[:200], 'limit': 10})

    async def candidates(self, job_id, lease, offset=0):
        return await self._request('GET', f'/internal/v1/agent/jobs/{job_id}/candidates',
                                   lease=lease, params={'limit': 100, 'offset': offset})

    async def history(self, job_id, lease):
        return await self._request('GET', f'/internal/v1/agent/jobs/{job_id}/conversation', lease=lease)

    async def baseline(self, job_id, lease):
        return await self._request('GET', f'/internal/v1/agent/jobs/{job_id}/monitor-baseline', lease=lease)

    async def reserve(self, job_id, lease, body):
        return await self._request('POST', f'/internal/v1/agent/jobs/{job_id}/model-reservations', lease=lease, body=body)

    async def settle(self, job_id, lease, reservation_id, body):
        return await self._request('POST', f'/internal/v1/agent/jobs/{job_id}/model-reservations/{reservation_id}/settle',
                                   lease=lease, body=body)

    async def complete(self, job_id: UUID, lease: UUID, result):
        return await self._request('POST', f'/internal/v2/agent/jobs/{job_id}/complete', lease=lease, body=result)

    async def fail(self, job_id: UUID, lease: UUID, retryable: bool, reason='failure'):
        return await self._request('POST', f'/internal/v1/agent/jobs/{job_id}/fail', lease=lease,
                                   body={'retryable': retryable, 'reason': reason})

    async def close(self):
        if self._owned:
            await self._client.aclose()
