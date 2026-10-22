"""Core enums. Commodity/macro/sector IDs live in
the committed catalog projection (Rule 4 registry), not here.

`OntologyRelationType` and `CorrelationType` ARE enums: they define the
closed set of dynamic edge labels the LLM may emit (`InferredOntologyEdge`,
`InferredNewsCorrelation`). Registry node IDs stay in YAML."""

from enum import Enum


class Window(str, Enum):
    LAST_6M = "LAST_6M"
    LAST_1Y = "LAST_1Y"


class Cadence(str, Enum):
    STREAM_30M = "stream_30m"
    DAILY_OPEN = "daily_open"
    DAILY_EOD = "daily_eod"
    MONTHLY = "monthly"
    BIMONTHLY = "bimonthly"
    QUARTERLY = "quarterly"


class MarketSession(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OntologyRelationType(str, Enum):
    """Dynamic Stock/Commodity <-> Commodity/Macro/Sector/Stock edge labels.

    Emitted by DynamicOntologyBuilder as `InferredOntologyEdge.relation`.
    Stock edges: EXPOSED_TO (commodity), SENSITIVE_TO_MACRO (macro),
    BELONGS_TO (sector), SUPPLIES_TO / COMPETES_WITH (peer stocks).
    Commodity inter-links: RELATED_TO (input/substitute linkage between
    :Commodity nodes, e.g. COKING_COAL -> HRC_STEEL).
    Only edges with `confidence >= ontology_min_confidence` are persisted.
    """

    EXPOSED_TO = "EXPOSED_TO"
    SENSITIVE_TO_MACRO = "SENSITIVE_TO_MACRO"
    BELONGS_TO = "BELONGS_TO"
    SUPPLIES_TO = "SUPPLIES_TO"
    COMPETES_WITH = "COMPETES_WITH"
    RELATED_TO = "RELATED_TO"


class CorrelationType(str, Enum):
    """Cross-news edge labels for [:CORRELATED_WITH] (NewsCorrelator L4)."""

    CAUSAL_CHAIN = "CAUSAL_CHAIN"
    MACRO_CONTAGION = "MACRO_CONTAGION"
    SECTOR_RIPPLE = "SECTOR_RIPPLE"
    FOLLOW_UP = "FOLLOW_UP"


class DealType(str, Enum):
    BULK = "BULK"
    BLOCK = "BLOCK"
    INSIDER = "INSIDER"


class DealSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ActorCategory(str, Enum):
    FII = "FII"
    DII = "DII"
    PROMOTER = "PROMOTER"
    MUTUAL_FUND = "MUTUAL_FUND"
    OTHER = "OTHER"


class NewsCategory(str, Enum):
    EARNINGS = "EARNINGS"
    SECTOR_UPDATE = "SECTOR_UPDATE"
    MACRO = "MACRO"
    TRADE = "TRADE"
    GEOPOLITICAL = "GEOPOLITICAL"
    REG30 = "REG30"
    COMMODITY = "COMMODITY"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    OTHER = "OTHER"
