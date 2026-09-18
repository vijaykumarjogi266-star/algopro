"""
Algo Lab — Stage 12 Arbitrage-Free Implied Volatility Solver & Volatility Surface Generator
"""

import math
from typing import Dict, List, Tuple, Optional
from services.derivatives_engine.contracts import (
    OptionType,
    DerivativesValidationError,
    IVConvergenceError,
    VolatilitySurfaceArbitrageError,
    StaleSnapshotError,
)
from services.derivatives_engine.pricing_models import BSMPricingModel
from services.derivatives_engine.greeks_analytics import OptionGreeksCalculator


class ImpliedVolatilitySolver:
    """Newton-Raphson Implied Volatility Solver with Bisection Fallback."""

    @staticmethod
    def solve_iv(
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float,
        option_type: OptionType,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> float:
        for name, val in [
            ("market_price", market_price),
            ("spot", spot),
            ("strike", strike),
            ("time_to_expiry", time_to_expiry),
            ("risk_free_rate", risk_free_rate),
            ("dividend_yield", dividend_yield),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite input parameter '{name}': {val}")

        if spot <= 0.0 or strike <= 0.0 or time_to_expiry <= 0.0:
            raise DerivativesValidationError("Invalid numeric bounds for IV calculation")

        S, K, T = spot, strike, time_to_expiry
        r, q = risk_free_rate, dividend_yield

        # Intrinsic Bounds Check
        discount_S = S * math.exp(-q * T)
        discount_K = K * math.exp(-r * T)

        if option_type == OptionType.CALL:
            lower_bound = max(0.0, discount_S - discount_K)
            upper_bound = discount_S
        else:
            lower_bound = max(0.0, discount_K - discount_S)
            upper_bound = discount_K

        if market_price < lower_bound - tolerance:
            raise IVConvergenceError(
                f"Market price {market_price} violates intrinsic lower bound {lower_bound}"
            )
        if market_price > upper_bound + tolerance:
            raise IVConvergenceError(
                f"Market price {market_price} violates theoretical upper bound {upper_bound}"
            )

        # 1. Newton-Raphson Iteration
        sigma = 0.20  # Initial guess
        nr_converged = False

        for _ in range(max_iterations):
            price = BSMPricingModel.calculate_price(S, K, T, r, q, sigma, option_type)
            diff = price - market_price

            if abs(diff) < tolerance:
                return sigma

            greeks = OptionGreeksCalculator.calculate_greeks_analytical(
                S, K, T, r, q, sigma, option_type
            )
            # vega per 1.0 change in vol = vega_reported / 0.01
            vega_raw = greeks.vega / 0.01

            if vega_raw < 1e-12 or math.isnan(vega_raw):
                break  # Fallback to Bisection

            step = diff / vega_raw
            sigma -= step

            if sigma <= 0.0 or math.isnan(sigma) or math.isinf(sigma):
                break  # Fallback to Bisection

        # 2. Bisection Fallback
        sigma_min = 0.001
        sigma_max = 5.0

        p_min = BSMPricingModel.calculate_price(S, K, T, r, q, sigma_min, option_type)
        p_max = BSMPricingModel.calculate_price(S, K, T, r, q, sigma_max, option_type)

        if (p_min - market_price) * (p_max - market_price) > 0.0:
            # If bounds do not bracket the solution within [0.001, 5.0]
            raise IVConvergenceError("Bisection solver cannot bracket IV solution")

        for _ in range(max_iterations):
            sigma_mid = 0.5 * (sigma_min + sigma_max)
            p_mid = BSMPricingModel.calculate_price(S, K, T, r, q, sigma_mid, option_type)
            diff = p_mid - market_price

            if abs(diff) < tolerance:
                return sigma_mid

            if (p_mid - market_price) * (p_min - market_price) > 0.0:
                sigma_min = sigma_mid
                p_min = p_mid
            else:
                sigma_max = sigma_mid
                p_max = p_mid

        if abs(BSMPricingModel.calculate_price(S, K, T, r, q, sigma_mid, option_type) - market_price) < 1e-4:
            return sigma_mid

        raise IVConvergenceError("Implied Volatility solver failed to converge within tolerance")


class VolatilitySurface:
    """Arbitrage-Free Volatility Surface Generator with Strike & Calendar Validation."""

    def __init__(self, spot: float, risk_free_rate: float, dividend_yield: float):
        self.spot = spot
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield

    def validate_surface(
        self,
        call_prices: Dict[float, float],
        put_prices: Dict[float, float],
        time_to_expiry: float,
    ) -> None:
        """Validates Vertical (Strike) Arbitrage Constraints."""
        S = self.spot
        r = self.risk_free_rate
        q = self.dividend_yield
        T = time_to_expiry

        strikes = sorted(call_prices.keys())
        if len(strikes) < 2:
            return

        # 1. Call Price Monotonicity: K1 < K2 => C(K1) >= C(K2)
        for i in range(len(strikes) - 1):
            k1, k2 = strikes[i], strikes[i + 1]
            if call_prices[k1] < call_prices[k2] - 1e-6:
                raise VolatilitySurfaceArbitrageError(
                    f"Call price monotonicity breached: C({k1})={call_prices[k1]} < C({k2})={call_prices[k2]}"
                )

        # 2. Put Price Monotonicity: K1 < K2 => P(K1) <= P(K2)
        put_strikes = sorted(put_prices.keys())
        for i in range(len(put_strikes) - 1):
            k1, k2 = put_strikes[i], put_strikes[i + 1]
            if put_prices[k1] > put_prices[k2] + 1e-6:
                raise VolatilitySurfaceArbitrageError(
                    f"Put price monotonicity breached: P({k1})={put_prices[k1]} > P({k2})={put_prices[k2]}"
                )

        # 3. Call Butterfly Convexity: C(K1) - 2 C(K2) + C(K3) >= 0
        for i in range(len(strikes) - 2):
            k1, k2, k3 = strikes[i], strikes[i + 1], strikes[i + 2]
            if abs((k2 - k1) - (k3 - k2)) < 1e-5:  # Equal spacing
                c1, c2, c3 = call_prices[k1], call_prices[k2], call_prices[k3]
                if c1 - 2.0 * c2 + c3 < -1e-6:
                    raise VolatilitySurfaceArbitrageError(
                        f"Butterfly convexity breached at K=({k1},{k2},{k3}): {c1 - 2*c2 + c3}"
                    )

        # 4. Put-Call Parity: C(K) - P(K) = S*e^(-qT) - K*e^(-rT)
        common_strikes = set(call_prices.keys()).intersection(set(put_prices.keys()))
        for K in common_strikes:
            c_val, p_val = call_prices[K], put_prices[K]
            lhs = c_val - p_val
            rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
            if abs(lhs - rhs) > 1e-4:
                raise VolatilitySurfaceArbitrageError(
                    f"Put-Call Parity violated at K={K}: C-P={lhs}, RHS={rhs}"
                )

    def validate_calendar_arbitrage(
        self,
        iv_by_tenor: Dict[float, Dict[float, float]],
    ) -> None:
        """Validates Calendar Total Variance Monotonicity: T1 < T2 => w(K, T1) <= w(K, T2)."""
        tenors = sorted(iv_by_tenor.keys())
        if len(tenors) < 2:
            return

        all_strikes = set()
        for t in tenors:
            all_strikes.update(iv_by_tenor[t].keys())

        for K in sorted(all_strikes):
            for i in range(len(tenors) - 1):
                t1, t2 = tenors[i], tenors[i + 1]
                if K in iv_by_tenor[t1] and K in iv_by_tenor[t2]:
                    sig1 = iv_by_tenor[t1][K]
                    sig2 = iv_by_tenor[t2][K]
                    w1 = sig1 * sig1 * t1
                    w2 = sig2 * sig2 * t2
                    if w1 > w2 + 1e-6:
                        raise VolatilitySurfaceArbitrageError(
                            f"Calendar total variance arbitrage at K={K}: w({t1})={w1} > w({t2})={w2}"
                        )

    def interpolate_iv(
        self,
        grid: Dict[float, Dict[float, float]],  # tenor -> strike -> IV
        query_strike: float,
        query_tenor: float,
    ) -> float:
        """Interpolates IV across strike and tenor dimensions with flat extrapolation."""
        tenors = sorted(grid.keys())
        if not tenors:
            raise DerivativesValidationError("Empty surface grid")

        # Clamp tenor (flat extrapolation)
        t_eff = max(tenors[0], min(query_tenor, tenors[-1]))

        # Find surrounding tenors
        t_below = max([t for t in tenors if t <= t_eff], default=tenors[0])
        t_above = min([t for t in tenors if t >= t_eff], default=tenors[-1])

        def interp_strike(strike_map: Dict[float, float], k: float) -> float:
            strikes = sorted(strike_map.keys())
            if not strikes:
                return 0.20
            k_eff = max(strikes[0], min(k, strikes[-1]))
            if len(strikes) == 1 or k_eff == strikes[0]:
                return strike_map[strikes[0]]
            if k_eff == strikes[-1]:
                return strike_map[strikes[-1]]

            for i in range(len(strikes) - 1):
                k1, k2 = strikes[i], strikes[i + 1]
                if k1 <= k_eff <= k2:
                    weight = (k_eff - k1) / (k2 - k1)
                    return (1.0 - weight) * strike_map[k1] + weight * strike_map[k2]
            return strike_map[strikes[0]]

        iv_below = interp_strike(grid[t_below], query_strike)
        iv_above = interp_strike(grid[t_above], query_strike)

        if t_below == t_above:
            return iv_below

        weight = (t_eff - t_below) / (t_above - t_below)
        return (1.0 - weight) * iv_below + weight * iv_above
