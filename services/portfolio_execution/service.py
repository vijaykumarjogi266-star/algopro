"""
Algo Lab — Stage 10 Portfolio Execution Service Interface
"""

from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional
import hashlib

from services.evaluation_engine.manifest import EvaluationEnvironment, ExperimentManifest
from services.portfolio_optimization.contracts import RebalancePlan
from services.portfolio_execution.contracts import (
    MarketImpactConfig,
    ExecutionFill,
    PerformanceAttributionRecord,
)
from services.portfolio_execution.execution_router import ExecutionRouter
from services.portfolio_execution.attribution_engine import PerformanceAttributionEngine


class PortfolioExecutionService:
    """Unified service interface for Stage 10 Multi-Strategy Execution Simulation & Attribution."""

    def __init__(self, environment: EvaluationEnvironment = EvaluationEnvironment.OFFLINE_SIMULATION):
        # AT-189: Live environment lockout gate
        if environment == EvaluationEnvironment.LIVE:
            raise PermissionError("LIVE is strictly forbidden in PortfolioExecutionService")
        self.environment = environment

    def execute_rebalance_plan(
        self,
        rebalance_plan: RebalancePlan,
        bar_data: Dict[str, Dict[str, Any]],
        current_cash_balance: float,
        config: MarketImpactConfig = None,
    ) -> Tuple[List[ExecutionFill], float]:
        """Routes rebalance plan orders and executes fills against bar volume limits."""
        return ExecutionRouter.match_bar_orders(
            rebalance_plan=rebalance_plan,
            bar_data=bar_data,
            current_cash_balance=current_cash_balance,
            config=config,
        )

    def generate_ai_execution_summary(
        self,
        manifest: ExperimentManifest,
        fills: List[ExecutionFill],
        attribution: Optional[PerformanceAttributionRecord] = None,
    ) -> str:
        """Generates AI trade attribution markdown analysis without mutating manifest (INV-45 / AT-185)."""
        orig_fp = manifest.compute_fingerprint()

        summary_lines = [
            "# Stage 10 AI Trade Attribution & Execution Summary",
            f"- **Strategy ID:** {manifest.strategy_id}",
            f"- **Environment:** {manifest.environment.value}",
            f"- **Fills Count:** {len(fills)}",
        ]

        if attribution:
            summary_lines.extend([
                f"- **Total Gross PnL:** ₹{attribution.total_portfolio_pnl:,.2f}",
                f"- **Strategy Selection Alpha PnL:** ₹{attribution.strategy_selection_pnl:,.2f}",
                f"- **Macro Timing PnL:** ₹{attribution.macro_timing_pnl:,.2f}",
                f"- **Execution Friction Drag:** ₹{attribution.execution_friction_drag:,.2f}",
                f"- **Attribution Residual:** {attribution.attribution_residual:.6f}",
            ])

        # Assert manifest fingerprint is untouched (INV-45)
        post_fp = manifest.compute_fingerprint()
        assert orig_fp == post_fp, "AI summary generator illegally mutated manifest fingerprint!"

        return "\n".join(summary_lines)
