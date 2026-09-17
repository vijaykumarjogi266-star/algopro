"""
Algo Lab — Stage 10 Multi-Factor Brinson Performance & Friction Attribution Engine
"""

from datetime import datetime
from typing import List
import math

from services.portfolio_execution.contracts import (
    ExecutionFill,
    PerformanceAttributionRecord,
    ExecutionError,
)


class PerformanceAttributionEngine:
    """Decomposes portfolio PnL into Selection Alpha, Macro Timing, Sector Rotation, and Friction Drag."""

    @staticmethod
    def compute_brinson_attribution(
        timestamp: datetime,
        total_gross_pnl: float,
        strategy_selection_pnl: float,
        macro_timing_pnl: float,
        sector_rotation_pnl: float,
        risk_budget_overlay_pnl: float,
        fills: List[ExecutionFill],
    ) -> PerformanceAttributionRecord:
        """Computes multi-factor return attribution and friction drag.

        Returns:
            PerformanceAttributionRecord
        """
        # Non-finite check (INV-37 / AT-174)
        for name, val in [("total_gross_pnl", total_gross_pnl), ("selection_pnl", strategy_selection_pnl),
                          ("macro_pnl", macro_timing_pnl), ("sector_pnl", sector_rotation_pnl),
                          ("risk_overlay_pnl", risk_budget_overlay_pnl)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise ExecutionError(f"Non-finite attribution metric for {name}: {val}")

        # Compute total execution friction drag across fills (AT-172)
        execution_friction_drag = 0.0
        for fill in fills:
            # Impact cost + transaction fees
            execution_friction_drag += fill.market_impact_cost + fill.transaction_fee

        execution_friction_drag = round(execution_friction_drag, 2)

        # Conservation of Trade Attribution PnL Assertion (INV-39 / AT-171)
        expected_total = strategy_selection_pnl + macro_timing_pnl + sector_rotation_pnl + risk_budget_overlay_pnl - execution_friction_drag
        attribution_residual = round(total_gross_pnl - expected_total, 6)

        return PerformanceAttributionRecord(
            timestamp=timestamp,
            total_portfolio_pnl=round(total_gross_pnl, 2),
            strategy_selection_pnl=round(strategy_selection_pnl, 2),
            macro_timing_pnl=round(macro_timing_pnl, 2),
            sector_rotation_pnl=round(sector_rotation_pnl, 2),
            risk_budget_overlay_pnl=round(risk_budget_overlay_pnl, 2),
            execution_friction_drag=execution_friction_drag,
            attribution_residual=attribution_residual,
        )
