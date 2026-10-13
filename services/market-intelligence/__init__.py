"""
Algo Lab — Stage 8 Market Intelligence Package
Exposes contracts, breadth calculator, institutional flow processor, and sector rotation engine.
"""

from services.market_intelligence.contracts import (
    PointInTimeRecord,
    SectorMembershipRecord,
    BreadthRecord,
    InstitutionalFlowRecord,
    SectorRank,
    MarketIntelligenceError,
    MissingTimestampError,
    SourceConflictError,
    MissingMembershipError,
)
from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    FundamentalSnapshot,
    QuantamentalDecisionManifest,
    SentimentLabel,
    NewsUrgency,
    NewsCategory,
    HealthTier,
    CompositeBias,
    MacroNewsItem,
    CorporateCalendarEvent,
    AnalystConsensus,
    CollectionScheduleConfig,
)
from services.market_intelligence.sentiment_engine import FinancialSentimentAnalyzer
from services.market_intelligence.fundamental_engine import FundamentalAnalyzer
from services.market_intelligence.collector_service import NewsCollector, FundamentalCollector
from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant
from services.market_intelligence.stock_decision_engine import (
    StockDecisionEngine,
    SelectionTier,
    TradeAction,
    StockSelectionCandidate,
    StockSelectionManifest,
    TradeDecisionResult,
)

__all__ = [
    "PointInTimeRecord",
    "SectorMembershipRecord",
    "BreadthRecord",
    "InstitutionalFlowRecord",
    "SectorRank",
    "MarketIntelligenceError",
    "MissingTimestampError",
    "SourceConflictError",
    "MissingMembershipError",
    "NewsItem",
    "FundamentalSnapshot",
    "QuantamentalDecisionManifest",
    "SentimentLabel",
    "NewsUrgency",
    "NewsCategory",
    "HealthTier",
    "CompositeBias",
    "MacroNewsItem",
    "CorporateCalendarEvent",
    "AnalystConsensus",
    "CollectionScheduleConfig",
    "FinancialSentimentAnalyzer",
    "FundamentalAnalyzer",
    "NewsCollector",
    "FundamentalCollector",
    "NewsFundamentalAgent",
    "MarketIntelligenceAssistant",
    "StockDecisionEngine",
    "SelectionTier",
    "TradeAction",
    "StockSelectionCandidate",
    "StockSelectionManifest",
    "TradeDecisionResult",
]


