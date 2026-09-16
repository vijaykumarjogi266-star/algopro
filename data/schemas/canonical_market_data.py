"""Algo Lab Canonical Market Data Contracts (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 3: Bad or uncertain data must not produce a trading decision.
- Principle 4: No look-ahead bias.
- Principle 9: Every dataset must be versioned.
- Principle 13: Data validation must fail closed.
- Strict OHLCV mathematical sanity, timezone integrity, and chronological ordering.
"""

from datetime import datetime, timezone
import math
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from data.schemas.contracts import Exchange, TimeFrame, DataQualityStatus


class CanonicalMarketDataBar(BaseModel):
    """Canonical Market Data Bar Contract for Indian & Global Markets.
    
    Validates:
    - Timezone consistency (must be UTC timezone-aware)
    - Valid uppercase symbol
    - Positive OHLC prices (gt=0)
    - Mathematical OHLC consistency (high >= max(open, close), low <= min(open, close))
    - Non-negative volume (ge=0)
    - Optional derivatives metrics: open_interest (ge=0), trade_count (ge=0)
    - Absolute rejection of NaN, Inf, and silent data repair.
    """

    timestamp: datetime = Field(description="Bar opening/start UTC timestamp")
    symbol: str = Field(min_length=1, max_length=30, description="Normalized trading symbol")
    exchange: str = Field(default="NSE", min_length=2, max_length=10, description="Exchange identifier")
    timeframe: str = Field(default="1d", min_length=1, description="Bar timeframe")

    open: float = Field(gt=0.0, description="Opening price")
    high: float = Field(gt=0.0, description="High price")
    low: float = Field(gt=0.0, description="Low price")
    close: float = Field(gt=0.0, description="Closing price")
    volume: float = Field(ge=0.0, description="Volume traded")

    open_interest: Optional[float] = Field(default=None, ge=0.0, description="Open interest")
    trade_count: Optional[int] = Field(default=None, ge=0, description="Number of trades in bar")
    turnover: Optional[float] = Field(default=None, ge=0.0, description="Total traded value INR")
    vwap: Optional[float] = Field(default=None, gt=0.0, description="Volume-weighted average price")

    quality_status: DataQualityStatus = Field(default=DataQualityStatus.VALID)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC required)")
        # Normalize to UTC
        return v.astimezone(timezone.utc)

    @field_validator("symbol")
    @classmethod
    def validate_symbol_format(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("Symbol cannot be empty")
        if not re.match(r"^[A-Z0-9_\-\.\&]+$", s):
            raise ValueError(f"Invalid characters in symbol '{s}'")
        return s

    @field_validator("open", "high", "low", "close", "volume", "open_interest", "trade_count", "turnover", "vwap", mode="before")
    @classmethod
    def validate_non_nan_inf(cls, v: Any) -> Any:
        if v is not None and isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v):
                raise ValueError("NaN or Infinite values are strictly prohibited")
        return v

    @model_validator(mode="after")
    def validate_ohlc_relationships(self) -> "CanonicalMarketDataBar":
        """Strict mathematical validation of OHLC prices."""
        max_oc = max(self.open, self.close)
        min_oc = min(self.open, self.close)

        if self.high < max_oc:
            raise ValueError(f"Bar high ({self.high}) is lower than max(open, close) ({max_oc})")
        if self.low > min_oc:
            raise ValueError(f"Bar low ({self.low}) is higher than min(open, close) ({min_oc})")
        if self.high < self.low:
            raise ValueError(f"Bar high ({self.high}) is lower than low ({self.low})")
        return self


class MarketDataBatchValidationResult(BaseModel):
    is_valid: bool
    total_bars: int
    errors: List[str] = Field(default_factory=list)
    quarantined_bars: List[Dict[str, Any]] = Field(default_factory=list)
    duplicate_count: int = 0
    out_of_order_count: int = 0


class CanonicalMarketDataValidator:
    """Validates entire market data series for ordering, duplicates, and integrity."""

    @staticmethod
    def validate_series(
        bars: List[CanonicalMarketDataBar],
        allow_duplicates: bool = False,
    ) -> MarketDataBatchValidationResult:
        if not bars:
            return MarketDataBatchValidationResult(
                is_valid=False,
                total_bars=0,
                errors=["Market data series is empty"],
            )

        errors: List[str] = []
        quarantined: List[Dict[str, Any]] = []
        seen_timestamps: Dict[str, datetime] = {}
        duplicates = 0
        out_of_order = 0

        # Group by (symbol, exchange, timeframe) to check ordering and duplicates per instrument
        grouped: Dict[str, List[CanonicalMarketDataBar]] = {}
        for b in bars:
            key = f"{b.symbol}:{b.exchange}:{b.timeframe}"
            grouped.setdefault(key, []).append(b)

        for key, series in grouped.items():
            last_ts: Optional[datetime] = None
            for idx, bar in enumerate(series):
                # 1. Duplicate check
                dedup_key = f"{key}:{bar.timestamp.isoformat()}"
                if dedup_key in seen_timestamps:
                    duplicates += 1
                    errors.append(f"Duplicate timestamp detected for {key} at {bar.timestamp.isoformat()}")
                    quarantined.append({"index": idx, "bar": bar.model_dump(), "reason": "duplicate_timestamp"})
                else:
                    seen_timestamps[dedup_key] = bar.timestamp

                # 2. Chronological ordering check
                if last_ts is not None and bar.timestamp < last_ts:
                    out_of_order += 1
                    errors.append(
                        f"Out-of-order timestamp in {key}: {bar.timestamp.isoformat()} preceded by {last_ts.isoformat()}"
                    )
                    quarantined.append({"index": idx, "bar": bar.model_dump(), "reason": "out_of_order"})

                last_ts = bar.timestamp

        is_valid = len(errors) == 0
        return MarketDataBatchValidationResult(
            is_valid=is_valid,
            total_bars=len(bars),
            errors=errors,
            quarantined_bars=quarantined,
            duplicate_count=duplicates,
            out_of_order_count=out_of_order,
        )
