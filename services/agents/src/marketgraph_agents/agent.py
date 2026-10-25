"""Contract for future agent handlers; no concrete handler is provided."""

from abc import ABC, abstractmethod
from typing import Any


class Agent(ABC):
    @abstractmethod
    async def run(self, job: dict[str, Any]) -> dict[str, Any]:
        """Produce a cited result for a leased Platform job when implemented."""
        raise NotImplementedError("Agent execution is not implemented")
