"""Algo Lab Core Data Schemas & Contracts.

Defines OHLCV Bar data, exchange metadata, timeframes, and data quality states
supporting Indian markets (NSE, BSE, MCX) and multi-asset classes.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"
    INDEX = "INDEX"


class TimeFrame(str, Enum):
    TICK = "TICK"
    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"


class DataQualityStatus(str, Enum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    CORRUPTED = "CORRUPTED"
    INCOMPLETE = "INCOMPLETE"
    REJECTED = "REJECTED"


class QualitySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class QualityCheckResult(BaseModel):
    check_name: str
    passed: bool
    severity: QualitySeverity
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatasetMetadata(BaseModel):
    source: str
    dataset_version: str
    symbol: str
    exchange: Exchange
    asset_class: AssetClass
    timeframe: TimeFrame
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_point_in_time: bool = True
    corporate_actions_adjusted: bool = True


class OHLCVBar(BaseModel):
    """Standardized Point-in-Time OHLCV Bar Contract.
    
    Adheres to Principle 3: Bad or uncertain data must not produce a trading decision.
    Adheres to Principle 4: No look-ahead bias.
    Adheres to Principle 9: Every dataset must be versioned.
    """

    symbol: str
    exchange: Exchange
    timeframe: TimeFrame
    market_timestamp: datetime
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    open: float = Field(gt=0, description="Opening price")
    high: float = Field(gt=0, description="High price")
    low: float = Field(gt=0, description="Low price")
    close: float = Field(gt=0, description="Closing price")
    volume: float = Field(ge=0, description="Trading volume in shares/contracts")
    turnover: Optional[float] = Field(default=None, ge=0, description="Total value traded (INR)")
    vwap: Optional[float] = Field(default=None, gt=0, description="Volume Weighted Average Price")
    open_interest: Optional[float] = Field(default=None, ge=0, description="Open interest for derivatives")

    data_source: str = "default_feed"
    dataset_version: str = "v1.0.0"
    quality_status: DataQualityStatus = DataQualityStatus.VALID
    quality_checks: List[QualityCheckResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ohlc_consistency(self) -> "OHLCVBar":
        """Deterministic mathematical sanity check for bar integrity."""
        # High must be the highest, low must be the lowest
        max_oc = max(self.open, self.close)
        min_oc = min(self.open, self.close)

        if self.high < max_oc:
            raise ValueError(f"Bar high ({self.high}) is lower than max(open, close) ({max_oc})")
        if self.low > min_oc:
            raise ValueError(f"Bar low ({self.low}) is higher than min(open, close) ({min_oc})")
        return self

    def is_usable_for_trading(self) -> bool:
        """Determines if the bar satisfies quality requirements to produce a decision."""
        if self.quality_status in (DataQualityStatus.CORRUPTED, DataQualityStatus.REJECTED):
            return False
        for check in self.quality_checks:
            if not check.passed and check.severity == QualitySeverity.CRITICAL:
                return False
        return True
