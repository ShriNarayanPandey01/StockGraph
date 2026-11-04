"""Compose keeps private Platform credentials on the API process."""

from pathlib import Path

import yaml


def test_platform_secrets_are_not_inherited_by_the_worker_and_template_is_opt_in():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    api_environment = services["platform-api"]["environment"]
    worker_environment = services["platform-worker"]["environment"]

    api_only = {
        "PLATFORM_ADMIN_NAME",
        "PLATFORM_ADMIN_EMAIL",
        "PLATFORM_ADMIN_PASSWORD",
        "PLATFORM_BROKER_ENCRYPTION_KEY",
        "PLATFORM_AGENT_SERVICE_KEY",
        "DOCUMENT_INTERNAL_API_KEY",
        "MARKETGRAPH_INTERNAL_SERVICE_KEY",
    }
    assert api_only <= api_environment.keys()
    assert not api_only.intersection(worker_environment)
    assert services["agents-template"]["profiles"] == ["agents-template"]
