"""
Algo Lab — Stage 13 Multi-Scenario Option Portfolio Stress Grid Engine
"""

import math
from typing import List, Optional

from services.derivatives_engine.contracts import (
    DerivativesValidationError,
    OptionStrategySpec,
    OptionType,
    StressGridReport,
)
from services.derivatives_engine.pricing_models import BSMPricingModel


class OptionPortfolioStressGridEngine:
    """Engine for generating 45-point multi-variable price/volatility stress matrices."""

    DEFAULT_SPOT_SHIFTS = [-0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20]
    DEFAULT_VOL_SHIFTS = [-0.50, -0.25, 0.0, 0.25, 0.50]

    @staticmethod
    def evaluate_stress_grid(
        spec: OptionStrategySpec,
        base_spot: float,
        base_vol: float,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
        time_to_expiry_years: float = 0.25,
        spot_shifts: Optional[List[float]] = None,
        vol_shifts: Optional[List[float]] = None,
        multiplier: float = 1.0,
    ) -> StressGridReport:
        """
        Evaluates 9x5=45 point stress grid across spot shifts [-20%, +20%] and vol shifts [-50%, +50%] (INV-80).
        Reports minimum portfolio PnL shift as max stress loss.
        """
        if spot_shifts is None:
            spot_shifts = OptionPortfolioStressGridEngine.DEFAULT_SPOT_SHIFTS
        if vol_shifts is None:
            vol_shifts = OptionPortfolioStressGridEngine.DEFAULT_VOL_SHIFTS

        # Input sanitization for non-finite parameters (INV-83)
        for name, val in [
            ("base_spot", base_spot),
            ("base_vol", base_vol),
            ("risk_free_rate", risk_free_rate),
            ("dividend_yield", dividend_yield),
            ("time_to_expiry_years", time_to_expiry_years),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite value for '{name}': {val}")

        for shift in spot_shifts + vol_shifts:
            if math.isnan(shift) or math.isinf(shift):
                raise DerivativesValidationError(f"Non-finite value in stress shifts: {shift}")

        if base_spot <= 0.0 or base_vol < 0.0 or time_to_expiry_years < 0.0:
            raise DerivativesValidationError("Invalid base parameters for stress grid evaluation")

        # Initial baseline portfolio value
        base_value = OptionPortfolioStressGridEngine._price_strategy_at(
            spec, base_spot, base_vol, risk_free_rate, dividend_yield, time_to_expiry_years, multiplier
        )

        grid_pnls: List[List[float]] = []
        min_pnl = float("inf")

        for s_shift in spot_shifts:
            row_pnls: List[float] = []
            s_prime = base_spot * (1.0 + s_shift)
            if s_prime <= 0.0:
                s_prime = 0.01  # Floor near zero

            for v_shift in vol_shifts:
                v_prime = max(0.0001, base_vol * (1.0 + v_shift))
                cell_value = OptionPortfolioStressGridEngine._price_strategy_at(
                    spec, s_prime, v_prime, risk_free_rate, dividend_yield, time_to_expiry_years, multiplier
                )
                pnl_shift = cell_value - base_value
                row_pnls.append(pnl_shift)
                if pnl_shift < min_pnl:
                    min_pnl = pnl_shift

            grid_pnls.append(row_pnls)

        return StressGridReport(
            strategy_name=spec.name,
            spot_shifts=spot_shifts,
            vol_shifts=vol_shifts,
            grid_pnls=grid_pnls,
            max_stress_loss=min_pnl if min_pnl != float("inf") else 0.0,
        )

    @staticmethod
    def _price_strategy_at(
        spec: OptionStrategySpec,
        spot: float,
        volatility: float,
        risk_free_rate: float,
        dividend_yield: float,
        time_to_expiry: float,
        multiplier: float,
    ) -> float:
        total_value = 0.0
        for leg in spec.legs:
            c = leg.contract
            qty = float(leg.quantity)
            if time_to_expiry == 0.0:
                if c.option_type == OptionType.CALL:
                    px = max(0.0, spot - c.strike_price)
                elif c.option_type == OptionType.PUT:
                    px = max(0.0, c.strike_price - spot)
                else:
                    px = 0.0
            else:
                px = BSMPricingModel.calculate_price(
                    spot=spot,
                    strike=c.strike_price,
                    time_to_expiry=time_to_expiry,
                    risk_free_rate=risk_free_rate,
                    dividend_yield=dividend_yield,
                    volatility=volatility,
                    option_type=c.option_type,
                )
            total_value += qty * px * multiplier
        return total_value
