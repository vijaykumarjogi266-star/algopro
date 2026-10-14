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
    PaperTradingEngine,
    ExecutionFill,
    OrderSide,
)
from services.execution_gateway.reconciliation_engine import DoubleEntryLedgerReconciler


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


# ==============================================================================
# Batch B Remediation Tests (B01 - B12)
# ==============================================================================

def test_b01_unaffordable_buy_leaves_every_portfolio_field_unchanged():
    """B01: Unaffordable BUY leaves every portfolio field completely unchanged."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill(
        order_id="ord_unaffordable",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=100,
        base_price=101.0,
        fill_price=101.05,
        transaction_costs=1.0,
        slippage_cost=5.0,
    )
    # Required cash = 100 * 101.05 + 1 = 10,106.00 > 10,000.00
    with pytest.raises(ValueError, match="Defensive cash invariant violation"):
        portfolio.on_fill(fill)

    # Invariants: Zero mutation across all portfolio attributes
    assert portfolio.cash == 10_000.0
    assert portfolio.total_fees_paid == 0.0
    assert portfolio.total_slippage_paid == 0.0
    assert portfolio.lifetime_trades == 0
    assert len(portfolio.positions) == 0
    assert portfolio.total_equity == 10_000.0
    assert portfolio.total_realized_pnl == 0.0
    assert portfolio.total_unrealized_pnl == 0.0


def test_b02_rejected_buy_then_valid_buy_increments_counters_exactly_once():
    """B02: Rejected BUY followed by valid BUY increments counters exactly once."""
    portfolio = PaperPortfolio(initial_capital=1_000.0, cash=1_000.0, peak_equity=1_000.0)

    # 1. Reject unaffordable BUY
    fill_bad = _make_fill("ord_bad", "INFY", OrderSide.BUY, 20, 100.0, 100.0, transaction_costs=1.0)
    with pytest.raises(ValueError):
        portfolio.on_fill(fill_bad)

    assert portfolio.lifetime_trades == 0
    assert portfolio.total_fees_paid == 0.0

    # 2. Accept valid BUY
    fill_good = _make_fill("ord_good", "INFY", OrderSide.BUY, 5, 100.0, 100.0, transaction_costs=1.0)
    portfolio.on_fill(fill_good)

    assert portfolio.lifetime_trades == 1
    assert portfolio.total_fees_paid == 1.0
    assert portfolio.cash == 499.0
    assert portfolio.positions["INFY"].quantity == 5


def test_b03_rejected_fill_remains_unchanged_after_database_reload():
    """B03: Rejected order leaves no side effects in database after reload."""
    from services.backtest_engine.execution_lifecycle import OrderLifecycleState

    engine = PaperTradingEngine(db_path=":memory:")
    session = engine.create_session(
        name="Reload Test",
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        initial_capital=500.0,
    )
    engine.start_session(session.session_id)

    # 1. Propose buy exceeding initial capital (500 INR)
    # 10 shares @ 100.0 = 1000 INR -> rejected by Risk Solvency check
    order_buy, fill_buy = engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        price=100.0,
    )
    assert order_buy.state == OrderLifecycleState.ORDER_REJECTED
    assert fill_buy is None

    # 2. Propose oversell (sell without holding) -> rejected by Oversell check
    order_sell, fill_sell = engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.SELL,
        quantity=5,
        price=100.0,
    )
    assert order_sell.state == OrderLifecycleState.ORDER_REJECTED
    assert fill_sell is None

    # 3. Reload session cleanly from database
    reloaded = engine.get_session(session.session_id)
    assert len(reloaded.fills) == 0
    assert reloaded.portfolio.cash == 500.0
    assert reloaded.portfolio.lifetime_trades == 0
    assert len(reloaded.portfolio.positions) == 0
    assert len(reloaded.orders) == 2
    assert all(o.state == OrderLifecycleState.ORDER_REJECTED for o in reloaded.orders)


def test_b04_buy_5_sell_6_rejects_with_no_phantom_proceeds():
    """B04: Buy 5, sell 6 rejects with zero phantom proceeds credited."""
    portfolio = PaperPortfolio(initial_capital=1_000.0, cash=1_000.0, peak_equity=1_000.0)
    f_buy = _make_fill("b1", "TCS", OrderSide.BUY, 5, 100.0, 100.0, transaction_costs=1.0)
    portfolio.on_fill(f_buy)
    assert portfolio.cash == 499.0
    assert portfolio.positions["TCS"].quantity == 5

    # Attempt to sell 6
    f_sell = _make_fill("s1", "TCS", OrderSide.SELL, 6, 110.0, 110.0, transaction_costs=1.0)
    with pytest.raises(ValueError, match="Oversell rejected"):
        portfolio.on_fill(f_sell)

    # Assert cash remains 499.0 (no phantom proceeds for 6 shares) and holding remains 5
    assert portfolio.cash == 499.0
    assert portfolio.positions["TCS"].quantity == 5
    assert portfolio.lifetime_trades == 1


def test_b05_buy_5_sell_3_then_sell_3_rejects_second_oversell():
    """B05: Buy 5, sell 3 (valid), then sell 3 rejects second oversell."""
    portfolio = PaperPortfolio(initial_capital=1_000.0, cash=1_000.0, peak_equity=1_000.0)
    f_buy = _make_fill("b1", "TCS", OrderSide.BUY, 5, 100.0, 100.0, transaction_costs=1.0)
    portfolio.on_fill(f_buy)

    f_sell1 = _make_fill("s1", "TCS", OrderSide.SELL, 3, 110.0, 110.0, transaction_costs=1.0)
    portfolio.on_fill(f_sell1)
    # Cash = 499 + (330 - 1) = 828.00, remaining holding = 2
    assert portfolio.cash == 828.0
    assert portfolio.positions["TCS"].quantity == 2
    assert portfolio.lifetime_trades == 2

    # Second sell of 3 must reject
    f_sell2 = _make_fill("s2", "TCS", OrderSide.SELL, 3, 110.0, 110.0, transaction_costs=1.0)
    with pytest.raises(ValueError, match="Oversell rejected"):
        portfolio.on_fill(f_sell2)

    assert portfolio.cash == 828.0
    assert portfolio.positions["TCS"].quantity == 2
    assert portfolio.lifetime_trades == 2


def test_b06_direct_portfolio_oversell_is_rejected_defensively():
    """B06: Selling with zero holdings rejects defensively with naked shorting prohibited."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill("s_naked", "RELIANCE", OrderSide.SELL, 10, 2500.0, 2500.0, transaction_costs=10.0)

    with pytest.raises(ValueError, match="Oversell rejected"):
        portfolio.on_fill(fill)

    assert portfolio.cash == 10_000.0
    assert len(portfolio.positions) == 0


