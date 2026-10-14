"""
Algo Lab — News & Market Fundamentals Agent Contracts & Data Models
Defines immutable point-in-time schemas for news items, fundamental metrics,
sentiment evaluations, and quantamental decision manifests.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Dict, Any, List, Optional


class DataUnavailableError(Exception):
    """Raised when real market intelligence data is unavailable and synthetic fallback is prohibited."""
    pass


class SentimentLabel(str, Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


class NewsUrgency(str, Enum):
    HIGH = "HIGH"        # Breaking regulatory action, earnings release, major legal dispute, default
    MEDIUM = "MEDIUM"    # Analyst upgrade/downgrade, product launch, contract win
    LOW = "LOW"          # General market commentary, sector gossip


class NewsCategory(str, Enum):
    EARNINGS = "EARNINGS"
    CORPORATE_GOVERNANCE = "CORPORATE_GOVERNANCE"
    REGULATORY = "REGULATORY"
    CONTRACT_ORDER = "CONTRACT_ORDER"
    DIVIDEND_SPLIT = "DIVIDEND_SPLIT"
    MACRO_POLICY = "MACRO_POLICY"
    ANALYST_OPINION = "ANALYST_OPINION"
    GENERAL = "GENERAL"


class HealthTier(str, Enum):
    PRIME_QUALITY = "PRIME_QUALITY"      # Robust balance sheet, strong ROE, low leverage
    SOUND = "SOUND"                      # Good fundamentals, manageable debt
    AVERAGE = "AVERAGE"                  # Neutral metrics, moderate risk
    SPECULATIVE = "SPECULATIVE"          # Stretched valuation, weak profitability
    DISTRESSED = "DISTRESSED"            # Extreme debt, deteriorating earnings, red flags


class CompositeBias(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    DISQUALIFIED = "DISQUALIFIED"        # High-risk red flags triggered; trade prohibited


@dataclass(frozen=True)
class NewsItem:
    """Immutable point-in-time financial news item enforcing INV-26 lookahead protection."""
    article_id: str                      # Deterministic hash of title and published_at
    symbol: str                          # Standardized ticker (e.g., RELIANCE.NS)
    title: str
    summary: str
    source: str                          # Publisher/outlet name
    published_at: datetime               # Strict publication timestamp T_pub
    ingested_at: datetime                # Ingestion timestamp T_ret
    url: Optional[str] = None
    sentiment_score: float = 0.0         # Range: [-1.0, 1.0]
    sentiment_label: SentimentLabel = SentimentLabel.NEUTRAL
    confidence: float = 0.5              # Confidence score [0.0, 1.0]
    urgency: NewsUrgency = NewsUrgency.LOW
    category: NewsCategory = NewsCategory.GENERAL
    is_synthetic_fixture: bool = False
    provenance: str = "LIVE_RSS"

    def __post_init__(self):
        if not math.isfinite(self.sentiment_score):
            raise ValueError(f"sentiment_score must be a finite float, got {self.sentiment_score}")
        if not math.isfinite(self.confidence):
            raise ValueError(f"confidence must be a finite float, got {self.confidence}")

    def is_eligible_at(self, simulation_time: datetime) -> bool:
        """Enforces point-in-time availability rule: T_pub <= t_sim."""
        return self.published_at <= simulation_time


@dataclass(frozen=True)
class FundamentalSnapshot:
    """Standardized fundamental financial metrics snapshot for an equity asset."""
    symbol: str
    as_of_date: date
    market_cap: float
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    ev_to_ebitda: Optional[float]
    debt_to_equity: Optional[float]
    roe: Optional[float]                 # Return on Equity (decimal, e.g. 0.18 = 18%)
    roce: Optional[float]                # Return on Capital Employed
    operating_margin: Optional[float]    # Operating profit margin
    net_margin: Optional[float]          # Net profit margin
    revenue_growth_yoy: Optional[float]  # YoY revenue growth rate
    eps_growth_yoy: Optional[float]      # YoY EPS growth rate
    free_cash_flow: Optional[float]
    piotroski_f_score: int               # Score between 0 and 9
    health_tier: HealthTier = HealthTier.AVERAGE
    red_flags: List[str] = field(default_factory=list)
    is_synthetic_fixture: bool = False
    provenance: str = "REAL_PROVIDER"

    def __post_init__(self):
        if not math.isfinite(self.market_cap) or self.market_cap < 0:
            raise ValueError(f"market_cap must be a non-negative finite float, got {self.market_cap}")
        for field_name in (
            "pe_ratio", "pb_ratio", "ev_to_ebitda", "debt_to_equity",
            "roe", "roce", "operating_margin", "net_margin",
            "revenue_growth_yoy", "eps_growth_yoy", "free_cash_flow",
        ):
            val = getattr(self, field_name)
            if val is not None and not math.isfinite(val):
                raise ValueError(f"{field_name} must be a finite number if provided, got {val}")
        if not isinstance(self.piotroski_f_score, int) or not (0 <= self.piotroski_f_score <= 9):
            raise ValueError(f"piotroski_f_score must be an integer between 0 and 9, got {self.piotroski_f_score}")

    @property
    def is_disqualified(self) -> bool:
        """Disqualification status based on severe fundamental red flags."""
        return len(self.red_flags) > 0 and (
            "EXTREME_DEBT_BURDEN" in self.red_flags
            or "CHRONIC_NEGATIVE_EARNINGS" in self.red_flags
            or "SEVERE_REVENUE_CONTRACTION" in self.red_flags
            or "NON_FINITE_RATIOS" in self.red_flags
            or "REGULATORY_SCANDAL" in self.red_flags
            or "AUDITOR_RESIGNATION" in self.red_flags
        )


@dataclass(frozen=True)
class QuantamentalDecisionManifest:
    """
    Synthesized decision and intelligence manifest uniting
    news sentiment and market fundamentals.
    Complies with Principle 18: Explainability through evidence.
    """
    symbol: str
    evaluated_at: datetime
    fundamental_score: float             # Score [0.0, 100.0]
    sentiment_score: float               # Score [-100.0, 100.0]
    composite_score: float               # Score [-100.0, 100.0]
    bias: CompositeBias
    allow_trading: bool                  # Hard risk filter gate
    allocation_multiplier: float         # Recommended capital scale [0.0, 1.0]
    recent_news_count: int
    catalysts: List[str]
    risks: List[str]
    narrative: str                       # Explainable audit narrative


@dataclass(frozen=True)
class MacroNewsItem:
    """Broader macroeconomic news event (RBI, inflation, GDP, FII, currency)."""
    item_id: str
    headline: str
    source: str
    published_at: datetime
    sentiment_score: float
    theme: str                           # "MONETARY_POLICY", "INFLATION", "FII_FLOWS", "MACRO_GROWTH"
    url: Optional[str] = None


@dataclass(frozen=True)
class CorporateCalendarEvent:
    """Upcoming or recent corporate catalyst (earnings release, dividend ex-date)."""
    symbol: str
    event_type: str                      # "EARNINGS", "DIVIDEND", "SPLIT"
    event_date: Optional[str]
    description: str


@dataclass(frozen=True)
class AnalystConsensus:
    """Institutional analyst ratings, target price dispersion, and recommendations."""
    symbol: str
    target_mean: Optional[float]
    target_high: Optional[float]
    target_low: Optional[float]
    current_price: Optional[float]
    upside_potential_pct: Optional[float]
    recommendation_key: str              # e.g. "buy", "hold", "outperform"
    number_of_analysts: Optional[int]


@dataclass
class CollectionScheduleConfig:
    """Configurable collection intervals across multi-tiered intelligence sources."""
    news_interval_minutes: int = 15      # Intraday breaking news stream
    macro_interval_minutes: int = 60     # Macroeconomic & market wrap news
    fundamentals_interval_hours: int = 12 # Deep fundamental balance sheet & analyst refresh

