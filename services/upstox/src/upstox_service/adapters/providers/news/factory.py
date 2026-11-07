"""Compose concrete news provider adapters."""

import logging

from upstox_service.adapters.providers.http_client import ResilientHttpClient
from upstox_service.adapters.providers.news.adapters import (
    AlphaVantageNewsAdapter,
    CurrentsNewsAdapter,
    FmpNewsAdapter,
    MarketauxNewsAdapter,
    NewsProviderAdapter,
)
from upstox_service.config.settings import settings
from upstox_service.domain.resolver import CanonicalEntityResolver

logger = logging.getLogger(__name__)
_PROVIDER_REGISTRY = {
    "marketaux": (MarketauxNewsAdapter, "marketaux_api_key"),
    "currents": (CurrentsNewsAdapter, "currents_api_key"),
    "alphavantage": (AlphaVantageNewsAdapter, "alpha_vantage_api_key"),
    "fmp": (FmpNewsAdapter, "fmp_api_key"),
}


def build_news_adapters(
    resolver: CanonicalEntityResolver | None = None,
    http_client: ResilientHttpClient | None = None,
    config=None,
) -> list[NewsProviderAdapter]:
    """Composition root: build the enabled provider adapters, in priority order.

    This is the ONLY place that names the concrete provider classes, so
    adding or removing a provider never touches the fetch service.
    """
    config = config or settings
    resolver = resolver or CanonicalEntityResolver.from_seed()
    adapters: list[NewsProviderAdapter] = []
    for raw_name in config.news_providers_enabled.split(","):
        name = raw_name.strip().lower()
        entry = _PROVIDER_REGISTRY.get(name)
        if entry is None:
            logger.warning("Unknown news provider %r - ignored", raw_name)
            continue
        adapter_cls, key_attr = entry
        adapters.append(
            adapter_cls(
                api_key=getattr(config, key_attr),
                resolver=resolver,
                http_client=http_client,
            )
        )
    return sorted(adapters, key=lambda a: a.priority)
