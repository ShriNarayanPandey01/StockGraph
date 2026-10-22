"""Deployment boundaries are enforced without importing the sibling service."""

import ast
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("service", "forbidden"),
    [
        ("stockgraph", {"upstox_service", "src", "asyncpg", "sqlalchemy", "psycopg", "psycopg2"}),
        ("upstox", {"stockgraph", "src", "falkordb", "litellm", "openai"}),
    ],
)
def test_services_have_no_cross_service_or_wrong_database_imports(service, forbidden):
    for source in (ROOT / "services" / service / "src").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not {name.split(".")[0] for name in names} & forbidden, source


def test_service_dependency_manifests_enforce_database_ownership():
    manifests = {
        name: tomllib.loads((ROOT / "services" / name / "pyproject.toml").read_text())
        for name in ("upstox", "stockgraph")
    }
    graph = " ".join(manifests["stockgraph"]["project"]["dependencies"]).lower()
    data = " ".join(manifests["upstox"]["project"]["dependencies"]).lower()
    assert "asyncpg" not in graph and "sqlalchemy" not in graph
    assert "falkordb" not in data and "litellm" not in data
    assert "falkordb" in graph and "asyncpg" in data


def test_reset_refuses_other_databases_and_graphs():
    from scripts.project_data import validate_targets
    from scripts.project_settings import ProjectDataSettings

    settings = ProjectDataSettings(_env_file=None)
    validate_targets(settings)
    for fields in (
        {"timescale_dsn": "postgresql://u:p@localhost/unrelated"},
        {"falkor_graph_name": "unrelated"},
        {"redis_url": "redis://localhost:6380/1"},
        {"timescale_dsn": "postgresql://u:p@remote/stockgraph"},
    ):
        with pytest.raises(ValueError, match="Refusing"):
            validate_targets(settings.model_copy(update=fields))


def test_reset_preserves_quota_and_spend_ledgers():
    from fnmatch import fnmatch

    from scripts.project_data import REDIS_PATTERNS

    for key in ("llm:spend:2026-10", "newsquota:MARKETAUX:20261022", "unrelated:cache"):
        assert not any(fnmatch(key, pattern) for pattern in REDIS_PATTERNS)


def test_published_event_can_be_consumed_without_shared_python_types():
    from stockgraph.domain.events import CommittedEvent
    from upstox_service.domain.models import event

    message = event(
        "registry.updated",
        "NEW_STOCK",
        1,
        {"kind": "Stock", "entity": {"ticker": "NEW_STOCK", "name": "Example"}},
    )
    parsed = CommittedEvent.model_validate(message)
    assert parsed.entity_id == "NEW_STOCK"
    assert parsed.payload["kind"] == "Stock"
