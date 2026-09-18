"""
Algo Lab — Stage 12 Acceptance Tests (Part 1: AT-231 to AT-255)
"""

import math
import pytest
from datetime import datetime
from services.derivatives_engine import (
    OptionContract,
    OptionType,
    ExerciseStyle,
    BSMPricingModel,
    CRRPricingModel,
    OptionGreeksCalculator,
    ImpliedVolatilitySolver,
    VolatilitySurface,
    DerivativesValidationError,
    CRRConvergenceError,
    IVConvergenceError,
    VolatilitySurfaceArbitrageError,
)


def test_at_231_bsm_call_pricing_with_dividend_yield():
    """AT-231: BSM Call Pricing with Dividend Yield q."""
    price = BSMPricingModel.calculate_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
        option_type=OptionType.CALL,
    )
    assert abs(price - 9.826298) < 1e-4


def test_at_232_bsm_put_pricing_with_dividend_yield():
    """AT-232: BSM Put Pricing with Dividend Yield q."""
    price = BSMPricingModel.calculate_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
        option_type=OptionType.PUT,
    )
    assert abs(price - 5.944257) < 1e-4


def test_at_233_bsm_deterministic_sigma_0_terminal_pricing():
    """AT-233: BSM Deterministic sigma=0, T>0 Terminal Pricing."""
    c_price = BSMPricingModel.calculate_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.0,
        option_type=OptionType.CALL,
    )
    expected_c = math.exp(-0.05) * max(0.0, 100.0 * math.exp(0.04) - 100.0)
    assert abs(c_price - expected_c) < 1e-5
    assert abs(c_price - 3.882041) < 1e-4


def test_at_234_bsm_expiry_boundary_t0_intrinsic_pricing():
    """AT-234: BSM Expiry Boundary T=0 Intrinsic Pricing."""
    c_price = BSMPricingModel.calculate_price(
        spot=105.0,
        strike=100.0,
        time_to_expiry=0.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
        option_type=OptionType.CALL,
    )
    p_price = BSMPricingModel.calculate_price(
        spot=105.0,
        strike=100.0,
        time_to_expiry=0.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
        option_type=OptionType.PUT,
    )
    assert c_price == 5.0
    assert p_price == 0.0

    greeks = OptionGreeksCalculator.calculate_greeks_analytical(
        105.0, 100.0, 0.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert greeks.delta == 1.0
    assert greeks.gamma == 0.0


def test_at_235_bsm_small_time_stability_protection():
    """AT-235: BSM Small-Time T->0+ Stability Protection."""
    price = BSMPricingModel.calculate_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry=1e-15,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
        option_type=OptionType.CALL,
    )
    assert not math.isnan(price)
    assert not math.isinf(price)
    assert price >= 0.0


def test_at_236_bsm_negative_time_to_expiry_rejection():
    """AT-236: BSM Negative Time-To-Expiry Rejection."""
    with pytest.raises(DerivativesValidationError):
        BSMPricingModel.calculate_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=-0.5,
            risk_free_rate=0.05,
            dividend_yield=0.01,
            volatility=0.20,
            option_type=OptionType.CALL,
        )


def test_at_237_bsm_negative_volatility_rejection():
    """AT-237: BSM Negative Volatility Rejection."""
    with pytest.raises(DerivativesValidationError):
        BSMPricingModel.calculate_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry=1.0,
            risk_free_rate=0.05,
            dividend_yield=0.01,
            volatility=-0.20,
            option_type=OptionType.CALL,
        )


