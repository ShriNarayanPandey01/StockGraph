"""Standard OAuth access-token aliases must work locally and in Compose."""

from pathlib import Path

from upstox_service.config.settings import Settings


def test_token_alias_does_not_get_shadowed_by_empty_template_value():
    settings = Settings(_env_file=None,UPSTOX_ANALYTICS_TOKEN='',UPSTOX_AUTHTOKEN='test-access-token')
    assert settings.upstox_analytics_token.get_secret_value() == 'test-access-token'
    assert 'test-access-token' not in repr(settings)


def test_explicit_analytics_token_takes_precedence():
    settings = Settings(_env_file=None,UPSTOX_ANALYTICS_TOKEN='analytics',UPSTOX_AUTHTOKEN='oauth')
    assert settings.upstox_analytics_token.get_secret_value() == 'analytics'


def test_compose_forwards_both_documented_token_names():
    compose = Path(__file__).resolve().parents[3].joinpath('docker-compose.yml').read_text(encoding='utf-8')
    assert '${UPSTOX_ANALYTICS_TOKEN:-${UPSTOX_AUTHTOKEN:-}}' in compose
