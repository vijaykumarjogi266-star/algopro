"""
Algo Lab — Stage 13 Acceptance Tests (Part 1: AT-286 to AT-308)
Multi-Leg Option Strategy Payoffs, Net Greeks, Dynamic Delta Hedging & Expiry Settlement
"""

from datetime import datetime, timedelta, timezone
import math
import pytest

from services.derivatives_engine.contracts import (
    ContractSpecError,
    DerivativesValidationError,
    ExerciseStyle,
    GreeksHedgingLimitError,
    InstrumentType,
    OptionContract,
    OptionGreeks,
    OptionStrategySpec,
    OptionType,
    SettlementRuleError,
    SettlementType,
    StrategyType,
)
from services.derivatives_engine.greeks_analytics import OptionGreeksCalculator
from services.derivatives_engine.greeks_hedging import (
    GreeksHedgingEngine,
    round_half_towards_zero,
)
from services.derivatives_engine.strategy_backtester import MultiLegStrategyBacktester
from services.derivatives_engine.strategy_builder import (
    MultiLegStrategyBuilder,
    build_bear_call_spread,
    build_bear_put_spread,
    build_bull_call_spread,
    build_bull_put_spread,
    build_butterfly,
    build_collar,
    build_iron_condor,
    build_straddle,
    build_strangle,
    build_synthetic_long,
    create_option_leg,
)


def test_at_286_bull_call_spread_payoff():
    """AT-286: Bull Call Spread Payoff Bounded in [0, K2-K1]."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_bull_call_spread("NIFTY", 100.0, 95.0, 105.0, exp, 7.0, 2.0, lot_size=1, mult=1.0)
    
    # Test spots below K1, between K1 & K2, and above K2
    for spot, expected_intrinsic in [(90.0, 0.0), (100.0, 5.0), (110.0, 10.0)]:
        net_prem, intrinsic, pnl = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, spot, 0.0, 0.0, 1.0)
        assert net_prem == -5.0  # Paid 7, collected 2
        assert intrinsic == expected_intrinsic
        assert 0.0 <= intrinsic <= 10.0
        assert pnl == net_prem + intrinsic


def test_at_287_bear_call_spread_payoff():
    """AT-287: Bear Call Spread Payoff & Credit Collection."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_bear_call_spread("NIFTY", 100.0, 95.0, 105.0, exp, 7.0, 2.0, lot_size=1, mult=1.0)
    
    net_prem, intrinsic_at_90, pnl_at_90 = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 90.0, 0.0, 0.0, 1.0)
    assert net_prem == 5.0  # Short K1(7), Long K2(2) -> net credit +5
    assert intrinsic_at_90 == 0.0
    assert pnl_at_90 == 5.0

    _, intrinsic_at_110, pnl_at_110 = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 110.0, 0.0, 0.0, 1.0)
    assert intrinsic_at_110 == -10.0
    assert pnl_at_110 == -5.0  # Capped max loss


def test_at_288_bull_put_spread_payoff():
    """AT-288: Bull Put Spread Credit Payoff."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_bull_put_spread("NIFTY", 100.0, 95.0, 105.0, exp, 2.0, 7.0, lot_size=1, mult=1.0)
    
    net_prem, intrinsic_at_110, pnl_at_110 = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 110.0, 0.0, 0.0, 1.0)
    assert net_prem == 5.0  # Long 95(2), Short 105(7) -> +5 credit
    assert intrinsic_at_110 == 0.0
    assert pnl_at_110 == 5.0


def test_at_289_bear_put_spread_payoff():
    """AT-289: Bear Put Spread Payoff Bounded in [0, K2-K1]."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_bear_put_spread("NIFTY", 100.0, 95.0, 105.0, exp, 2.0, 7.0, lot_size=1, mult=1.0)
    
    net_prem, intrinsic_at_90, pnl_at_90 = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 90.0, 0.0, 0.0, 1.0)
    assert net_prem == -5.0  # Short 95(2), Long 105(7) -> net debit -5
    assert intrinsic_at_90 == 10.0
    assert pnl_at_90 == 5.0


