"""
Algo Lab — Stage 8 Market Intelligence Contracts & Schemas
Implements point-in-time provenance schemas, publication timestamp eligibility,
versioned sector constituent records, and structural fail-closed exception types.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, Any, List, Optional


class MarketIntelligenceError(ValueError):
    """Base exception for Stage 8 market intelligence errors."""
    pass


class MissingTimestampError(MarketIntelligenceError):
    """Raised when publication timestamp (T_pub) cannot be established."""
    pass


class SourceConflictError(MarketIntelligenceError):
    """Raised when primary and secondary data feeds conflict for identical timestamps."""
    pass


class MissingMembershipError(MarketIntelligenceError):
    """Raised when point-in-time sector membership for date t cannot be resolved."""
    pass


class StaleDataWarning(UserWarning):
    """Warning issued when institutional flows or breadth statistics are un-updated."""
    pass


@dataclass(frozen=True)
class PointInTimeRecord:
    """Point-in-time data provenance record enforcing INV-26."""
    event_date: date                   # Date the economic event occurred (T_event)
    publication_timestamp: datetime    # Exact UTC timestamp data became public (T_pub)
    retrieval_timestamp: datetime      # UTC timestamp dataset was ingested (T_ret)
    dataset_version_id: str            # Version identifier of the dataset
    revision_sequence_id: int          # Revision sequence number (0 = initial, 1 = revised)
    payload: Dict[str, Any]            # Metric payload

    def is_eligible_at(self, simulation_time: datetime) -> bool:
        """Eligibility rule (INV-26): Available strictly if T_pub <= t_sim."""
        if not self.publication_timestamp:
            raise MissingTimestampError("Publication timestamp (T_pub) is missing or unestablished.")
        return self.publication_timestamp <= simulation_time


@dataclass(frozen=True)
class SectorMembershipRecord:
    """Versioned historical sector constituent record enforcing INV-27."""
    sector_id: str                      # e.g., "NIFTY_BANK"
    effective_date: date                # Date constituent change took effect
    added_symbols: List[str]            # Symbols added on effective_date
    removed_symbols: List[str]          # Symbols removed on effective_date
    active_constituents: List[str]      # Complete active constituent list as of effective_date


@dataclass(frozen=True)
class BreadthRecord:
    """Market breadth statistics snapshot for a specified asset universe."""
    timestamp: datetime
    universe_id: str
    advances_count: int
    declines_count: int
    unchanged_count: int
    ad_ratio: float
    pct_above_20_sma: float
    pct_above_50_sma: float
    pct_above_200_sma: float


@dataclass(frozen=True)
class InstitutionalFlowRecord:
    """Institutional investor net flow snapshot (FII / DII)."""
    event_date: date
    publication_timestamp: datetime
    fii_cash_net: float
    dii_cash_net: float
    fii_index_futures_net: float = 0.0
    fii_index_options_net: float = 0.0
    fii_stock_futures_net: float = 0.0
    fii_cash_buy: float = 0.0
    fii_cash_sell: float = 0.0
    dii_cash_buy: float = 0.0
    dii_cash_sell: float = 0.0


@dataclass(frozen=True)
class SectorRank:
    """Sector relative strength and rotation leaderboard entry."""
    sector_id: str
    relative_strength_score: float
    rank: int
    momentum_category: str  # "LEADING", "WEAKENING", "LAGGING", "IMPROVING"
