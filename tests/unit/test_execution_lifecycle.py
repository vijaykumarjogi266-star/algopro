"""Unit tests for Execution Lifecycle & Deterministic Slippage (Stage 6)."""

import pytest

from services.backtest_engine.contracts import OrderSide, OrderType, SlippageModelConfig
from services.backtest_engine.cost_models import IndianCostCalculator, SlippageCalculator
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    ExecutionOrder,
    ExecutionFill,
    OrderLifecycleState,
)
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode


def test_complete_successful_order_lifecycle():
    """Verify full transition: PROPOSED -> EVALUATED -> ACCEPTED -> SUBMITTED -> FILLED."""
    manager = ExecutionLifecycleManager()

    # 1. Propose
    order = manager.propose_order(
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        price=3500.0,
        stop_loss=3400.0,
        target_price=3700.0,
    )
    assert order.state == OrderLifecycleState.ORDER_PROPOSED
    assert len(order.state_history) == 1

    # 2. Evaluate Risk (Approved)
    portfolio_value = 1_000_000.0
    evaluated = manager.evaluate_risk(order, current_portfolio_value=portfolio_value)
    assert evaluated.state == OrderLifecycleState.ORDER_ACCEPTED
    assert evaluated.rejection_code is None
    assert len(evaluated.state_history) == 3  # PROPOSED -> EVALUATED -> ACCEPTED

    # 3. Submit
    submitted = manager.submit_order(evaluated)
    assert submitted.state == OrderLifecycleState.ORDER_SUBMITTED

    # 4. Fill
    filled_order, fill = manager.fill_order(submitted, execution_price=3500.0)
    assert filled_order.state == OrderLifecycleState.ORDER_FILLED
    assert fill.quantity == 10
    # Buy order slippage: fill_price should be > base_price
    assert fill.fill_price > 3500.0
    assert fill.slippage_pts > 0
    assert fill.transaction_costs > 0
    assert fill.net_traded_value == round(10 * fill.fill_price, 4)


def test_risk_rejection_lifecycle():
    """Verify order rejection when risk limits are breached."""
    manager = ExecutionLifecycleManager()

    # Propose order exceeding max capital limit (10% of portfolio = 100,000 INR)
    # 500 * 3500 = 1,750,000 INR > 100,000 INR
    order = manager.propose_order(
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=500,
        price=3500.0,
        stop_loss=3400.0,
    )

    evaluated = manager.evaluate_risk(order, current_portfolio_value=1_000_000.0)
    assert evaluated.state == OrderLifecycleState.ORDER_REJECTED
    assert evaluated.rejection_code == RiskRejectionCode.EXCEEDS_MAX_CAPITAL.value
    assert "exceeds max trade limit" in evaluated.rejection_reason

    # Attempting to submit a rejected order must fail closed
    with pytest.raises(ValueError) as exc:
        manager.submit_order(evaluated)
    assert "Only ORDER_ACCEPTED orders can be submitted" in str(exc.value)


def test_missing_mandatory_stop_loss():
    """Orders with missing stop-loss must be rejected by Risk Engine."""
    manager = ExecutionLifecycleManager()

    order = manager.propose_order(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=10,
        price=1500.0,
        stop_loss=None,  # Missing mandatory stop loss
    )
    evaluated = manager.evaluate_risk(order, current_portfolio_value=1_000_000.0)
    assert evaluated.state == OrderLifecycleState.ORDER_REJECTED
    assert evaluated.rejection_code == RiskRejectionCode.MISSING_STOP_LOSS.value


def test_deterministic_slippage_and_cost_attribution():
    """Verify buy and sell slippage directions and cost calculations."""
    slip_calc = SlippageCalculator(
        SlippageModelConfig(fixed_tick_slippage_pts=0.05, variable_slippage_pct=0.001)
    )
    cost_calc = IndianCostCalculator()
    manager = ExecutionLifecycleManager(slippage_calculator=slip_calc, cost_calculator=cost_calc)

    # Buy order
    order_buy = manager.propose_order("SBIN", OrderSide.BUY, 50, 750.0, stop_loss=740.0)
    manager.evaluate_risk(order_buy, current_portfolio_value=1_000_000.0)
    manager.submit_order(order_buy)
    _, fill_buy = manager.fill_order(order_buy, execution_price=750.0)

    # Fixed tick (0.05) + pct (750 * 0.001 = 0.75) = 0.80 pts
    assert fill_buy.slippage_pts == pytest.approx(0.80, abs=1e-3)
    assert fill_buy.fill_price == pytest.approx(750.80, abs=1e-3)

    # Sell order
    order_sell = manager.propose_order("SBIN", OrderSide.SELL, 50, 750.0, stop_loss=760.0)
    manager.evaluate_risk(order_sell, current_portfolio_value=1_000_000.0)
    manager.submit_order(order_sell)
    _, fill_sell = manager.fill_order(order_sell, execution_price=750.0)

    assert fill_sell.fill_price == pytest.approx(750.0 - 0.80, abs=1e-3)


def test_cancellation_and_failure():
    """Verify order cancellation and failure transitions."""
    manager = ExecutionLifecycleManager()

    # Cancel proposed order
    order1 = manager.propose_order("WIPRO", OrderSide.BUY, 10, 450.0, stop_loss=440.0)
    cancelled = manager.cancel_order(order1, reason="Strategy condition timed out")
    assert cancelled.state == OrderLifecycleState.ORDER_CANCELLED

    # Cannot cancel filled order
    order2 = manager.propose_order("WIPRO", OrderSide.BUY, 10, 450.0, stop_loss=440.0)
    manager.evaluate_risk(order2, 1_000_000.0)
    manager.submit_order(order2)
    manager.fill_order(order2)
    with pytest.raises(ValueError):
        manager.cancel_order(order2)

    # Order failed transition
    order3 = manager.propose_order("WIPRO", OrderSide.BUY, 10, 450.0, stop_loss=440.0)
    failed = manager.fail_order(order3, reason="Exchange network timeout")
    assert failed.state == OrderLifecycleState.ORDER_FAILED
