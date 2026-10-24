"""Stock news and rising stock breakout feed.

Provides structured market items for proactive notifications and on-demand queries.
In production, this feeds directly from Upstox Bhavcopy / NSE Reg-30 / NewsProviderAdapter.
"""

from dataclasses import dataclass
from typing import List, Optional, Union
import itertools


@dataclass
class StockNewsItem:
    """Represents a market or company news event with stock impact."""
    ticker: str
    company_name: str
    headline: str
    summary: str
    source: str
    sentiment: str  # "BULLISH", "BEARISH", "NEUTRAL"
    cmp: float
    catalyst: str
    impact_rationale: str
    url: Optional[str] = None

    @property
    def sentiment_emoji(self) -> str:
        if self.sentiment == "BULLISH":
            return "🟢 BULLISH"
        elif self.sentiment == "BEARISH":
            return "🔴 BEARISH"
        return "🟡 NEUTRAL"


@dataclass
class RisingStockAlert:
    """Represents a high-momentum or technical volume breakout alert."""
    ticker: str
    company_name: str
    cmp: float
    change_pct: float
    volume_surge: str
    breakout_level: str
    delivery_pct: float
    catalyst: str

    @property
    def direction_emoji(self) -> str:
        return "🚀 SURGING" if self.change_pct >= 3.0 else "📈 RISING"


# Curated realistic demo items reflecting Indian Equities (NSE/BSE)
SAMPLE_NEWS_FEED: List[StockNewsItem] = [
    StockNewsItem(
        ticker="RELIANCE",
        company_name="Reliance Industries Ltd",
        headline="Reliance Retail expands hyper-local quick commerce across 50 cities; petrochemical margins rebound",
        summary="Reliance Retail reports a 24% acceleration in daily digital orders while global refining margins (GRM) widen to $11.4/bbl.",
        source="NSE Reg-30 / Exchange Filing",
        sentiment="BULLISH",
        cmp=1428.60,
        catalyst="Retail EBITDA Expansion + Crude GRM Uplift",
        impact_rationale="FII net buying detected (+₹420 Cr). High delivery percentage of 54.2% suggests institutional accumulation.",
        url="https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    ),
    StockNewsItem(
        ticker="TATAMOTORS",
        company_name="Tata Motors Ltd",
        headline="Tata Motors bags major 2,500 EV bus tender; JLR UK order backlog crosses 160,000 units",
        summary="State transport corporations award a key fleet electrification order. JLR reports sustained free cash flow (FCF) momentum.",
        source="BSE Corporate Disclosures",
        sentiment="BULLISH",
        cmp=985.40,
        catalyst="EV Fleet Order Win + Margin Expansion",
        impact_rationale="Delivery volume up 2.8x 20-day mean. Upward target revisions by major institutional brokerages.",
        url="https://www.bseindia.com/corporates/ann.html",
    ),
    StockNewsItem(
        ticker="HDFCBANK",
        company_name="HDFC Bank Ltd",
        headline="HDFC Bank advances deposit growth to 17.5% YoY; Loan-to-Deposit Ratio (LDR) normalizes",
        summary="Quarterly update shows robust Casa deposit accretion, reducing borrowing costs and stabilizing Net Interest Margins (NIM).",
        source="RBI / Banking Bulletin",
        sentiment="BULLISH",
        cmp=1682.10,
        catalyst="Credit Quality & Margin Normalization",
        impact_rationale="DII accumulation confirmed across 3 consecutive trading sessions.",
        url="https://www.nseindia.com",
    ),
    StockNewsItem(
        ticker="INFY",
        company_name="Infosys Ltd",
        headline="Infosys secures $450M multi-year European cloud transformation and generative AI deal",
        summary="Large deal Total Contract Value (TCV) hits fresh fiscal highs as enterprise clients ramp up AI migration spending.",
        source="Exchange Press Release",
        sentiment="BULLISH",
        cmp=1795.00,
        catalyst="Cloud & GenAI Deal TCV Growth",
        impact_rationale="USD/INR stability provides gross margin cushion; valuation re-rating expected.",
        url="https://www.nseindia.com",
    ),
    StockNewsItem(
        ticker="ITC",
        company_name="ITC Ltd",
        headline="ITC agribusiness posts 18% export growth; FMCG segment margin scales past 11%",
        summary="Strong hotel demerger progress and raw material cost tailwinds drive operating leverage in non-cigarette FMCG.",
        source="Bloomberg Quint",
        sentiment="BULLISH",
        cmp=482.30,
        catalyst="Agri Commodity Tailwinds & Hotel Demerger",
        impact_rationale="Defensive cash-flow asset with 3.8% dividend yield and consistent promoter/DII backing.",
        url="https://www.bseindia.com",
    ),
]

SAMPLE_RISING_ALERTS: List[RisingStockAlert] = [
    RisingStockAlert(
        ticker="TATAMOTORS",
        company_name="Tata Motors Ltd",
        cmp=985.40,
        change_pct=4.82,
        volume_surge="3.4x 20-Day Average",
        breakout_level="Crossed 52-Week High resistance at ₹965",
        delivery_pct=61.8,
        catalyst="Heavy institutional block deal + JLR cash-flow guidance boost",
    ),
    RisingStockAlert(
        ticker="BEL",
        company_name="Bharat Electronics Ltd",
        cmp=312.75,
        change_pct=5.35,
        volume_surge="4.1x 20-Day Average",
        breakout_level="Multi-month consolidation breakout at ₹302",
        delivery_pct=68.2,
        catalyst="Defence Ministry procurement order nod + High export pipeline",
    ),
    RisingStockAlert(
        ticker="LT",
        company_name="Larsen & Toubro Ltd",
        cmp=3680.00,
        change_pct=3.65,
        volume_surge="2.7x 20-Day Average",
        breakout_level="All-time high territory above ₹3600",
        delivery_pct=55.9,
        catalyst="Middle East mega-infrastructure order win valued at $1.2B",
    ),
    RisingStockAlert(
        ticker="SUNPHARMA",
        company_name="Sun Pharmaceutical Industries Ltd",
        cmp=1740.20,
        change_pct=3.15,
        volume_surge="2.3x 20-Day Average",
        breakout_level="Channel breakout above ₹1710",
        delivery_pct=59.1,
        catalyst="US FDA fast-track approval for specialty dermatology pipeline",
    ),
]


class MarketFeedManager:
    """Manages cycle and retrieval of market feeds."""

    def __init__(self):
        # Infinite cycling iterators
        self._news_cycle = itertools.cycle(SAMPLE_NEWS_FEED)
        self._rising_cycle = itertools.cycle(SAMPLE_RISING_ALERTS)
        self._alert_toggle = True

    def get_next_proactive_alert(self) -> Union[StockNewsItem, RisingStockAlert]:
        """Alternates between a top news story and a high-momentum breakout alert."""
        self._alert_toggle = not self._alert_toggle
        if self._alert_toggle:
            return next(self._news_cycle)
        else:
            return next(self._rising_cycle)

    def get_news_item(self) -> StockNewsItem:
        """Returns the next stock news item."""
        return next(self._news_cycle)

    def get_rising_alert(self) -> RisingStockAlert:
        """Returns the next rising stock alert."""
        return next(self._rising_cycle)


feed_manager = MarketFeedManager()

