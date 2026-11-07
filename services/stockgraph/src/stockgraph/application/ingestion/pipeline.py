"""Dispatch committed events to their dedicated application handlers."""

from stockgraph.application.ingestion.handlers import NewsEventHandler, RegistryEventHandler
from stockgraph.application.ports import (
    ChatModel,
    EmbeddingModel,
    EventStateStore,
    GraphEventHandler,
    GraphProcessingStore,
    GuidanceReader,
    NewsRoutingHandler,
)
from stockgraph.application.processors.news_dedup import NewsDeduper
from stockgraph.application.processors.stock_profile_provider import StockProfileProvider
from stockgraph.domain.events import CommittedEvent


class GraphPipeline:
    def __init__(self, repo: GraphProcessingStore, redis: EventStateStore, chat: ChatModel,
                 embedder: EmbeddingModel,
                 guidance: GuidanceReader | None = None, *,
                 registry_handler: GraphEventHandler | None = None,
                 news_handler: NewsRoutingHandler | None = None) -> None:
        profiles = StockProfileProvider(repo, guidance)
        self._news_handler = (
            news_handler if news_handler is not None
            else NewsEventHandler(repo, redis, chat, embedder, profiles, NewsDeduper(repo))
        )
        self._registry_handler = (
            registry_handler if registry_handler is not None
            else RegistryEventHandler(repo, chat, embedder, self._news_handler, profiles)
        )

    def process(self, event: CommittedEvent) -> None:
        if event.kind == "registry.updated":
            self._registry_handler.handle(event)
        else:
            self._news_handler.handle(event)
