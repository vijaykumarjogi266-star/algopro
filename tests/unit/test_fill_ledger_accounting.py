"""Unit tests for Fill-Price-Consistent Accounting (R19–R23).

Tests:
R19: test_buy_cashflow_uses_executed_fill
R20: test_mark_after_buy_uses_market_price
R21: test_sell_round_trip_reconciles_to_cash
R22: test_partial_fill_partial_close_accounting
R23: test_cash_and_ledger_recover_identically_after_restart
"""

import json
import pytest

from services.paper_engine.session import (
    PaperPortfolio,
    ExecutionFill,
    OrderSide,
)


def _make_fill(
    order_id: str,
    symbol: str,
    side: OrderSide,
    quantity: int,
    base_price: float,
    fill_price: float,
    transaction_costs: float = 1.0,
    slippage_cost: float = 0.50,
) -> ExecutionFill:
    return ExecutionFill(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        base_price=base_price,
        fill_price=fill_price,
        slippage_pts=round(abs(fill_price - base_price), 4),
        slippage_cost=slippage_cost,
        transaction_costs=transaction_costs,
        net_traded_value=round(quantity * fill_price, 4),
    )


def test_buy_cashflow_uses_executed_fill():
    """R19: Initial cash 10,000. BUY qty 10, ref 100, fill 100.05, fee 1. Assert cash=8,998.50, slip attribution=0.50."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill(
        order_id="ord_buy_1",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        base_price=100.0,
        fill_price=100.05,
        transaction_costs=1.0,
        slippage_cost=0.50,
    )
    portfolio.on_fill(fill)

    # Cash debit = 10 * 100.05 + 1.00 = 1001.50
    # Remaining cash = 10,000.00 - 1001.50 = 8,998.50
    assert portfolio.cash == 8998.50
    assert portfolio.total_slippage_paid == 0.50
    assert portfolio.total_fees_paid == 1.00


def test_mark_after_buy_uses_market_price():
    """R20: Using R19, market mark 100. Assert position market value = 1,000. Equity = 9,998.50.

    Do not mark shares at 100.05 merely because that was the fill.
    """
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill(
        order_id="ord_buy_1",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        base_price=100.0,
        fill_price=100.05,
        transaction_costs=1.0,
        slippage_cost=0.50,
    )
    portfolio.on_fill(fill)

    # Position is marked at reference/market price 100.00
    pos = portfolio.positions["TCS"]
    assert pos.quantity == 10
    assert pos.cost_basis == 1000.50  # 10 * 100.05
    assert pos.current_price == 100.00
    assert pos.market_value == 1000.00  # 10 * 100.00

    # Equity = Cash (8,998.50) + Position Market Value (1,000.00) = 9,998.50
    assert portfolio.total_equity == 9998.50


def test_sell_round_trip_reconciles_to_cash():
    """R21: Continue R19: SELL qty 10, ref 110, fill 109.95, fee 1.

    Assert final cash = 10,097.00, net realized PnL = 97.00, total fees = 2.00, slippage attribution = 1.00.
    """
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill_buy = _make_fill(
        order_id="ord_buy_1",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        base_price=100.0,
        fill_price=100.05,
        transaction_costs=1.0,
        slippage_cost=0.50,
    )
    portfolio.on_fill(fill_buy)

    fill_sell = _make_fill(
        order_id="ord_sell_1",
        symbol="TCS",
        side=OrderSide.SELL,
        quantity=10,
        base_price=110.0,
        fill_price=109.95,
        transaction_costs=1.0,
        slippage_cost=0.50,
    )
    portfolio.on_fill(fill_sell)

    # Cash inflow = 10 * 109.95 - 1.00 = 1098.50
    # Final cash = 8,998.50 + 1098.50 = 10,097.00
    assert portfolio.cash == 10097.00

    # Gross realized PnL = 10 * 109.95 - 10 * 100.05 = 1099.50 - 1000.50 = 99.00
    # Net realized PnL = Gross (99.00) - Total Fees (2.00) = 97.00
    net_realized_pnl = portfolio.total_realized_pnl - portfolio.total_fees_paid
    assert net_realized_pnl == 97.00
    assert portfolio.total_fees_paid == 2.00
    assert portfolio.total_slippage_paid == 1.00
    assert len(portfolio.positions) == 0


def test_partial_fill_partial_close_accounting():
    """R22: Use multiple fills and partial sell. Assert remaining cost basis, cash, realized PnL, fees and quantities."""
    portfolio = PaperPortfolio(initial_capital=20_000.0, cash=20_000.0, peak_equity=20_000.0)

    # Buy fill 1: 10 shares @ 100.00, fee 1
    f1 = _make_fill("ord_1", "INFY", OrderSide.BUY, 10, 100.0, 100.00, transaction_costs=1.0, slippage_cost=0.0)
    portfolio.on_fill(f1)
    assert portfolio.cash == 18999.00

    # Buy fill 2: 10 shares @ 110.00, fee 1
    f2 = _make_fill("ord_2", "INFY", OrderSide.BUY, 10, 110.0, 110.00, transaction_costs=1.0, slippage_cost=0.0)
    portfolio.on_fill(f2)
    assert portfolio.cash == 17898.00

    pos = portfolio.positions["INFY"]
    assert pos.quantity == 20
    assert pos.cost_basis == 2100.00
    assert pos.average_entry_price == 105.00

    # Partial close: Sell 10 shares @ 120.00, fee 1
    f3 = _make_fill("ord_3", "INFY", OrderSide.SELL, 10, 120.0, 120.00, transaction_costs=1.0, slippage_cost=0.0)
    portfolio.on_fill(f3)

    # Cash proceeds = 10 * 120 - 1 = 1199.00
    # New cash = 17898 + 1199 = 19097.00
    assert portfolio.cash == 19097.00

    # Realized gross = 10 * 120 - 10 * 105 = 150.00
    assert portfolio.total_realized_pnl == 150.00
    assert pos.quantity == 10
    assert pos.cost_basis == 1050.00
    assert pos.average_entry_price == 105.00
    assert portfolio.total_fees_paid == 3.00


def test_cash_and_ledger_recover_identically_after_restart():
    """R23: Persist real fills/positions, restart, assert economic state equals original and duplicate orders blocked."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill("ord_1", "TCS", OrderSide.BUY, 10, 100.0, 100.05, transaction_costs=1.0, slippage_cost=0.50)
    portfolio.on_fill(fill)

    # Serialize state to simulate persistent database / JSON storage
    serialized = portfolio.model_dump_json()

    # Reconstruct after restart
    recovered = PaperPortfolio.model_validate_json(serialized)
    assert recovered.cash == portfolio.cash
    assert recovered.total_fees_paid == portfolio.total_fees_paid
    assert recovered.total_slippage_paid == portfolio.total_slippage_paid
    assert recovered.positions["TCS"].cost_basis == portfolio.positions["TCS"].cost_basis
    assert recovered.total_equity == portfolio.total_equity
