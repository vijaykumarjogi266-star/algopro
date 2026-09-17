"""
Algo Lab — Stage 9 Portfolio Optimization Service Interface
"""

from datetime import date, datetime, timezone
from typing import Dict, List, Any, Optional
import hashlib

from services.evaluation_engine.manifest import EvaluationEnvironment, ExperimentManifest
from services.portfolio_optimization.contracts import (
    WeightingScheme,
    StrategyAllocationConfig,
    PortfolioRiskBudget,
    StrategyAllocationRecord,
    RebalancePlan,
    AllocationError,
)
from services.portfolio_optimization.risk_budgeting import RiskBudgetingEngine
from services.portfolio_optimization.dynamic_allocator import DynamicAllocationEngine
from services.portfolio_optimization.rebalancer import PortfolioRebalancer


class PortfolioOptimizationService:
    """Unified service interface for Stage 9 Multi-Strategy Portfolio Optimization."""

    def __init__(self, environment: EvaluationEnvironment = EvaluationEnvironment.OFFLINE_SIMULATION):
        # AT-158: Live environment lockout gate
        if environment == EvaluationEnvironment.LIVE:
            raise PermissionError("LIVE is strictly forbidden in PortfolioOptimizationService")
        self.environment = environment

    def run_portfolio_allocation(
        self,
        configs: List[StrategyAllocationConfig],
        strategy_degradation_scores: Dict[str, float],
        macro_regime_score: float = 0.0,
        risk_budget: PortfolioRiskBudget = None,
        scheme: WeightingScheme = WeightingScheme.EQUAL_WEIGHT,
        current_drawdown_pct: float = 0.0,
        current_volatility_annual: float = 0.15,
        stale_macro_warning: bool = False,
        timestamp: datetime = None,
    ) -> Tuple[Dict[str, float], float, List[StrategyAllocationRecord]]:
        """Computes risk-budgeted strategy allocations."""
        if risk_budget is None:
            risk_budget = PortfolioRiskBudget()

        # 1. Dynamic strategy allocation
        raw_weights, cash_w, records = DynamicAllocationEngine.calculate_allocations(
            scheme=scheme,
            configs=configs,
            strategy_degradation_scores=strategy_degradation_scores,
            macro_regime_score=macro_regime_score,
            cash_floor_pct=risk_budget.cash_reserve_floor_pct,
            stale_macro_warning=stale_macro_warning,
            timestamp=timestamp,
        )

        # 2. Risk budget check & multi-limit cascade
        config_dict = {c.strategy_id: c for c in configs}
        is_approved, target_cash_w, final_weights, reason = RiskBudgetingEngine.evaluate_risk_budget(
            current_drawdown_pct=current_drawdown_pct,
            current_volatility_annual=current_volatility_annual,
            proposed_weights=raw_weights,
            configs=config_dict,
            risk_budget=risk_budget,
        )

        return final_weights, target_cash_w, records

    def generate_ai_portfolio_summary(
        self,
        manifest: ExperimentManifest,
        rebalance_plan: Optional[RebalancePlan] = None,
    ) -> str:
        """Generates AI analysis summary markdown without mutating manifest (INV-34 / AT-154)."""
        orig_fp = manifest.compute_fingerprint()

        summary_lines = [
            "# Stage 9 AI Portfolio Allocation Analysis",
            f"- **Strategy ID:** {manifest.strategy_id}",
            f"- **Environment:** {manifest.environment.value}",
            f"- **Initial Capital:** ₹{manifest.initial_capital:,.2f}",
        ]

        if rebalance_plan:
            summary_lines.extend([
                f"- **Rebalance Date:** {rebalance_plan.rebalance_date}",
                f"- **Target Cash Weight:** {rebalance_plan.target_cash_weight:.2%}",
                f"- **Estimated Turnover:** {rebalance_plan.estimated_turnover_pct:.2%}",
                f"- **Proposed Orders Count:** {len(rebalance_plan.proposed_orders)}",
            ])

        # Assert manifest fingerprint is untouched (INV-34)
        post_fp = manifest.compute_fingerprint()
        assert orig_fp == post_fp, "AI summary generator illegally mutated manifest fingerprint!"

        return "\n".join(summary_lines)
