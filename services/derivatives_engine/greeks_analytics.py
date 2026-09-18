"""
Algo Lab — Stage 12 Option Greeks Analytics Engine (Analytical & Finite-Difference)
"""

import math
from services.derivatives_engine.contracts import (
    OptionType,
    OptionGreeks,
    DerivativesValidationError,
)
from services.derivatives_engine.pricing_models import BSMPricingModel, norm_cdf, norm_pdf


class OptionGreeksCalculator:
    """Calculates First & Second-Order Option Greeks under ACT/365 conventions."""

    @staticmethod
    def calculate_greeks_analytical(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float,
        volatility: float,
        option_type: OptionType,
    ) -> OptionGreeks:
        for name, val in [
            ("spot", spot),
            ("strike", strike),
            ("time_to_expiry", time_to_expiry),
            ("risk_free_rate", risk_free_rate),
            ("dividend_yield", dividend_yield),
            ("volatility", volatility),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite parameter '{name}': {val}")

        if spot <= 0.0 or strike <= 0.0 or time_to_expiry < 0.0 or volatility < 0.0:
            raise DerivativesValidationError("Invalid numeric input for Greeks calculation")

        S, K, T = spot, strike, time_to_expiry
        r, q, sig = risk_free_rate, dividend_yield, volatility

        # Boundary Edge Cases
        if S == 0.0:
            return OptionGreeks(delta=0.0, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

        if T == 0.0:
            if option_type == OptionType.CALL:
                d_val = 1.0 if S > K else 0.0
            else:
                d_val = -1.0 if S < K else 0.0
            return OptionGreeks(delta=d_val, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

        if sig == 0.0:
            S_T = S * math.exp((r - q) * T)
            if option_type == OptionType.CALL:
                d_val = math.exp(-q * T) if S_T > K else 0.0
            else:
                d_val = -math.exp(-q * T) if S_T < K else 0.0
            return OptionGreeks(delta=d_val, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

        T_eff = max(T, 1e-12)
        d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T_eff) / (sig * math.sqrt(T_eff))
        d2 = d1 - sig * math.sqrt(T_eff)

        # 1. Delta
        if option_type == OptionType.CALL:
            delta = math.exp(-q * T) * norm_cdf(d1)
        else:
            delta = -math.exp(-q * T) * norm_cdf(-d1)

        # 2. Gamma
        gamma = (math.exp(-q * T) * norm_pdf(d1)) / (S * sig * math.sqrt(T_eff))

        # 3. Vega (per 1% change in vol)
        vega = S * math.exp(-q * T) * norm_pdf(d1) * math.sqrt(T_eff) * 0.01

        # 4. Theta (daily time decay, 1/365 year)
        term1 = -(S * math.exp(-q * T) * norm_pdf(d1) * sig) / (2.0 * math.sqrt(T_eff))
        if option_type == OptionType.CALL:
            term2 = q * S * math.exp(-q * T) * norm_cdf(d1)
            term3 = -r * K * math.exp(-r * T) * norm_cdf(d2)
            theta = (term1 + term2 + term3) / 365.0
        else:
            term2 = -q * S * math.exp(-q * T) * norm_cdf(-d1)
            term3 = r * K * math.exp(-r * T) * norm_cdf(-d2)
            theta = (term1 + term2 + term3) / 365.0

        # 5. Rho (per 1% change in rate)
        if option_type == OptionType.CALL:
            rho = K * T * math.exp(-r * T) * norm_cdf(d2) * 0.01
        else:
            rho = -K * T * math.exp(-r * T) * norm_cdf(-d2) * 0.01

        return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)

    @staticmethod
    def calculate_greeks_finite_difference(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float,
        volatility: float,
        option_type: OptionType,
        eps_spot: float = 0.001,
        eps_vol: float = 0.01,
        eps_rate: float = 0.01,
    ) -> OptionGreeks:
        S, K, T = spot, strike, time_to_expiry
        r, q, sig = risk_free_rate, dividend_yield, volatility

        if T <= 0.0 or S <= 0.0 or sig <= 0.0:
            return OptionGreeksCalculator.calculate_greeks_analytical(
                spot, strike, time_to_expiry, risk_free_rate, dividend_yield, volatility, option_type
            )

        # Price helper
        def p(s_val, t_val, r_val, sig_val):
            return BSMPricingModel.calculate_price(
                s_val, K, t_val, r_val, q, sig_val, option_type
            )

        p_base = p(S, T, r, sig)

        # Delta & Gamma via central bump dS = eps_spot * S
        dS = eps_spot * S
        p_up_S = p(S + dS, T, r, sig)
        p_dn_S = p(S - dS, T, r, sig)

        delta = (p_up_S - p_dn_S) / (2.0 * dS)
        gamma = (p_up_S - 2.0 * p_base + p_dn_S) / (dS * dS)

        # Vega via central bump dSig = eps_vol
        dSig = eps_vol
        p_up_sig = p(S, T, r, max(1e-6, sig + dSig))
        p_dn_sig = p(S, T, r, max(1e-6, sig - dSig))
        vega = (p_up_sig - p_dn_sig) / (2.0 * dSig) * eps_vol

        # Theta via daily bump dT = 1/365
        dt = 1.0 / 365.0
        p_prev_T = p(S, max(1e-12, T - dt), r, sig)
        theta = -(p_base - p_prev_T)

        # Rho via central bump dR = eps_rate
        dR = eps_rate
        p_up_r = p(S, T, r + dR, sig)
        p_dn_r = p(S, T, r - dR, sig)
        rho = (p_up_r - p_dn_r) / (2.0 * dR) * eps_rate

        return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
