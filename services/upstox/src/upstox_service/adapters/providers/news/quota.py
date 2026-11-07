"""Redis-backed provider request quota."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class RequestQuotaBudget:
    """Per-provider daily request budget, backed by Redis counters.

    The counter key format is an implementation detail and stays private;
    callers only ask `try_consume()`.
    """

    def __init__(self, redis_client: Any | None, daily_cap_override: int | None = None) -> None:
        self._redis = redis_client
        self._override = daily_cap_override

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def _key(self, provider_id: str) -> str:
        return f"newsquota:{provider_id}:{datetime.now(UTC):%Y%m%d}"

    def effective_cap(self, provider_cap: int) -> int:
        """The cap that applies to a provider: the operator override, else
        the provider's own declared plan limit."""
        if self._override is not None:
            return self._override
        return provider_cap

    def try_consume(self, provider_id: str, provider_cap: int) -> bool:
        """Consume one request from today's budget. False when exhausted.

        With no Redis the budget cannot be enforced, so the request is
        allowed through: an unavailable cache must not silently stop
        ingestion.
        """
        if self._redis is None:
            return True
        cap = self.effective_cap(provider_cap)
        key = self._key(provider_id)
        try:
            used = int(self._redis.incr(key))
            if used == 1:
                self._redis.expire(key, self._seconds_until_utc_midnight())
            if used > cap:
                # Give the slot back so the counter reflects real usage.
                self._redis.decr(key)
                return False
        except Exception:  # noqa: BLE001 - fail open, never stop ingestion
            logger.warning("Quota counter unavailable for %s", provider_id)
            return False
        return True

    def consumed(self, provider_id: str) -> int:
        """Requests already consumed today for a provider."""
        if self._redis is None:
            return 0
        try:
            raw = self._redis.get(self._key(provider_id))
        except Exception:  # noqa: BLE001
            return 0
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _seconds_until_utc_midnight() -> int:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((tomorrow - now).total_seconds()))
