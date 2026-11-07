"""Background registration orchestration; API requests never wait for providers."""

import asyncio

from upstox_service.application.errors import ProviderError
from upstox_service.application.ports import CompanyProviderPort, RegistrationJobPort
from upstox_service.domain.models import StockRegistration


class StockRegistrationSubmissionService:
    def __init__(self, jobs: RegistrationJobPort) -> None:
        self._jobs = jobs

    async def submit(self, request: StockRegistration) -> dict:
        return await self._jobs.create_job(request)


class RegistrationWorker:
    def __init__(
        self,
        repository: RegistrationJobPort,
        provider: CompanyProviderPort,
        *,
        max_attempts: int = 3,
        lease_seconds: int = 600,
    ):
        self._repository = repository
        self._provider = provider
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        job = await self._repository.claim_job(self._lease_seconds, self._max_attempts)
        if job is None:
            return False
        provider_task = None
        heartbeat = None

        async def renew():
            while True:
                await asyncio.sleep(max(1, self._lease_seconds // 3))
                if not await self._repository.renew_job(
                    job["job_id"], job["attempts"], self._lease_seconds
                ):
                    raise RuntimeError("Registration worker lost its lease")

        try:
            request = StockRegistration.model_validate(job["request"])
            provider_task = asyncio.create_task(self._provider.fetch_company(request))
            heartbeat = asyncio.create_task(renew())
            done, _ = await asyncio.wait(
                {provider_task, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                await heartbeat  # Lost lease or SQL unavailable: never commit stale data.
            company = await provider_task
            await self._repository.commit_company(job["job_id"], company, attempt=job["attempts"])
        except ProviderError as exc:
            await self._repository.fail_job(
                job["job_id"],
                str(exc),
                exc.retryable and job["attempts"] < self._max_attempts,
                attempt=job["attempts"],
            )
        except Exception:
            # Never expose exception reprs containing request/token/connection details.
            await self._repository.fail_job(
                job["job_id"],
                "Data collection or commit failed",
                job["attempts"] < self._max_attempts,
                attempt=job["attempts"],
            )
        finally:
            tasks = [task for task in (provider_task, heartbeat) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return True
