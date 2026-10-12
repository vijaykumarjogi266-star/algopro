"""Algo Lab Pluggable Risk Signal Hooks.

Enables extensible pre-trade and pre-allocation risk filters (VaR, Expected Shortfall, Tail Risk)
without modifying the core hard risk boundary contracts.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field

from services.risk_engine.contracts import RiskEvaluationResult, RiskRejectionCode
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class IRiskFilterHook(ABC):
    """Abstract interface for extensible pre-trade risk filters."""

    @abstractmethod
    def evaluate_hook(
        self,
        symbol: str,
        price: float,
        proposed_quantity: int,
        portfolio_value: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[RiskEvaluationResult]:
        """Returns None if approved, or a RiskEvaluationResult if rejected."""
        pass


class ValueAtRiskFilter(IRiskFilterHook):
    """Rejects trades if historical Value at Risk (VaR) exceeds maximum allowed budget."""

    def __init__(self, confidence_level: float = 0.95, max_var_pct: float = 0.05):
        self.confidence_level = confidence_level
        self.max_var_pct = max_var_pct

    def evaluate_hook(
        self,
        symbol: str,
        price: float,
        proposed_quantity: int,
        portfolio_value: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[RiskEvaluationResult]:
        ctx = context or {}
        historical_returns = ctx.get("historical_returns")
        if not historical_returns or len(historical_returns) < 10:
            return None  # Insufficient data, defer to baseline checks

        returns_arr = np.array(historical_returns)
        alpha = 1.0 - self.confidence_level
        var_pct = float(-np.percentile(returns_arr, alpha * 100))

        trade_value = proposed_quantity * price
        allocated_weight = (trade_value / portfolio_value) if portfolio_value > 0 else 1.0
        projected_var = var_pct * allocated_weight

        if projected_var > self.max_var_pct:
            from datetime import datetime, timezone
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.EXCEEDS_MAX_CAPITAL,
                rejection_reason=f"Projected VaR ({projected_var*100:.2f}%) exceeds maximum VaR threshold ({self.max_var_pct*100:.2f}%) at {int(self.confidence_level*100)}% confidence",
                approved_quantity=0,
                timestamp=datetime.now(timezone.utc),
            )
        return None


class ExpectedShortfallFilter(IRiskFilterHook):
    """Rejects trades if Conditional VaR (Expected Shortfall / Tail Risk) exceeds threshold."""

    def __init__(self, confidence_level: float = 0.95, max_cvar_pct: float = 0.07):
        self.confidence_level = confidence_level
        self.max_cvar_pct = max_cvar_pct

    def evaluate_hook(
        self,
        symbol: str,
        price: float,
        proposed_quantity: int,
        portfolio_value: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[RiskEvaluationResult]:
        ctx = context or {}
        historical_returns = ctx.get("historical_returns")
        if not historical_returns or len(historical_returns) < 10:
            return None

        returns_arr = np.array(historical_returns)
        alpha = 1.0 - self.confidence_level
        cutoff = np.percentile(returns_arr, alpha * 100)
        tail_losses = returns_arr[returns_arr <= cutoff]
        cvar_pct = float(-tail_losses.mean()) if len(tail_losses) > 0 else 0.0

        trade_value = proposed_quantity * price
        allocated_weight = (trade_value / portfolio_value) if portfolio_value > 0 else 1.0
        projected_cvar = cvar_pct * allocated_weight

        if projected_cvar > self.max_cvar_pct:
            from datetime import datetime, timezone
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.EXCEEDS_MAX_CAPITAL,
                rejection_reason=f"Projected CVaR/Expected Shortfall ({projected_cvar*100:.2f}%) exceeds threshold ({self.max_cvar_pct*100:.2f}%)",
                approved_quantity=0,
                timestamp=datetime.now(timezone.utc),
            )
        return None