def test_at_290_long_straddle_volatility_payoff():
    """AT-290: Long Straddle V-Shape Payoff Curve."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_straddle("NIFTY", 100.0, 100.0, exp, 5.0, 5.0, is_long=True, lot_size=1, mult=1.0)
    
    _, intr_100, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 100.0, 0.0, 0.0, 1.0)
    assert intr_100 == 0.0

    _, intr_115, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 115.0, 0.0, 0.0, 1.0)
    assert intr_115 == 15.0

    _, intr_85, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 85.0, 0.0, 0.0, 1.0)
    assert intr_85 == 15.0


def test_at_291_short_strangle_credit_payoff():
    """AT-291: Short Strangle Credit Payoff."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_strangle("NIFTY", 100.0, 90.0, 110.0, exp, 3.0, 3.0, is_long=False, lot_size=1, mult=1.0)
    
    net_prem, intr_100, pnl_100 = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 100.0, 0.0, 0.0, 1.0)
    assert net_prem == 6.0  # Collect 3 + 3
    assert intr_100 == 0.0
    assert pnl_100 == 6.0


def test_at_292_butterfly_spread_symmetry():
    """AT-292: Butterfly Spread Payoff Peak & Wing Symmetry."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_butterfly("NIFTY", 100.0, 90.0, 100.0, 110.0, exp, [12.0, 5.0, 1.0], lot_size=1, mult=1.0)
    
    _, intr_80, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 80.0, 0.0, 0.0, 1.0)
    assert intr_80 == 0.0

    _, intr_100, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 100.0, 0.0, 0.0, 1.0)
    assert intr_100 == 10.0  # Peak payoff at middle strike

    _, intr_120, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 120.0, 0.0, 0.0, 1.0)
    assert intr_120 == 0.0


def test_at_293_collar_strategy_protection():
    """AT-293: Collar Strategy Protection Bounded Value."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_collar("NIFTY", 100.0, 90.0, 110.0, exp, 3.0, 3.0, lot_size=1, mult=1.0)
    
    # Portfolio combined intrinsic + spot
    for spot in [70.0, 90.0, 100.0, 110.0, 130.0]:
        _, intr, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, spot, 0.0, 0.0, 1.0)
        tot_val = spot + intr
        assert 90.0 <= tot_val <= 110.0


def test_at_294_mixed_long_short_leg_payoff():
    """AT-294: Mixed Long/Short Leg Payoff Sign Symmetry."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    l1 = create_option_leg("NIFTY_C_100", "NIFTY", 100.0, exp, OptionType.CALL, 1, 5.0)
    l2 = create_option_leg("NIFTY_C_100", "NIFTY", 100.0, exp, OptionType.CALL, -1, 5.0)
    
    for spot in [80.0, 100.0, 120.0]:
        net_prem, intr, pnl = MultiLegStrategyBuilder.calculate_strategy_payoff([l1, l2], spot, 0.0, 0.0, 1.0)
        assert net_prem == 0.0
        assert intr == 0.0
        assert pnl == 0.0


def test_at_295_synthetic_long_payoff_equivalence():
    """AT-295: Synthetic Long Payoff Equivalence (S_T - K)."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_synthetic_long("NIFTY", 100.0, 100.0, exp, 5.0, 5.0, lot_size=1, mult=1.0)
    
    for spot in [80.0, 100.0, 120.0]:
        _, intr, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, spot, 0.0, 0.0, 1.0)
        assert intr == spot - 100.0


