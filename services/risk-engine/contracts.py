"""Algo Lab Risk Engine Contracts.

Adheres to Non-Negotiable Principles:
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 15: AI must never override hard risk controls.
- Principle 21: Evaluate portfolio-level risk, not only individual trades.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RiskRejectionCode(str, Enum):
    APPROVED = "APPROVED"
    EXCEEDS_MAX_CAPITAL = "EXCEEDS_MAX_CAPITAL"
    MISSING_STOP_LOSS = "MISSING_STOP_LOSS"
    DRAWDOWN_LIMIT_BREACHED = "DRAWDOWN_LIMIT_BREACHED"
    DAILY_LOSS_LIMIT_BREACHED = "DAILY_LOSS_LIMIT_BREACHED"
    MAX_POSITIONS_REACHED = "MAX_POSITIONS_REACHED"
    UNAUTHORIZED_LEVERAGE = "UNAUTHORIZED_LEVERAGE"
    DATA_QUALITY_UNSATISFACTORY = "DATA_QUALITY_UNSATISFACTORY"
    PROHIBITED_INSTRUMENT = "PROHIBITED_INSTRUMENT"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"


class HardRiskLimits(BaseModel):
    """Immutable hard constraints that NO strategy or AI can override."""

    max_capital_per_trade_pct: float = Field(default=0.05, ge=0.01, le=0.20)
    max_portfolio_drawdown_pct: float = Field(default=0.15, ge=0.01, le=0.50)
    max_daily_loss_pct: float = Field(default=0.03, ge=0.01, le=0.10)
    max_open_positions: int = Field(default=10, ge=1, le=50)
    enforce_mandatory_stop_loss: bool = True
    max_leverage: float = Field(default=1.0, ge=1.0, le=1.0, description="Strictly 1.0x in initial foundation")


class RiskEvaluationResult(BaseModel):
    """The verdict of the independent Risk Engine on a proposed order."""

    is_approved: bool
    rejection_code: RiskRejectionCode = RiskRejectionCode.APPROVED
    rejection_reason: Optional[str] = None
    approved_quantity: int = 0
    adjusted_stop_loss: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IRiskEngine(ABC):
    """Independent Risk Engine Interface."""

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        price: float,
        proposed_quantity: int,
        stop_loss: Optional[float],
        current_portfolio_value: float,
        current_daily_loss_pct: float,
        current_drawdown_pct: float,
        current_open_positions_count: int,
    ) -> RiskEvaluationResult:
        """Validates an order against hard portfolio and asset-level limits."""
        pass
