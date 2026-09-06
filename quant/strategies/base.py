"""Algo Lab Strategy Contract & Base Interface.

Adheres to Non-Negotiable Principles:
- Principle 1: Never force a trade.
- Principle 2: WAIT is a valid decision.
- Principle 4: No look-ahead bias (strict point-in-time access).
- Principle 8: Every strategy must be versioned.
- Principle 18: All trading decisions must be explainable through evidence.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from data.schemas.contracts import OHLCVBar
from services.data_quality.validator import DataQualityReport


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"  # Principle 2: Explicitly supported & logged
    EXIT = "EXIT"


class StrategyDecision(BaseModel):
    """Immutable record of an evaluated trading opportunity."""

    symbol: str
    decision_timestamp: datetime
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score based on evidence confluence")
    reason: str = Field(..., description="Explainable reason citing evidence")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Snapshot of evidentiary indicator values")
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    position_sizing_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rejection_reason: Optional[str] = None


class BaseStrategy(ABC):
    """Abstract Strategy Contract that all quantitative strategies must inherit.
    
    Strategies are decision engines that evaluate evidence and propose signals.
    They NEVER directly execute orders or override risk parameters.
    """

    def __init__(
        self,
        strategy_id: str,
        name: str,
        version: str,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.strategy_id = strategy_id
        self.name = name
        self.version = version
        self.parameters = parameters or {}

    @abstractmethod
    def evaluate(
        self,
        current_bar: OHLCVBar,
        history: List[OHLCVBar],
        data_quality: DataQualityReport,
    ) -> StrategyDecision:
        """Evaluates market state point-in-time.
        
        Args:
            current_bar: The latest closed bar (no lookahead into next bar).
            history: Historical bars up to current_bar.
            data_quality: Report on current dataset state.
            
        Returns:
            StrategyDecision containing explainable signal and evidence.
        """
        pass

    def default_wait(self, symbol: str, timestamp: datetime, reason: str = "No setup criteria met") -> StrategyDecision:
        """Convenience generator for WAIT decisions (Principle 2)."""
        return StrategyDecision(
            symbol=symbol,
            decision_timestamp=timestamp,
            signal=SignalType.WAIT,
            confidence=0.0,
            reason=reason,
            evidence={},
        )
