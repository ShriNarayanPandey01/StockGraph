"""Behavior checks for the application boundaries introduced by the redesign."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from upstox_service.adapters.api.main import create_app
from upstox_service.application.errors import InstrumentNotFound
from upstox_service.application.ingestion.news_fetch import (
    CommittedNewsPersistence,
    NewsIngestionCoordinator,
)
from upstox_service.application.stock_data import StockDataService, StockNotFound
from upstox_service.domain.news import ProviderFetchResult, ProviderStatus
from upstox_service.domain.resolver import CanonicalEntityResolver


async def test_registration_identity_error_does_not_depend_on_provider_error_text():
    repository = SimpleNamespace(get_instrument=AsyncMock(return_value=None))
    provider = SimpleNamespace(resolve=AsyncMock(side_effect=InstrumentNotFound("unavailable")))
    with pytest.raises(StockNotFound):
        await StockDataService(repository, provider).stock("TCS", "NSE")


async def test_failed_review_replay_stops_the_new_provider_fetch():
    replay = SimpleNamespace(
        replay_pending=AsyncMock(side_effect=RuntimeError("store unavailable"))
    )
    fetch = SimpleNamespace(fetch_cycle=AsyncMock())
    with pytest.raises(RuntimeError, match="store unavailable"):
        await NewsIngestionCoordinator(fetch, replay).fetch_cycle()
    fetch.fetch_cycle.assert_not_awaited()


async def test_news_commit_failure_is_not_hidden_by_persistence_adapter():
    repository = SimpleNamespace(commit_news=AsyncMock(side_effect=RuntimeError("commit failed")))
    result = ProviderFetchResult(provider_id="test", status=ProviderStatus.AVAILABLE)
    with pytest.raises(RuntimeError, match="commit failed"):
        await CommittedNewsPersistence(repository).stage(result)


def test_readiness_uses_repository_health_contract():
    repository = SimpleNamespace(health_check=AsyncMock(return_value=True))
    broker = SimpleNamespace(ping=AsyncMock(return_value=True))
    with TestClient(create_app(repository, broker)) as client:
        assert client.get("/ready").status_code == 200
    repository.health_check.assert_awaited_once()


def test_resolver_returns_a_copy_of_stock_names():
    resolver = CanonicalEntityResolver.from_catalog(
        [{"kind": "Stock", "payload": {"ticker": "TCS", "name": "Tata Consultancy Services"}}]
    )
    names = resolver.list_stock_names()
    names["TCS"] = "changed"
    assert resolver.resolve_stock("Tata Consultancy Services") == "TCS"
    assert resolver.list_stock_names()["TCS"] == "Tata Consultancy Services"
