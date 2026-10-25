"""Empty, read-only registry; future handlers will be registered explicitly."""

from collections.abc import Mapping
from types import MappingProxyType

from marketgraph_agents.agent import Agent

AGENTS: Mapping[str, type[Agent]] = MappingProxyType({})
