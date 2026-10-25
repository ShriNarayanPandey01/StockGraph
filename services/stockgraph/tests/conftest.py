"""Explicit internal credentials for service contract tests."""
import pytest
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def internal_service_credential(monkeypatch):
    monkeypatch.setenv("MARKETGRAPH_INTERNAL_SERVICE_KEY", "test-internal-key")
    from stockgraph.runtime.settings import settings
    monkeypatch.setattr(settings, "internal_service_key", SecretStr("test-internal-key"))