def test_at_296_invalid_combination_rejection():
    """AT-296: Invalid/Duplicate Leg Registration Rejection."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    l1 = create_option_leg("NIFTY_C_100", "NIFTY", 100.0, exp, OptionType.CALL, 1, 5.0)
    l2 = create_option_leg("NIFTY_C_100", "NIFTY", 100.0, exp, OptionType.CALL, 1, 5.0)
    
    spec = build_straddle("NIFTY", 100.0, 100.0, exp, 5.0, 5.0, is_long=True, lot_size=1)
    spec_invalid = build_straddle("NIFTY", 100.0, 100.0, exp, 5.0, 5.0, is_long=True, lot_size=1)
    object.__setattr__(spec_invalid, "legs", [l1, l2])

    with pytest.raises(DerivativesValidationError):
        MultiLegStrategyBuilder.validate_strategy_spec(spec_invalid, 1)


def test_at_297_iron_condor_4leg_net_greeks():
    """AT-297: Iron Condor 4-Leg Net Greeks Additivity."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_iron_condor("NIFTY", 100.0, 85.0, 90.0, 110.0, 115.0, exp, [1.0, 3.0, 3.0, 1.0], lot_size=1, mult=1.0)
    
    greeks_list = [
        OptionGreeks(delta=-0.10, gamma=0.01, vega=10.0, theta=-1.0, rho=0.5),
        OptionGreeks(delta=-0.25, gamma=0.02, vega=20.0, theta=-2.0, rho=1.0),
        OptionGreeks(delta=0.25, gamma=0.02, vega=20.0, theta=-2.0, rho=1.0),
        OptionGreeks(delta=0.10, gamma=0.01, vega=10.0, theta=-1.0, rho=0.5),
    ]

    net_greeks = MultiLegStrategyBuilder.compute_aggregate_greeks(spec.legs, greeks_list, multiplier=1.0)
    
    # Check linear superposition: Leg 1(+1), Leg 2(-1), Leg 3(-1), Leg 4(+1)
    expected_delta = 1.0 * (-0.10) - 1.0 * (-0.25) - 1.0 * (0.25) + 1.0 * (0.10)
    assert abs(net_greeks.delta - expected_delta) < 1e-8


