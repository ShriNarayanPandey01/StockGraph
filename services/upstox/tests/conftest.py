"""Explicit internal credentials for service contract tests."""
import pytest


@pytest.fixture(autouse=True)
def internal_service_credential(monkeypatch):
    monkeypatch.setenv("MARKETGRAPH_INTERNAL_SERVICE_KEY", "test-internal-key")
