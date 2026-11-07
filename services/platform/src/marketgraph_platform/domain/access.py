"""Immutable access policy snapshots used at request and job boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from marketgraph_platform.errors import PlatformError
from marketgraph_platform.models import Principal


def _decode_features(value: Any) -> dict[str, bool]:
    if isinstance(value, str):
        value = json.loads(value)
    return {str(key): bool(allowed) for key, allowed in (value or {}).items()}


@dataclass(frozen=True, slots=True)
class PlanPolicy:
    """A detached policy value; nested feature state cannot be mutated by callers."""

    plan: str
    active_stock_limit: int | None
    monthly_alert_limit: int | None
    features: frozenset[str]
    feature_names: frozenset[str]
    revision: int

    @classmethod
    def from_record(cls, record: Mapping[str, Any] | PlanPolicy) -> PlanPolicy:
        if isinstance(record, cls):
            return record
        features = _decode_features(record.get("features"))
        return cls(
            plan=str(record.get("plan", "FREE")),
            active_stock_limit=record.get("active_stock_limit"),
            monthly_alert_limit=record.get("monthly_alert_limit"),
            features=frozenset(key for key, enabled in features.items() if enabled),
            feature_names=frozenset(features),
            revision=int(record.get("revision", 1)),
        )

    def allows(self, feature: str) -> bool:
        return feature in self.features

    def as_dict(self) -> dict[str, Any]:
        # Return fresh nested collections for serialization and compatibility.
        return {
            "plan": self.plan,
            "active_stock_limit": self.active_stock_limit,
            "monthly_alert_limit": self.monthly_alert_limit,
            "features": {name: name in self.features for name in sorted(self.feature_names)},
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True, init=False)
class AccessSnapshot:
    """Immutable identity, plan and stock-selection state for one authorization check."""

    _principal: Principal
    _policy: PlanPolicy
    _tickers: tuple[str, ...]

    def __init__(self, user: Principal, policy: Mapping[str, Any] | PlanPolicy,
                 tickers: tuple[str, ...] | list[str]):
        object.__setattr__(self, "_principal", user.model_copy(deep=True))
        object.__setattr__(self, "_policy", PlanPolicy.from_record(policy))
        object.__setattr__(self, "_tickers", tuple(sorted(set(tickers))))

    @property
    def user(self) -> Principal:
        return self._principal

    @property
    def policy(self) -> dict[str, Any]:
        return self._policy.as_dict()

    @property
    def tickers(self) -> tuple[str, ...]:
        return self._tickers

    @property
    def developer(self) -> bool:
        return self._principal.is_developer

    @property
    def pro(self) -> bool:
        from marketgraph_platform.policy import effective_plan

        return effective_plan(self._principal) == "PRO"

    def allows(self, feature: str) -> bool:
        return self.developer or self._policy.allows(feature)

    def require(self, feature: str | None = None, tickers=(), single: bool = False):
        if self._principal.disabled:
            raise PlatformError(403, "Account is disabled")
        if feature and not self.allows(feature):
            raise PlatformError(403, "Feature requires Pro access: " + feature)
        limit = self._policy.active_stock_limit
        if not self.developer and limit is not None and len(self._tickers) > limit:
            raise PlatformError(403, f"Reduce active stocks to the configured limit of {limit}")
        if not self.developer and not self.pro:
            if single and len(tickers) != 1:
                raise PlatformError(403, "Free research requires exactly one active stock")
            if tickers and (not self._principal.active_selection_initialized or set(tickers) - set(self._tickers)):
                raise PlatformError(403, "Select these stocks in your active-stock selection first")
        return self

    def require_job(self, job):
        input_data = job.get("input")
        if isinstance(input_data, str):
            input_data = json.loads(input_data)
        payload = input_data or {}
        kind = job["kind"]
        feature = (
            "discovery" if kind == "discovery" else
            "market_monitoring" if payload.get("scope") == "market" else
            "monitoring" if kind == "monitor" else "research_chat"
        )
        self.require(feature, payload.get("tickers", []), single=kind == "chat")
        if job.get("required_plan") == "PRO" and not self.pro and not self.developer:
            raise PlatformError(403, "This job requires Pro access")
        return self
