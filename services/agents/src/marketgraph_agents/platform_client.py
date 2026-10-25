"""Future REST transport interface, deliberately without an HTTP implementation."""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class PlatformClient(ABC):
    @abstractmethod
    async def claim(self) -> dict[str, Any] | None:
        """Claim using X-Agent-Key; user identity comes from the job."""
        raise NotImplementedError

    @abstractmethod
    async def heartbeat(self, job_id: UUID, lease: UUID) -> dict[str, Any]:
        """Extend a lease using X-Agent-Key and X-Job-Lease."""
        raise NotImplementedError

    @abstractmethod
    async def context(self, job_id: UUID, lease: UUID, ticker: str) -> dict[str, Any]:
        """Retrieve only the evidence authorized for this job."""
        raise NotImplementedError

    @abstractmethod
    async def complete(self, job_id: UUID, lease: UUID, result: dict[str, Any]) -> dict[str, Any]:
        """Commit a cited result through the Platform evidence contract."""
        raise NotImplementedError

    @abstractmethod
    async def fail(self, job_id: UUID, lease: UUID, retryable: bool) -> dict[str, Any]:
        """Report failure without exposing provider secrets."""
        raise NotImplementedError
