"""
Algo Lab — Stage 13 Dynamic Greeks-Based Hedging & Monitoring Engine
"""

import math
from datetime import datetime
from typing import Optional, Tuple

from services.derivatives_engine.contracts import (
    DerivativesValidationError,
    GreeksHedgingLimitError,
)


def round_half_towards_zero(val: float) -> int:
    """
    Rounds a float half-towards-zero to an integer:
    e.g. +1.5 -> +1, -1.5 -> -1, +1.6 -> +2, -1.6 -> -2.
    """
    if val >= 0:
        return math.ceil(val - 0.5)
    else:
        return math.floor(val + 0.5)


class GreeksHedgingEngine:
    """Engine for dynamic Delta hedging and portfolio Gamma/Vega safety monitoring."""

    @staticmethod
    def calculate_delta_hedge(
        net_delta: float,
        delta_target: float,
        multiplier: float = 1.0,
        lot_size: int = 1,
        max_hedge_limit: int = 1000,
        last_rebalance_time: Optional[datetime] = None,
        current_time: Optional[datetime] = None,
        min_interval_hours: float = 1.0,
    ) -> int:
        """
        Calculates required underlying/futures hedge contract quantity (INV-75).
        H = round(-net_delta * multiplier / lot_size), rounding half-towards-zero.
        Raises GreeksHedgingLimitError if |H| > max_hedge_limit.
        """
        for name, val in [("net_delta", net_delta), ("delta_target", delta_target)]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite value for '{name}': {val}")

        if abs(net_delta) <= delta_target:
            return 0

        # Time gating check (minimum interval)
        if last_rebalance_time is not None and current_time is not None:
            elapsed_seconds = (current_time - last_rebalance_time).total_seconds()
            if elapsed_seconds < min_interval_hours * 3600.0:
                # Defer hedge rebalance
                return 0

        raw_hedge = -net_delta * multiplier / float(lot_size)
        hedge_qty = round_half_towards_zero(raw_hedge)

        if abs(hedge_qty) > max_hedge_limit:
            raise GreeksHedgingLimitError(
                f"Required hedge quantity {hedge_qty} breaches maximum hedge limit {max_hedge_limit} (net_delta: {net_delta})"
            )

        return hedge_qty

    @staticmethod
    def check_risk_bounds(
        net_gamma: float,
        net_vega: float,
        gamma_max: float = 0.05,
        vega_max: float = 1000.0,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates portfolio Gamma and Vega safety boundaries (INV-91).
        Returns (is_breached, alert_message).
        """
        for name, val in [("net_gamma", net_gamma), ("net_vega", net_vega)]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite value for '{name}': {val}")

        alerts = []
        is_breached = False

        if net_gamma > gamma_max:
            is_breached = True
            alerts.append(f"Gamma breach: net_gamma {net_gamma:.6f} > gamma_max {gamma_max:.6f}")

        if abs(net_vega) > vega_max:
            is_breached = True
            alerts.append(f"Vega breach: |net_vega| {abs(net_vega):.2f} > vega_max {vega_max:.2f}")

        if is_breached:
            return True, "; ".join(alerts)

        return False, None


class WhalleyWilmottHedgingEngine:
    """
    Whalley-Wilmott (1997) Asymptotic Optimal Option Hedging Engine.
    
    Computes cost-optimal no-transaction hedging bandwidth around Black-Scholes Delta,
    balancing gamma risk variance against proportional transaction costs (STT, brokerage, slippage).
    
    Bandwidth H = ( (3/2) * exp(-r * dt) * c * S * Gamma^2 / gamma_risk )^(1/3)
    """

    @staticmethod
    def calculate_asymptotic_bandwidth(
        spot_price: float,
        net_gamma: float,
        cost_rate: float = 0.001,  # 10 bps statutory + exchange friction
        risk_aversion: float = 0.01,
        discount_factor: float = 1.0,
    ) -> float:
        """
        Calculates the half-width of the no-transaction zone around target Delta.
        """
        if spot_price <= 0.0 or cost_rate <= 0.0 or risk_aversion <= 0.0:
            return 0.0

        abs_gamma = abs(net_gamma)
        if abs_gamma < 1e-9:
            return 0.0

        # Whalley-Wilmott asymptotic formula
        numerator = 1.5 * discount_factor * cost_rate * spot_price * (abs_gamma ** 2)
        inner = numerator / risk_aversion
        return float(inner ** (1.0 / 3.0))

    @classmethod
    def calculate_optimal_hedge(
        cls,
        net_delta: float,
        target_delta: float,
        spot_price: float,
        net_gamma: float,
        cost_rate: float = 0.001,
        risk_aversion: float = 0.01,
        multiplier: float = 1.0,
        lot_size: int = 1,
        max_hedge_limit: int = 1000,
    ) -> Tuple[int, float, bool]:
        """
        Calculates optimal hedge contracts under Whalley-Wilmott bounds.
        Returns: (hedge_contracts, bandwidth, is_rebalanced).
        
        Only triggers rebalancing when |net_delta - target_delta| > bandwidth.
        Rebalances to the band edge rather than zero to minimize transaction fees.
        """
        bandwidth = cls.calculate_asymptotic_bandwidth(
            spot_price=spot_price,
            net_gamma=net_gamma,
            cost_rate=cost_rate,
            risk_aversion=risk_aversion,
        )

        delta_diff = net_delta - target_delta

        # Inside no-transaction zone -> Do not trade (save friction)
        if abs(delta_diff) <= bandwidth:
            return 0, bandwidth, False

        # Outside no-transaction zone -> Rebalance towards the band boundary
        if delta_diff > bandwidth:
            excess_delta = delta_diff - bandwidth
        else:
            excess_delta = delta_diff + bandwidth

        raw_hedge = -excess_delta * multiplier / float(lot_size)
        hedge_qty = round_half_towards_zero(raw_hedge)

        if abs(hedge_qty) > max_hedge_limit:
            raise GreeksHedgingLimitError(
                f"Whalley-Wilmott hedge {hedge_qty} exceeds safety limit {max_hedge_limit} (excess_delta: {excess_delta:.4f})"
            )

        return hedge_qty, bandwidth, True

