"""
Algo Lab — Stage 12 Derivatives Pricing Engine (BSM Analytical & CRR Binomial Tree)
"""

import math
from typing import Tuple
from services.derivatives_engine.contracts import (
    OptionType,
    ExerciseStyle,
    DerivativesValidationError,
    DerivativesPricingError,
    CRRConvergenceError,
)


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function N(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal probability density function N'(x)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class BSMPricingModel:
    """Black-Scholes-Merton (BSM) Analytical Pricing Engine for European Options."""

    @staticmethod
    def calculate_price(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float,
        volatility: float,
        option_type: OptionType,
    ) -> float:
        # 1. Non-finite input check
        for name, val in [
            ("spot", spot),
            ("strike", strike),
            ("time_to_expiry", time_to_expiry),
            ("risk_free_rate", risk_free_rate),
            ("dividend_yield", dividend_yield),
            ("volatility", volatility),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite input parameter '{name}': {val}")

        # 2. Domain checks
        if spot <= 0.0:
            raise DerivativesValidationError(f"Spot price must be > 0.0: {spot}")
        if strike <= 0.0:
            raise DerivativesValidationError(f"Strike price must be > 0.0: {strike}")
        if time_to_expiry < 0.0:
            raise DerivativesValidationError(f"Time to expiry cannot be negative: {time_to_expiry}")
        if volatility < 0.0:
            raise DerivativesValidationError(f"Volatility cannot be negative: {volatility}")
        if option_type not in (OptionType.CALL, OptionType.PUT):
            raise DerivativesValidationError(f"Invalid option_type for BSM: {option_type}")

        S, K, T = spot, strike, time_to_expiry
        r, q, sig = risk_free_rate, dividend_yield, volatility

        # 3. T = 0 Expiry Intrinsic Pricing Boundary
        if T == 0.0:
            if option_type == OptionType.CALL:
                return max(0.0, S - K)
            else:
                return max(0.0, K - S)

        # 4. Volatility = 0 Deterministic Terminal-Value Pricing Boundary
        if sig == 0.0:
            S_T = S * math.exp((r - q) * T)
            if option_type == OptionType.CALL:
                return math.exp(-r * T) * max(0.0, S_T - K)
            else:
                return math.exp(-r * T) * max(0.0, K - S_T)

        # 5. Small-Time Numerical Stability Protection
        T_eff = max(T, 1e-12)

        d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T_eff) / (sig * math.sqrt(T_eff))
        d2 = d1 - sig * math.sqrt(T_eff)

        if option_type == OptionType.CALL:
            price = S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)

        if math.isnan(price) or math.isinf(price):
            raise DerivativesPricingError(f"BSM price computed non-finite result: {price}")

        return price


class CRRPricingModel:
    """Cox-Ross-Rubinstein (CRR) Binomial Tree Pricing Engine for European & American Options."""

    @staticmethod
    def calculate_price(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float,
        volatility: float,
        option_type: OptionType,
        exercise_style: ExerciseStyle = ExerciseStyle.EUROPEAN,
        steps: int = 100,
    ) -> float:
        for name, val in [
            ("spot", spot),
            ("strike", strike),
            ("time_to_expiry", time_to_expiry),
            ("risk_free_rate", risk_free_rate),
            ("dividend_yield", dividend_yield),
            ("volatility", volatility),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite input parameter '{name}': {val}")

        if spot <= 0.0 or strike <= 0.0 or time_to_expiry < 0.0 or volatility < 0.0:
            raise DerivativesValidationError("Invalid numeric inputs for CRR pricing")

        if steps < 50 or steps > 1000:
            raise DerivativesValidationError(f"Tree steps N must be in [50, 1000]: {steps}")

        if time_to_expiry == 0.0:
            if option_type == OptionType.CALL:
                return max(0.0, spot - strike)
            else:
                return max(0.0, strike - spot)

        S, K, T = spot, strike, time_to_expiry
        r, q, sig = risk_free_rate, dividend_yield, volatility
        N = steps
        dt = T / N

        u = math.exp(sig * math.sqrt(dt))
        d = 1.0 / u
        exp_rq_dt = math.exp((r - q) * dt)
        p = (exp_rq_dt - d) / (u - d)

        if p < 0.0 or p > 1.0 or math.isnan(p) or math.isinf(p):
            raise CRRConvergenceError(f"Invalid risk-neutral probability in CRR tree: p = {p}")

        df = math.exp(-r * dt)

        # Terminal payoffs
        values = [0.0] * (N + 1)
        for j in range(N + 1):
            S_node = S * (u ** j) * (d ** (N - j))
            if option_type == OptionType.CALL:
                values[j] = max(0.0, S_node - K)
            else:
                values[j] = max(0.0, K - S_node)

        # Backward induction
        for i in range(N - 1, -1, -1):
            for j in range(i + 1):
                v_cont = df * (p * values[j + 1] + (1.0 - p) * values[j])
                if exercise_style == ExerciseStyle.AMERICAN:
                    S_node = S * (u ** j) * (d ** (i - j))
                    if option_type == OptionType.CALL:
                        v_intr = max(0.0, S_node - K)
                    else:
                        v_intr = max(0.0, K - S_node)
                    values[j] = max(v_intr, v_cont)
                else:
                    values[j] = v_cont

        price = values[0]
        if math.isnan(price) or math.isinf(price):
            raise DerivativesPricingError(f"CRR computed non-finite price: {price}")

        return price
