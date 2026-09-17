"""
Algo Lab — Stage 10 Portfolio Execution Schemas & Exceptions
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
import math


class PortfolioExecutionError(Exception):
    """Base exception for Stage 10 portfolio execution."""
    pass


class ExecutionError(PortfolioExecutionError):
    """Raised on execution router failure, illiquidity, or NaN/Inf inputs."""
    pass


class ASTIsolationError(PortfolioExecutionError):
    """Raised when AST scanner detects prohibited broker or socket imports."""
    pass


@dataclass(frozen=True)
class MarketImpactConfig:
    gamma_impact_coefficient: float = 0.50     # Dynamic impact scaling factor
    max_volume_participation_pct: float = 0.10   # Max bar volume participation (10%)
    volatility_lookback_bars: int = 20          # Historical volatility window
    adv_lookback_bars: int = 20                 # Average Daily Volume window

    def __post_init__(self):
        for name, val in [("gamma_impact_coefficient", self.gamma_impact_coefficient),
                          ("max_volume_participation_pct", self.max_volume_participation_pct)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise ExecutionError(f"Non-finite value in MarketImpactConfig for {name}: {val}")

        if self.gamma_impact_coefficient < 0.0:
            raise ValueError(f"gamma_impact_coefficient cannot be negative: {self.gamma_impact_coefficient}")
        if self.max_volume_participation_pct <= 0.0 or self.max_volume_participation_pct > 1.0:
            raise ValueError(f"max_volume_participation_pct must be in (0.0, 1.0]: {self.max_volume_participation_pct}")


@dataclass(frozen=True)
class ExecutionFill:
    fill_id: str
    order_id: str
    strategy_id: str
    symbol: str
    fill_timestamp: datetime
    fill_quantity: int
    fill_price: float
    market_impact_cost: float
    slippage_cost: float
    transaction_fee: float
    is_partial_fill: bool
    remaining_quantity: int

    def __post_init__(self):
        for name, val in [("fill_price", self.fill_price), ("market_impact_cost", self.market_impact_cost),
                          ("slippage_cost", self.slippage_cost), ("transaction_fee", self.transaction_fee)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise ExecutionError(f"Non-finite value in ExecutionFill for {name}: {val}")


@dataclass(frozen=True)
class PerformanceAttributionRecord:
    timestamp: datetime
    total_portfolio_pnl: float
    strategy_selection_pnl: float
    macro_timing_pnl: float
    sector_rotation_pnl: float
    risk_budget_overlay_pnl: float
    execution_friction_drag: float
    attribution_residual: float = 0.0

    def __post_init__(self):
        for name, val in [("total_portfolio_pnl", self.total_portfolio_pnl),
                          ("strategy_selection_pnl", self.strategy_selection_pnl),
                          ("macro_timing_pnl", self.macro_timing_pnl),
                          ("sector_rotation_pnl", self.sector_rotation_pnl),
                          ("execution_friction_drag", self.execution_friction_drag)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise ExecutionError(f"Non-finite value in PerformanceAttributionRecord for {name}: {val}")
