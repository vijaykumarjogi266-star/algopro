"""
Algo Lab — Stage 9 Dynamic Risk Budgeting Engine
"""

from typing import Dict, Tuple, Any
import math
from services.portfolio_optimization.contracts import (
    PortfolioRiskBudget,
    StrategyAllocationConfig,
    AllocationError,
)


class RiskBudgetingEngine:
    """Enforces aggregate portfolio drawdown limits, volatility limits, and strategy concentration caps."""

    @staticmethod
    def evaluate_risk_budget(
        current_drawdown_pct: float,
        current_volatility_annual: float,
        proposed_weights: Dict[str, float],
        configs: Dict[str, StrategyAllocationConfig],
        risk_budget: PortfolioRiskBudget,
    ) -> Tuple[bool, float, Dict[str, float], str]:
        """Evaluates proposed strategy weights against risk budget constraints.
        
        Returns:
            Tuple[is_approved, target_cash_weight, adjusted_weights, reason]
        """
        # 1. Non-finite check (INV-37)
        for name, val in [("drawdown", current_drawdown_pct), ("volatility", current_volatility_annual)]:
            if math.isnan(val) or math.isinf(val):
                raise AllocationError(f"Non-finite risk metric detected: {name}={val}")

        for s_id, w in proposed_weights.items():
            if math.isnan(w) or math.isinf(w):
                raise AllocationError(f"Non-finite proposed weight for {s_id}: {w}")

        # 2. Simultaneous Multi-Limit Risk Breach Cascade (INV-29 / AT-156 / AT-167)
        drawdown_breached = current_drawdown_pct > risk_budget.max_aggregate_drawdown_pct
        volatility_breached = current_volatility_annual > risk_budget.max_portfolio_volatility_annual

        if drawdown_breached or volatility_breached:
            reasons = []
            if drawdown_breached:
                reasons.append(f"Drawdown {current_drawdown_pct:.2%} > limit {risk_budget.max_aggregate_drawdown_pct:.2%}")
            if volatility_breached:
                reasons.append(f"Volatility {current_volatility_annual:.2%} > limit {risk_budget.max_portfolio_volatility_annual:.2%}")

            # Force 100% Cash allocation
            zero_weights = {s_id: 0.0 for s_id in proposed_weights.keys()}
            return False, 1.0, zero_weights, f"Risk Budget Breach: {'; '.join(reasons)}"

        # 3. Strategy Concentration Caps & Available Equity Pool Capping
        max_equity_pool = 1.0 - risk_budget.cash_reserve_floor_pct
        adjusted_weights = {}
        total_equity_weight = 0.0

        # Process in deterministic alphabetical order
        for s_id in sorted(proposed_weights.keys()):
            w = proposed_weights[s_id]
            cfg = configs.get(s_id)
            cap = risk_budget.max_single_strategy_weight
            if cfg is not None:
                cap = min(cap, cfg.max_weight_cap)

            # Cap individual strategy weight
            capped_w = min(w, cap)
            adjusted_weights[s_id] = round(max(0.0, capped_w), 6)
            total_equity_weight += adjusted_weights[s_id]

        # Scaled down if total equity weight exceeds available equity pool
        if total_equity_weight > max_equity_pool:
            scale_factor = max_equity_pool / total_equity_weight
            total_equity_weight = 0.0
            for s_id in sorted(adjusted_weights.keys()):
                adjusted_weights[s_id] = round(adjusted_weights[s_id] * scale_factor, 6)
                total_equity_weight += adjusted_weights[s_id]

        target_cash_weight = round(1.0 - total_equity_weight, 6)
        return True, target_cash_weight, adjusted_weights, "Risk budget checks passed"
