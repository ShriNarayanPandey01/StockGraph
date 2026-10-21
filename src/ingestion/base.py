"""Shared contracts for scheduled ingestion jobs.

The contracts deliberately accept normalized dictionaries at the source
boundary.  Exchange/agency-specific HTTP and file parsing can therefore be
implemented behind adapters without leaking untrusted identifiers into the
repositories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IngestionResult:
    """Stable result returned by every periodic ingestion entrypoint."""

    status: str
    records_seen: int = 0
    records_persisted: int = 0
    graph_writes: int = 0
    skipped: int = 0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class BaseIngestor(ABC):
    """Small common base kept intentionally free of source-specific logic."""

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> IngestionResult:
        """Run one bounded, idempotent ingestion batch."""


class BasePeriodicMacroIngestor(BaseIngestor):
    """Contract required by docs/03 for monthly and bi-monthly feeds."""

    @abstractmethod
    async def ingest_macro_indicators(self, *args: Any, **kwargs: Any) -> IngestionResult:
        """Ingest canonical official macro observations into TimescaleDB."""

    @abstractmethod
    async def ingest_mf_holdings(self, *args: Any, **kwargs: Any) -> IngestionResult:
        """Ingest and rotate AMFI/AMC mutual-fund holdings."""
