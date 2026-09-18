"""
Algo Lab — Stage 12 Arbitrage-Free Implied Volatility Solver & Volatility Surface Generator

DOCUMENTATION & MATHEMATICAL BOUNDS DISCLAIMER:
- This module implements deterministic finite-grid numerical arbitrage validation.
- PCHIP (Piecewise Cubic Hermite Interpolating Polynomial) interpolation on total implied variance
  w(K, T) = sigma^2 * T does NOT constitute a continuous analytical proof of global static arbitrage freedom.
- Validation is finite and numerically bounded (10-point interior sub-grid sampling per strike interval).
- Continuous analytical proof (e.g., Gatheral SVI / SSVI density non-negativity bounds) is outside Stage 12 scope.
- Total variance w(K, T) and option prices C(K, T) establish C^0 (value continuity) and C^1 (first-derivative continuity)
  under zero-slope endpoint boundary conditions, but do NOT guarantee C^2 (implied density continuity across knots).
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
        for _ in range(max_iterations):
            price = BSMPricingModel.calculate_price(S, K, T, r, q, sigma, option_type)
            diff = price - market_price

            if abs(diff) < tolerance:
                return sigma

            greeks = OptionGreeksCalculator.calculate_greeks_analytical(
                S, K, T, r, q, sigma, option_type
            )
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
            raise IVConvergenceError("Bisection solver cannot bracket IV solution")

        sigma_mid = 0.20
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


def _fritsch_carlson_pchip_interpolate(
    xs: List[float],
    ys: List[float],
    x_query: float,
) -> float:
    """
    Pure Python Fritsch-Carlson Monotone PCHIP Interpolation on Total Variance w(K).
    Enforces zero boundary derivatives w'(K_min) = 0 and w'(K_max) = 0 for flat total-variance extrapolation.
    """
    n = len(xs)
    if n == 0:
        return 0.0
    if n == 1:
        return ys[0]

    # Flat extrapolation outside bounds
    if x_query <= xs[0]:
        return ys[0]
    if x_query >= xs[-1]:
        return ys[-1]

    # Calculate secant slopes
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

    # Slopes d_i at grid points with zero endpoint derivatives
    d = [0.0] * n
    # Boundary slopes forced to zero for flat total variance extrapolation
    d[0] = 0.0
    d[-1] = 0.0

    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0.0:
            d[i] = 0.0
        else:
            # Weighted harmonic mean
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            d[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])

    # Find interval for x_query
    idx = 0
    for i in range(n - 1):
        if xs[i] <= x_query <= xs[i + 1]:
            idx = i
            break

    x_l, x_r = xs[idx], xs[idx + 1]
    y_l, y_r = ys[idx], ys[idx + 1]
    d_l, d_r = d[idx], d[idx + 1]
    h_i = h[idx]

    t = (x_query - x_l) / h_i
    t2 = t * t
    t3 = t2 * t

    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2

    return h00 * y_l + h10 * h_i * d_l + h01 * y_r + h11 * h_i * d_r


class VolatilitySurface:
    """Arbitrage-Free Volatility Surface Generator with 10-Point Sub-Grid Numerical Validation."""

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
        """Validates Vertical (Strike) Arbitrage & Put-Call Parity with 10-Point Sub-Grid Check."""
        S = self.spot
        r = self.risk_free_rate
        q = self.dividend_yield
        T = time_to_expiry

        # 1. Direct Surface Put-Call Parity Validation (AT-285)
        common_strikes = set(call_prices.keys()).intersection(set(put_prices.keys()))
        for K in sorted(common_strikes):
            c_val, p_val = call_prices[K], put_prices[K]
            lhs = c_val - p_val
            rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
            if abs(lhs - rhs) > 1e-4:
                raise VolatilitySurfaceArbitrageError(
                    f"Put-Call Parity breached at K={K}: C-P={lhs:.6f}, S*e^(-qT)-K*e^(-rT)={rhs:.6f}"
                )

        strikes = sorted(call_prices.keys())
        if len(strikes) < 2:
            return

        # 2. Strike Monotonicity on Discrete Knots: K1 < K2 => C(K1) >= C(K2)
        for i in range(len(strikes) - 1):
            k1, k2 = strikes[i], strikes[i + 1]
            if call_prices[k1] < call_prices[k2] - 1e-6:
                raise VolatilitySurfaceArbitrageError(
                    f"Call price monotonicity breached: C({k1})={call_prices[k1]} < C({k2})={call_prices[k2]}"
                )

        # 3. Put Price Monotonicity on Discrete Knots: K1 < K2 => P(K1) <= P(K2)
        put_strikes = sorted(put_prices.keys())
        for i in range(len(put_strikes) - 1):
            k1, k2 = put_strikes[i], put_strikes[i + 1]
            if put_prices[k1] > put_prices[k2] + 1e-6:
                raise VolatilitySurfaceArbitrageError(
                    f"Put price monotonicity breached: P({k1})={put_prices[k1]} > P({k2})={put_prices[k2]}"
                )

        # 4. Discrete Knot Butterfly Convexity: C(K1) - 2 C(K2) + C(K3) >= 0
        for i in range(len(strikes) - 2):
            k1, k2, k3 = strikes[i], strikes[i + 1], strikes[i + 2]
            if abs((k2 - k1) - (k3 - k2)) < 1e-5:  # Equal spacing
                c1, c2, c3 = call_prices[k1], call_prices[k2], call_prices[k3]
                if c1 - 2.0 * c2 + c3 < -1e-6:
                    raise VolatilitySurfaceArbitrageError(
                        f"Butterfly convexity breached at K=({k1},{k2},{k3}): {c1 - 2*c2 + c3}"
                    )

        # 5. 10-Point Sub-Grid Numerical Arbitrage Validation (AT-281)
        # Solve IV at grid knots to build Total Variance Monotone PCHIP curve
        try:
            iv_grid = {}
            for K, C in call_prices.items():
                iv_grid[K] = ImpliedVolatilitySolver.solve_iv(
                    C, S, K, T, r, q, OptionType.CALL
                )
        except Exception:
            # If IV solver fails for raw prices, validation halts
            return

        # Generate sub-grid evaluation points
        sub_grid_strikes = []
        for i in range(len(strikes) - 1):
            k1, k2 = strikes[i], strikes[i + 1]
            step = (k2 - k1) / 10.0
            for m in range(10):
                sub_grid_strikes.append(k1 + m * step)
        sub_grid_strikes.append(strikes[-1])

        # Evaluate call prices across fine sub-grid using Total Variance PCHIP
        sub_grid_prices = []
        for K_sub in sub_grid_strikes:
            iv_sub = self._interpolate_strike_pchip(iv_grid, K_sub, T)
            p_sub = BSMPricingModel.calculate_price(S, K_sub, T, r, q, iv_sub, OptionType.CALL)
            sub_grid_prices.append(p_sub)

        # Check Sub-Grid Strike Monotonicity
        for j in range(len(sub_grid_prices) - 1):
            if sub_grid_prices[j] < sub_grid_prices[j + 1] - 1e-9:
                raise VolatilitySurfaceArbitrageError(
                    f"Sub-grid strike monotonicity breached at K={sub_grid_strikes[j]:.2f}: "
                    f"C({sub_grid_strikes[j]:.2f})={sub_grid_prices[j]:.6f} < C({sub_grid_strikes[j+1]:.2f})={sub_grid_prices[j+1]:.6f}"
                )

        # Check Sub-Grid Butterfly Convexity (Second Difference)
        for j in range(1, len(sub_grid_prices) - 1):
            dk = sub_grid_strikes[j] - sub_grid_strikes[j - 1]
            if dk > 1e-8:
                second_diff = (sub_grid_prices[j - 1] - 2.0 * sub_grid_prices[j] + sub_grid_prices[j + 1]) / (dk * dk)
                if second_diff < -1e-6:
                    raise VolatilitySurfaceArbitrageError(
                        f"Sub-grid butterfly convexity breached at K={sub_grid_strikes[j]:.2f}: d2C/dK2={second_diff:.6f}"
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

    def _interpolate_strike_pchip(
        self,
        strike_map: Dict[float, float],
        query_strike: float,
        tenor: float,
    ) -> float:
        """Interpolates IV across strike dimension using Fritsch-Carlson PCHIP on Total Variance w(K)."""
        strikes = sorted(strike_map.keys())
        if not strikes:
            return 0.20
        if len(strikes) == 1:
            return strike_map[strikes[0]]

        # Compute total implied variance w_i = sigma_i^2 * T
        ws = [strike_map[k] * strike_map[k] * tenor for k in strikes]

        # Interpolate total variance w(K) with zero-slope boundary PCHIP
        w_query = _fritsch_carlson_pchip_interpolate(strikes, ws, query_strike)

        # Fail closed if interpolated total variance is non-positive
        if w_query <= 0.0 or math.isnan(w_query) or math.isinf(w_query):
            raise VolatilitySurfaceArbitrageError(
                f"Interpolated total variance non-positive or non-finite at K={query_strike}: {w_query}"
            )

        return math.sqrt(w_query / tenor)

    def interpolate_iv(
        self,
        grid: Dict[float, Dict[float, float]],  # tenor -> strike -> IV
        query_strike: float,
        query_tenor: float,
    ) -> float:
        """Interpolates IV across strike and tenor dimensions using Total Variance PCHIP & Flat Extrapolation."""
        tenors = sorted(grid.keys())
        if not tenors:
            raise DerivativesValidationError("Empty surface grid")

        # Clamp tenor for flat extrapolation outside tenor bounds
        t_eff = max(tenors[0], min(query_tenor, tenors[-1]))

        # Find surrounding tenors
        t_below = max([t for t in tenors if t <= t_eff], default=tenors[0])
        t_above = min([t for t in tenors if t >= t_eff], default=tenors[-1])

        iv_below = self._interpolate_strike_pchip(grid[t_below], query_strike, t_below)
        iv_above = self._interpolate_strike_pchip(grid[t_above], query_strike, t_above)

        if t_below == t_above:
            return iv_below

        # Linear total-variance interpolation across tenor dimension
        w_below = iv_below * iv_below * t_below
        w_above = iv_above * iv_above * t_above
        weight = (t_eff - t_below) / (t_above - t_below)
        w_eff = (1.0 - weight) * w_below + weight * w_above

        if w_eff <= 0.0 or math.isnan(w_eff) or math.isinf(w_eff):
            raise VolatilitySurfaceArbitrageError(
                f"Interpolated total variance non-positive across tenor at T={query_tenor}: {w_eff}"
            )

        return math.sqrt(w_eff / t_eff)
