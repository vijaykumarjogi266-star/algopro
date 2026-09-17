"""
Algo Lab — Stage 9 Multi-Strategy Portfolio Optimization Schemas & Exceptions
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from enum import Enum
import math


class WeightingScheme(str, Enum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    VOLATILITY_PARITY = "VOLATILITY_PARITY"
    DEGRADATION_ADJUSTED = "DEGRADATION_ADJUSTED"
    MACRO_ALIGNED = "MACRO_ALIGNED"


class PortfolioOptimizationError(Exception):
    """Base exception for Stage 9 portfolio optimization."""
    pass


class AllocationError(PortfolioOptimizationError):
    """Raised on invalid capital allocation, float overflow, or NaN/Inf values."""
    pass


class SolvencyError(PortfolioOptimizationError):
    """Raised when rebalance fees/friction exceed available cash."""
    pass


class MissingMetricError(PortfolioOptimizationError):
    """Raised when required out-of-sample strategy metrics are missing."""
    pass


class ASTIsolationError(PortfolioOptimizationError):
    """Raised when AST scanner detects prohibited broker or socket imports."""
    pass


@dataclass(frozen=True)
class StrategyAllocationConfig:
    strategy_id: str
    base_weight: float                 # Target weight in [0.0, 1.0]
    max_weight_cap: float = 0.40       # Hard upper bound on weight
    min_weight_floor: float = 0.0      # Hard lower bound
    max_degradation_threshold: float = 0.40  # Max OOS degradation score before throttling

    def __post_init__(self):
        if not self.strategy_id or not isinstance(self.strategy_id, str):
            raise ValueError("strategy_id must be a non-empty string")
        
        for name, val in [("base_weight", self.base_weight), ("max_weight_cap", self.max_weight_cap),
                          ("min_weight_floor", self.min_weight_floor), ("max_degradation_threshold", self.max_degradation_threshold)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise AllocationError(f"Non-finite value detected for {name}: {val}")

        if self.base_weight < 0.0:
            raise ValueError(f"base_weight cannot be negative: {self.base_weight}")
        if self.max_weight_cap < 0.0 or self.max_weight_cap > 1.0:
            raise ValueError(f"max_weight_cap must be in [0.0, 1.0]: {self.max_weight_cap}")


@dataclass(frozen=True)
class PortfolioRiskBudget:
    max_portfolio_volatility_annual: float = 0.25  # Max allowable annual std dev
    max_aggregate_drawdown_pct: float = 0.15       # Max aggregate drawdown
    max_single_strategy_weight: float = 0.35       # Hard cap across all strategies
    max_turnover_per_rebalance_pct: float = 0.20   # Max turnover per rebalance
    cash_reserve_floor_pct: float = 0.05           # Mandatory cash reserve floor

    def __post_init__(self):
        for name, val in [("max_portfolio_volatility_annual", self.max_portfolio_volatility_annual),
                          ("max_aggregate_drawdown_pct", self.max_aggregate_drawdown_pct),
                          ("max_single_strategy_weight", self.max_single_strategy_weight),
                          ("max_turnover_per_rebalance_pct", self.max_turnover_per_rebalance_pct),
                          ("cash_reserve_floor_pct", self.cash_reserve_floor_pct)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise AllocationError(f"Non-finite value detected in risk budget for {name}: {val}")


@dataclass(frozen=True)
class StrategyAllocationRecord:
    timestamp: datetime
    strategy_id: str
    assigned_weight: float
    allocated_capital: float
    degradation_score: float
    macro_regime_multiplier: float
    is_throttled: bool
    reason: str


@dataclass(frozen=True)
class RebalancePlan:
    rebalance_date: date
    simulation_time: datetime
    target_weights: Dict[str, float]
    target_cash_weight: float
    proposed_orders: List[Dict[str, Any]]
    estimated_turnover_pct: float
    estimated_friction_cost: float
    residual_cash_unallocated: float = 0.0
