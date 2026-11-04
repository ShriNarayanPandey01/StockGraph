"""Explicit, read-only registry of supported LangGraph job handlers."""

from collections.abc import Callable, Mapping
from types import MappingProxyType

from marketgraph_agents.workflows import build_graph

AGENTS: Mapping[str, Callable] = MappingProxyType({
    'chat': build_graph, 'discovery': build_graph, 'monitor': build_graph,
})