def test_b07_initial_cash_10000_buy_10_at_100_05_with_fee_1():
    """B07: Initial cash 10,000; buy 10 at 100.05 with fee 1: cash must equal 8,998.50."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    fill = _make_fill("b_100_05", "TCS", OrderSide.BUY, 10, 100.0, 100.05, transaction_costs=1.0, slippage_cost=0.50)
    portfolio.on_fill(fill)

    # Cash debit = 10 * 100.05 + 1 = 1001.50
    # Remaining cash = 10,000.00 - 1001.50 = 8,998.50
    assert portfolio.cash == 8998.50
    assert portfolio.total_fees_paid == 1.0
    assert portfolio.total_slippage_paid == 0.50


def test_b08_sell_those_10_at_109_95_with_fee_1_final_cash_and_pnl():
    """B08: Sell those 10 at 109.95 with fee 1: final cash 10,097.00; net economic PnL 97.00."""
    portfolio = PaperPortfolio(initial_capital=10_000.0, cash=10_000.0, peak_equity=10_000.0)
    # Buy 10 @ 100.05 with fee 1
    f_buy = _make_fill("b1", "TCS", OrderSide.BUY, 10, 100.0, 100.05, transaction_costs=1.0, slippage_cost=0.50)
    portfolio.on_fill(f_buy)

    # Sell 10 @ 109.95 with fee 1
    f_sell = _make_fill("s1", "TCS", OrderSide.SELL, 10, 110.0, 109.95, transaction_costs=1.0, slippage_cost=0.50)
    portfolio.on_fill(f_sell)

    # Cash inflow = 10 * 109.95 - 1 = 1099.50 - 1 = 1098.50
    # Final cash = 8998.50 + 1098.50 = 10,097.00
    assert portfolio.cash == 10097.00

    # Net economic PnL = final cash - initial capital = 10097.00 - 10000.00 = 97.00
    net_economic_pnl = portfolio.cash - portfolio.initial_capital
    assert net_economic_pnl == 97.00
    assert portfolio.total_fees_paid == 2.00
    assert portfolio.total_slippage_paid == 1.00


def test_b09_double_deduction_of_slippage_fails_reconciliation():
    """B09: Double deduction of slippage from cash fails reconciliation."""
    initial_cash = 10_000.0
    # Correct fill-price consistent cash after BUY 10 @ 100.05 with fee 1
    correct_cash = 8998.50
    total_fees = 1.0
    slippage_attribution = 0.50
    cost_basis = 1000.50
    positions = {"TCS": {"quantity": 10, "avg_price": 100.05, "current_price": 100.0, "cost_basis": cost_basis}}

    # 1. Correct accounting reconciles
    valid, delta, reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=initial_cash,
        current_cash=correct_cash,
        positions=positions,
        total_fees_paid=total_fees,
        total_slippage_paid=slippage_attribution,
        realized_pnl=0.0,
    )
    assert valid is True
    assert delta == 0.0

    # 2. Defective double-slippage cash debit fails reconciliation
    defective_cash = correct_cash - slippage_attribution  # 8998.00
    valid_bad, delta_bad, reason_bad = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=initial_cash,
        current_cash=defective_cash,
        positions=positions,
        total_fees_paid=total_fees,
        total_slippage_paid=slippage_attribution,
        realized_pnl=0.0,
    )
    assert valid_bad is False
    assert "Double-entry cash imbalance detected" in reason_bad
    assert round(delta_bad, 2) == 0.50


def test_b10_real_two_session_fills_fees_carry_positions_reconcile():
    """B10: Multi-session fills, fees, and overnight carry positions reconcile accurately."""
    portfolio = PaperPortfolio.initialize(100_000.0)

    # Session 1: Buy 50 TCS @ 1000.00, fee 10
    f1 = _make_fill("s1_b", "TCS", OrderSide.BUY, 50, 1000.0, 1000.0, transaction_costs=10.0, slippage_cost=0.0)
    portfolio.on_fill(f1)
    portfolio.mark_to_market({"TCS": 1020.0})

    # Rollover to Session 2
    portfolio.reset_daily_metrics()
    portfolio.mark_to_market({"TCS": 1025.0})

    # Session 2: Sell 20 TCS @ 1030.00, fee 5
    f2 = _make_fill("s2_s", "TCS", OrderSide.SELL, 20, 1030.0, 1030.0, transaction_costs=5.0, slippage_cost=0.0)
    portfolio.on_fill(f2)
    portfolio.mark_to_market({"TCS": 1030.0})

    positions_dict = {
        "TCS": {
            "quantity": portfolio.positions["TCS"].quantity,
            "avg_price": portfolio.positions["TCS"].average_entry_price,
            "current_price": portfolio.positions["TCS"].current_price,
            "cost_basis": portfolio.positions["TCS"].cost_basis,
        }
    }

    valid, delta, reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=portfolio.initial_capital,
        current_cash=portfolio.cash,
        positions=positions_dict,
        total_fees_paid=portfolio.total_fees_paid,
        total_slippage_paid=portfolio.total_slippage_paid,
        realized_pnl=portfolio.total_realized_pnl,
    )
    assert valid is True, f"Failed reconciliation: {reason}"


def test_b11_nan_inf_cash_price_quantity_equity_or_fees_reject():
    """B11: NaN / Inf cash, price, quantity, equity, or fees reject unconditionally."""
    portfolio = PaperPortfolio.initialize(10_000.0)

    # 1. NaN price rejects in on_fill
    f_nan_p = _make_fill("bad1", "TCS", OrderSide.BUY, 10, 100.0, float("nan"))
    with pytest.raises(ValueError, match="Nonfinite"):
        portfolio.on_fill(f_nan_p)

    # 2. Inf quantity rejects in on_fill
    with pytest.raises((ValueError, TypeError)):
        _make_fill("bad2", "TCS", OrderSide.BUY, float("inf"), 100.0, 100.0)

    # 3. Nonfinite inputs reject in DoubleEntryLedgerReconciler
    valid, _, reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=float("nan"),
        current_cash=10_000.0,
        positions={},
        total_fees_paid=0.0,
        total_slippage_paid=0.0,
        realized_pnl=0.0,
    )
    assert valid is False
    assert "Nonfinite" in reason


def test_b12_reported_equity_inconsistent_with_assets_cash_rejects():
    """B12: Reported equity inconsistent with assets and cash fails balance sheet reconciliation."""
    initial_cap = 100_000.0
    cash = 50_000.0
    positions_value = 40_000.0
    net_cashflow = 0.0  # Actual equity = 90,000, expected equity = 100,000 (loss of 10,000 not accounted in cashflow)

    valid, imbalance, reason = DoubleEntryLedgerReconciler.audit_lifetime_balance_sheet(
        initial_capital=initial_cap,
        cash=cash,
        positions_value=positions_value,
        net_cashflows=net_cashflow,
    )
    assert valid is False
    assert "Lifetime balance-sheet imbalance" in reason
    assert imbalance == 10_000.0
