"""
Algo Lab — News & Market Fundamentals Agent Contracts & Data Models
Defines immutable point-in-time schemas for news items, fundamental metrics,
sentiment evaluations, and quantamental decision manifests.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Dict, Any, List, Optional


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

    @property
    def is_disqualified(self) -> bool:
        """Disqualification status based on severe fundamental red flags."""
        return len(self.red_flags) > 0 and (
            "EXTREME_DEBT_BURDEN" in self.red_flags
            or "CHRONIC_NEGATIVE_EARNINGS" in self.red_flags
            or "SEVERE_REVENUE_CONTRACTION" in self.red_flags
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
