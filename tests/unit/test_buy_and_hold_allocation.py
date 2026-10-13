"""Unit tests for Buy and Hold Allocation and Risk Enforcement (R15–R18).

Tests:
R15: test_single_symbol_benchmark_allocation_is_explicit
R16: test_multisymbol_weights_conserve_cash
R17: test_executable_buy_and_hold_respects_risk_policy
R18: test_buy_and_hold_does_not_depend_on_sma_crossover
"""

from datetime import datetime, timezone
import pytest

from quant.strategies.buy_and_hold import BuyAndHold
from data.schemas.contracts import OHLCVBar
from quant.strategies.base import SignalType, StrategyDecision
from services.backtest_engine.trade_candidate import CandidateAction, TradeCandidate
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode


def test_single_symbol_benchmark_allocation_is_explicit():
    """R15: Single symbol benchmark allocation is explicit; invested amount and residual cash match documented allocation."""
    capital = 100_000.0
    price = 150.0
    # Explicit 60% allocation
    strategy = BuyAndHold(parameters={"allocation_pct": 0.60})
    weight = strategy.get_allocation_weight("RELIANCE")
    assert weight == 0.60

    allocated_capital = capital * weight
    assert allocated_capital == 60_000.0

    qty = int(allocated_capital / price)
    invested = qty * price
    residual_cash = capital - invested

    assert qty == 400
    assert invested == 60_000.0
    assert residual_cash == 40_000.0


def test_multisymbol_weights_conserve_cash():
    """R16: Multi-symbol weights conserve cash: weight sum <= 1.0, quantity rounding, no leverage, no overspending."""
    capital = 100_000.0
    symbols = ["TCS", "INFY", "RELIANCE"]
    weights = {"TCS": 0.40, "INFY": 0.35, "RELIANCE": 0.25}
    assert sum(weights.values()) <= 1.0

    strategy = BuyAndHold(parameters={"weights": weights, "universe": symbols})

    total_spent = 0.0
    prices = {"TCS": 3500.0, "INFY": 1800.0, "RELIANCE": 2900.0}

    for sym in symbols:
        w = strategy.get_allocation_weight(sym)
        assert w == weights[sym]
        allocated = capital * w
        qty = int(allocated / prices[sym])
        cost = qty * prices[sym]
        assert cost <= allocated
        total_spent += cost

    assert total_spent <= capital
    residual = capital - total_spent
    assert residual >= 0.0


def test_executable_buy_and_hold_respects_risk_policy():
    """R17: Hard risk constraints are preserved: prohibited concentration rejected or reduced, never bypassed."""
    capital = 100_000.0
    price = 100.0

    # Risk policy limits max capital per trade to 20%
    risk_limits = HardRiskLimits(max_capital_per_trade_pct=0.20)
    risk_engine = RiskEngine(limits=risk_limits)

    # Strategy attempts 100% allocation
    strategy_100 = BuyAndHold(parameters={"allocation_pct": 1.0})
    res_100 = strategy_100.execute_allocation_with_risk_policy(
        symbol="SBIN",
        price=price,
        portfolio_value=capital,
        risk_engine=risk_engine,
    )
    # Must be rejected because 100% > 20% limit
    assert res_100["approved"] is False
    assert res_100["rejection_code"] == RiskRejectionCode.EXCEEDS_MAX_CAPITAL

    # Strategy with compliant 15% allocation
    strategy_15 = BuyAndHold(parameters={"allocation_pct": 0.15})
    res_15 = strategy_15.execute_allocation_with_risk_policy(
        symbol="SBIN",
        price=price,
        portfolio_value=capital,
        risk_engine=risk_engine,
    )
    assert res_15["approved"] is True
    assert res_15["quantity"] == 150  # 15,000 / 100


def test_buy_and_hold_does_not_depend_on_sma_crossover():
    """R18: BuyAndHold enters on bar 0 independently of any SMA crossover fixture."""
    strategy = BuyAndHold(parameters={"allocation_pct": 1.0})
    ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)

    # Bar with no indicators or moving averages
    bar0 = OHLCVBar(
        symbol="TCS",
        exchange="NSE",
        timeframe="1d",
        market_timestamp=ts,
        timestamp=ts,
        open=100.0,
        high=105.0,
        low=98.0,
        close=102.0,
        volume=5000.0,
    )

    decision = strategy.evaluate(bar0, history=[])
    assert decision.signal == SignalType.BUY
    assert "bar 0" in decision.reason

    # Fresh strategy for on_bar lifecycle
    strat_bar = BuyAndHold(parameters={"allocation_pct": 1.0})
    candidate = strat_bar.on_bar(bar0, history=[], has_open_position=False)
    assert candidate is not None
    assert candidate.action == CandidateAction.ENTER_LONG
    assert candidate.symbol == "TCS"

    # Subsequent bar should be hold (no repeated entry)
    candidate_next = strat_bar.on_bar(bar0, history=[bar0], has_open_position=True)
    assert candidate_next is None
