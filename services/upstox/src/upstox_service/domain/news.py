"""Provider-independent news ingestion values."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from upstox_service.domain.entities import NewsArticle


class ProviderStatus(str, Enum):
    """Outcome of one provider fetch attempt."""

    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DEGRADED_PAYWALL = "DEGRADED_PAYWALL"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class StagedNewsItem:
    """One provider item ready to be staged immutably in `news_raw`.

    Carries the provider's untouched payload alongside the identity fields
    the staging table needs, so the audit trail is exactly what the
    provider returned.
    """

    external_id: str
    published_at: datetime
    source_url: str
    payload: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ProviderFetchResult:
    """Outcome of one provider fetch - articles plus how it went.

    Immutable: a fetch result is a record of what happened, not a mutable
    accumulator. Before eligibility filtering, `staged` carries each
    provider's untouched item dict.  After filtering it contains only the
    approved pairs that may be written to SQL. `watermark_at` still records
    the newest parsed provider item so rejected stories are not re-fetched.
    """

    provider_id: str
    status: ProviderStatus
    articles: tuple[NewsArticle, ...] = ()
    requests_used: int = 0
    error: str | None = None
    staged: tuple[StagedNewsItem, ...] = field(default=(), repr=False)
    watermark_at: datetime | None = None
    approvals: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    eligibility_counts: dict[str, int] = field(default_factory=dict, repr=False)