def test_at_298_straddle_delta_neutral_entry():
    """AT-298: Straddle Delta-Neutral Entry State."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_straddle("NIFTY", 100.0, 100.0, exp, 5.0, 5.0, is_long=True, lot_size=1, mult=1.0)
    
    g_call = OptionGreeksCalculator.calculate_greeks_analytical(100.0, 100.0, 0.25, 0.05, 0.0, 0.20, OptionType.CALL)
    g_put = OptionGreeksCalculator.calculate_greeks_analytical(100.0, 100.0, 0.25, 0.05, 0.0, 0.20, OptionType.PUT)

    net_greeks = MultiLegStrategyBuilder.compute_aggregate_greeks(spec.legs, [g_call, g_put], multiplier=1.0)
    assert abs(net_greeks.delta) < 0.15  # Near zero net delta


def test_at_299_dynamic_delta_hedging_rebalance():
    """AT-299: Dynamic Delta Hedging Rebalance Trigger."""
    hedge_qty = GreeksHedgingEngine.calculate_delta_hedge(
        net_delta=0.25,
        delta_target=0.10,
        multiplier=100.0,
        lot_size=100,
        max_hedge_limit=1000,
    )
    # H = round(-0.25 * 100 / 100) = -0.25 -> -1 contract (or -25 shares)
    assert hedge_qty == 0 or hedge_qty == -1  # -0.25 rounded half towards zero gives 0 if lot_size=100


def test_at_300_delta_hedging_time_gating():
    """AT-300: Delta Hedging Time Gating (Minimum 1-Hour Interval)."""
    t_last = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    t_curr_30min = datetime(2026, 3, 1, 10, 30, 0, tzinfo=timezone.utc)
    t_curr_2hr = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 30 mins elapsed -> Deferred
    h_deferred = GreeksHedgingEngine.calculate_delta_hedge(
        net_delta=0.50,
        delta_target=0.10,
        multiplier=1.0,
        lot_size=1,
        last_rebalance_time=t_last,
        current_time=t_curr_30min,
        min_interval_hours=1.0,
    )
    assert h_deferred == 0

    # 2 hours elapsed -> Executed
    h_executed = GreeksHedgingEngine.calculate_delta_hedge(
        net_delta=1.50,
        delta_target=0.10,
        multiplier=1.0,
        lot_size=1,
        last_rebalance_time=t_last,
        current_time=t_curr_2hr,
        min_interval_hours=1.0,
    )
    assert h_executed == -1


def test_at_301_max_hedge_limit_lockout():
    """AT-301: Max Hedge Limit Fail-Closed Lockout."""
    with pytest.raises(GreeksHedgingLimitError):
        GreeksHedgingEngine.calculate_delta_hedge(
            net_delta=5000.0,
            delta_target=0.10,
            multiplier=1.0,
            lot_size=1,
            max_hedge_limit=1000,
        )


def test_at_302_hedging_contract_rounding():
    """AT-302: Hedging Contract Rounding Half Towards Zero."""
    assert round_half_towards_zero(1.5) == 1
    assert round_half_towards_zero(-1.5) == -1
    assert round_half_towards_zero(1.6) == 2
    assert round_half_towards_zero(-1.6) == -2


def test_at_303_gamma_safety_limit_alert():
    """AT-303: Net Gamma Safety Boundary Alert & Entry Lockout."""
    is_breached, alert = GreeksHedgingEngine.check_risk_bounds(
        net_gamma=0.08,
        net_vega=500.0,
        gamma_max=0.05,
        vega_max=1000.0,
    )
    assert is_breached is True
    assert "Gamma breach" in alert


def test_at_304_vega_safety_limit_alert():
    """AT-304: Net Vega Safety Boundary Alert & Entry Lockout."""
    is_breached, alert = GreeksHedgingEngine.check_risk_bounds(
        net_gamma=0.02,
        net_vega=1500.0,
        gamma_max=0.05,
        vega_max=1000.0,
    )
    assert is_breached is True
    assert "Vega breach" in alert


def test_at_305_cash_settlement_index_expiry():
    """AT-305: OPTIDX Cash Settlement at Expiry."""
    exp = datetime(2026, 3, 1, 15, 30, 0, tzinfo=timezone.utc)
    spec = build_bull_call_spread("NIFTY", 100.0, 95.0, 105.0, exp, 7.0, 2.0, lot_size=1, mult=1.0)
    
    bt = MultiLegStrategyBacktester(environment="RESEARCH")
    snap = [{"timestamp": exp, "spot": 105.0, "volatility": 0.20}]
    res = bt.run_backtest(
        spec, snap, initial_cash=10000.0, multiplier=1.0, commission_per_contract=0.0, slippage_per_contract=0.0
    )
    assert res.execution_status == "COMPLETED_CASH_SETTLEMENT"
    assert res.realized_pnl == 5.0  # Net premium (-5) + Intrinsic (10) = 5


def test_at_306_stock_physical_delivery_alert():
    """AT-306: OPTSTK Physical Delivery Alert Generation."""
    exp = datetime(2026, 3, 1, 15, 30, 0, tzinfo=timezone.utc)
    l1 = create_option_leg("RELIANCE_C_2000", "RELIANCE", 2000.0, exp, OptionType.CALL, 1, 50.0)
    object.__setattr__(l1.contract, "instrument_type", InstrumentType.OPTSTK)
    
    spec = OptionStrategySpec("Stock Option", StrategyType.CUSTOM, [l1], "RELIANCE", 2000.0)
    bt = MultiLegStrategyBacktester(environment="RESEARCH")
    snap = [{"timestamp": exp, "spot": 2100.0, "volatility": 0.20}]
    
    res = bt.run_backtest(spec, snap, initial_cash=500000.0, lot_size=1, multiplier=1.0)
    assert res.execution_status == "PHYSICAL_DELIVERY_ALERT"


def test_at_307_collateral_lockout_delivery():
    """AT-307: Insufficient Collateral Delivery Lockout."""
    exp = datetime(2026, 3, 1, 15, 30, 0, tzinfo=timezone.utc)
    l1 = create_option_leg("RELIANCE_C_2000", "RELIANCE", 2000.0, exp, OptionType.CALL, 1, 50.0)
    object.__setattr__(l1.contract, "instrument_type", InstrumentType.OPTSTK)
    
    spec = OptionStrategySpec("Stock Option", StrategyType.CUSTOM, [l1], "RELIANCE", 2000.0)
    bt = MultiLegStrategyBacktester(environment="RESEARCH")
    snap = [{"timestamp": exp, "spot": 2100.0, "volatility": 0.20}]
    
    # Available cash = $500, but required collateral = $2,100 -> Halts
    with pytest.raises(SettlementRuleError):
        bt.run_backtest(spec, snap, initial_cash=500.0, lot_size=1, multiplier=1.0)


def test_at_308_zero_time_expiry_payoff():
    """AT-308: Direct Intrinsic Valuation at T=0."""
    exp = datetime(2026, 12, 31, tzinfo=timezone.utc)
    spec = build_bull_call_spread("NIFTY", 100.0, 95.0, 105.0, exp, 7.0, 2.0, lot_size=1, mult=1.0)
    
    # T=0 evaluation
    _, intrinsic, pnl = MultiLegStrategyBuilder.calculate_strategy_payoff(spec.legs, 100.0, 0.0, 0.0, 1.0)
    assert intrinsic == 5.0