def test_at_238_crr_binomial_tree_european_call_convergence():
    """AT-238: CRR Binomial Tree European Call Convergence."""
    bsm_p = BSMPricingModel.calculate_price(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    crr_p = CRRPricingModel.calculate_price(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL, ExerciseStyle.EUROPEAN, steps=100
    )
    assert abs(crr_p - bsm_p) < 0.025


def test_at_239_crr_binomial_tree_european_put_convergence():
    """AT-239: CRR Binomial Tree European Put Convergence."""
    bsm_p = BSMPricingModel.calculate_price(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.PUT
    )
    crr_p = CRRPricingModel.calculate_price(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.PUT, ExerciseStyle.EUROPEAN, steps=100
    )
    assert abs(crr_p - bsm_p) < 0.025


def test_at_240_crr_american_put_early_exercise_premium():
    """AT-240: CRR American Put Early Exercise Premium."""
    eur_p = CRRPricingModel.calculate_price(
        100.0, 110.0, 1.0, 0.05, 0.01, 0.20, OptionType.PUT, ExerciseStyle.EUROPEAN, steps=100
    )
    amer_p = CRRPricingModel.calculate_price(
        100.0, 110.0, 1.0, 0.05, 0.01, 0.20, OptionType.PUT, ExerciseStyle.AMERICAN, steps=100
    )
    assert amer_p > eur_p


def test_at_241_crr_american_dividend_call_early_exercise():
    """AT-241: CRR American Dividend Call Early Exercise."""
    eur_c = CRRPricingModel.calculate_price(
        100.0, 90.0, 1.0, 0.05, 0.08, 0.20, OptionType.CALL, ExerciseStyle.EUROPEAN, steps=100
    )
    amer_c = CRRPricingModel.calculate_price(
        100.0, 90.0, 1.0, 0.05, 0.08, 0.20, OptionType.CALL, ExerciseStyle.AMERICAN, steps=100
    )
    assert amer_c > eur_c


def test_at_242_crr_invalid_risk_neutral_probability_rejection():
    """AT-242: CRR Invalid Risk-Neutral Probability Rejection."""
    with pytest.raises(CRRConvergenceError):
        # Extreme negative drift relative to volatility causing p < 0
        CRRPricingModel.calculate_price(
            100.0, 100.0, 1.0, -2.0, 0.0, 0.01, OptionType.CALL, steps=100
        )


def test_at_243_put_call_parity_conservation_check():
    """AT-243: Put-Call Parity Conservation Check."""
    S, K, T, r, q, sig = 100.0, 100.0, 1.0, 0.05, 0.01, 0.20
    c = BSMPricingModel.calculate_price(S, K, T, r, q, sig, OptionType.CALL)
    p = BSMPricingModel.calculate_price(S, K, T, r, q, sig, OptionType.PUT)
    rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert abs((c - p) - rhs) < 1e-6


def test_at_244_option_delta_analytical_vs_central_finite_diff():
    """AT-244: Option Delta Analytical vs Central Finite Diff."""
    g_analytical = OptionGreeksCalculator.calculate_greeks_analytical(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    g_fd = OptionGreeksCalculator.calculate_greeks_finite_difference(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert abs(g_analytical.delta - g_fd.delta) < 1e-4


def test_at_245_option_gamma_analytical_vs_central_finite_diff():
    """AT-245: Option Gamma Analytical vs Central Finite Diff."""
    g_analytical = OptionGreeksCalculator.calculate_greeks_analytical(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    g_fd = OptionGreeksCalculator.calculate_greeks_finite_difference(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert abs(g_analytical.gamma - g_fd.gamma) < 1e-4


def test_at_246_option_vega_analytical_vs_finite_difference():
    """AT-246: Option Vega Analytical vs Finite Difference."""
    g_analytical = OptionGreeksCalculator.calculate_greeks_analytical(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    g_fd = OptionGreeksCalculator.calculate_greeks_finite_difference(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert abs(g_analytical.vega - g_fd.vega) < 1e-4


def test_at_247_option_theta_daily_time_decay_precision():
    """AT-247: Option Theta Daily Time Decay Precision."""
    g_analytical = OptionGreeksCalculator.calculate_greeks_analytical(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    g_fd = OptionGreeksCalculator.calculate_greeks_finite_difference(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert abs(g_analytical.theta - g_fd.theta) < 1e-4


def test_at_248_option_rho_interest_rate_sensitivity_accuracy():
    """AT-248: Option Rho Interest Rate Sensitivity Accuracy."""
    g_analytical = OptionGreeksCalculator.calculate_greeks_analytical(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    g_fd = OptionGreeksCalculator.calculate_greeks_finite_difference(
        100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL
    )
    assert abs(g_analytical.rho - g_fd.rho) < 1e-4


def test_at_249_newton_raphson_iv_solver_convergence():
    """AT-249: Newton-Raphson IV Solver Convergence."""
    bsm_price = BSMPricingModel.calculate_price(100.0, 100.0, 1.0, 0.05, 0.01, 0.20, OptionType.CALL)
    solved_iv = ImpliedVolatilitySolver.solve_iv(
        market_price=bsm_price,
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        option_type=OptionType.CALL,
    )
    assert abs(solved_iv - 0.20000) < 1e-4


def test_at_250_newton_raphson_zero_vega_fallback_bisection():
    """AT-250: Newton-Raphson Zero-Vega Fallback Bisection."""
    solved_iv = ImpliedVolatilitySolver.solve_iv(
        market_price=0.0001,
        spot=100.0,
        strike=250.0,
        time_to_expiry=0.1,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        option_type=OptionType.CALL,
    )
    assert solved_iv > 0.0


def test_at_251_bisection_iv_solver_bracket_convergence():
    """AT-251: Bisection IV Solver Bracket Convergence."""
    high_vol_price = BSMPricingModel.calculate_price(100.0, 100.0, 1.0, 0.05, 0.01, 1.50, OptionType.CALL)
    solved_iv = ImpliedVolatilitySolver.solve_iv(
        market_price=high_vol_price,
        spot=100.0,
        strike=100.0,
        time_to_expiry=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        option_type=OptionType.CALL,
    )
    assert abs(solved_iv - 1.50) < 1e-4


def test_at_252_iv_solver_intrinsic_lower_bound_violation():
    """AT-252: IV Solver Intrinsic Lower-Bound Violation."""
    with pytest.raises(IVConvergenceError):
        ImpliedVolatilitySolver.solve_iv(
            market_price=2.0,
            spot=100.0,
            strike=90.0,
            time_to_expiry=1.0,
            risk_free_rate=0.05,
            dividend_yield=0.01,
            option_type=OptionType.CALL,
        )


def test_at_253_iv_solver_upper_bound_violation_rejection():
    """AT-253: IV Solver Upper-Bound Violation Rejection."""
    with pytest.raises(IVConvergenceError):
        ImpliedVolatilitySolver.solve_iv(
            market_price=110.0,
            spot=100.0,
            strike=100.0,
            time_to_expiry=1.0,
            risk_free_rate=0.05,
            dividend_yield=0.01,
            option_type=OptionType.CALL,
        )


def test_at_254_volatility_surface_call_strike_monotonicity():
    """AT-254: Volatility Surface Call Strike Monotonicity."""
    surf = VolatilitySurface(spot=100.0, risk_free_rate=0.05, dividend_yield=0.01)
    invalid_calls = {90.0: 10.0, 100.0: 12.0}
    with pytest.raises(VolatilitySurfaceArbitrageError):
        surf.validate_surface(invalid_calls, {}, time_to_expiry=1.0)


def test_at_255_volatility_surface_call_butterfly_convexity():
    """AT-255: Volatility Surface Call Butterfly Convexity."""
    surf = VolatilitySurface(spot=100.0, risk_free_rate=0.05, dividend_yield=0.01)
    invalid_calls = {90.0: 15.0, 100.0: 10.0, 110.0: 4.0}
    with pytest.raises(VolatilitySurfaceArbitrageError):
        surf.validate_surface(invalid_calls, {}, time_to_expiry=1.0)
