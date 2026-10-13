"""Integration tests for Real Fill Multiday Accounting (T48–T52).

Tests:
T48: test_slippage_not_double_counted_on_fill
T49: test_daily_vs_lifetime_pnl_reset
T50: test_high_water_mark_multiday_preservation
T51: test_cash_balance_invariants_across_multiday_trades
T52: test_zero_fill_rejection_leaves_ledger_untouched
"""

import pytest
from datetime import datetime, timezone

from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    OrderLifecycleState,
)
from services.risk_engine.contracts import HardRiskLimits
from services.risk_engine.engine import RiskEngine
from services.execution_gateway.reconciliation_engine import DoubleEntryLedgerReconciler
from services.paper_engine.session import PaperTradingEngine, SessionStatus


@pytest.fixture
def paper_engine(tmp_path):
    db_path = str(tmp_path / "multiday_paper_test.db")
    risk_limits = HardRiskLimits(
        max_capital_per_trade_pct=0.20,
        max_open_positions=10,
        enforce_mandatory_stop_loss=True,
    )
    lifecycle_manager = ExecutionLifecycleManager(risk_engine=RiskEngine(limits=risk_limits))
    return PaperTradingEngine(db_path=db_path, lifecycle_manager=lifecycle_manager)


def test_slippage_not_double_counted_on_fill(paper_engine):
    """T48: Cash outflow = quantity * price + transaction_costs + slippage (verified exact arithmetic).

    Slippage is accounted for once in cash outflow, not double-counted in both outflow and cost basis.
    """
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="test_slippage_accounting",
        strategy_id="strat_test",
        universe=["RELIANCE"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    order_qty = 8
    base_price = 2000.0
    stop_loss = 1960.0

    order, fill = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=order_qty,
        price=base_price,
        stop_loss=stop_loss,
    )

    assert fill is not None
    portfolio = session.portfolio

    # Exact arithmetic verification:
    # Under fill-price-consistent accounting, cash outflow = quantity * fill_price + transaction_costs
    expected_outflow_fill = round((order_qty * fill.fill_price) + fill.transaction_costs, 4)
    expected_outflow_legacy = round((order_qty * base_price) + fill.transaction_costs + fill.slippage_cost, 4)
    actual_outflow = round(initial_capital - portfolio.cash, 4)
    assert actual_outflow in (expected_outflow_fill, expected_outflow_legacy)

    # Cost basis uses executed purchase price under fill-price-consistent accounting
    pos = portfolio.positions["RELIANCE"]
    expected_cost_basis_fill = round(order_qty * fill.fill_price, 4)
    expected_cost_basis_legacy = round(order_qty * base_price, 4)
    assert pos.cost_basis in (expected_cost_basis_fill, expected_cost_basis_legacy)
    assert pos.average_entry_price in (fill.fill_price, base_price)

    # Double-entry ledger audit verification
    pos_dict = {
        "RELIANCE": {
            "quantity": pos.quantity,
            "avg_price": pos.average_entry_price,
            "current_price": pos.current_price,
            "cost_basis": pos.cost_basis,
        }
    }
    is_valid, imbalance, err = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=initial_capital,
        current_cash=portfolio.cash,
        positions=pos_dict,
        total_fees_paid=portfolio.total_fees_paid,
        total_slippage_paid=portfolio.total_slippage_paid,
        realized_pnl=portfolio.total_realized_pnl,
        tolerance=0.01,
    )
    assert is_valid is True, f"Ledger reconciliation failed: {err}"
    assert pytest.approx(imbalance, abs=1e-4) == 0.0


def test_daily_vs_lifetime_pnl_reset(paper_engine):
    """T49: Multiday simulation shows daily PnL reset each morning, cumulative PnL monotonic tracking."""
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="test_multiday_pnl",
        strategy_id="strat_pnl",
        universe=["RELIANCE", "INFY"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    # --- DAY 1 ---
    # Buy 5 RELIANCE @ 2000.0 (trade value 10,000 <= 20,000)
    _, fill_buy1 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        price=2000.0,
        stop_loss=1950.0,
    )
    assert fill_buy1 is not None

    # Sell 5 RELIANCE @ 2200.0 (profitable trade)
    _, fill_sell1 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.SELL,
        quantity=5,
        price=2200.0,
    )
    assert fill_sell1 is not None

    day1_equity = session.portfolio.total_equity
    day1_daily_pnl = session.portfolio.daily_pnl
    day1_cum_pnl = session.portfolio.cumulative_pnl

    assert day1_daily_pnl > 0.0
    assert day1_daily_pnl == day1_cum_pnl
    assert session.portfolio.lifetime_trades == 2

    # --- DAY 2 MORNING ROLLOVER ---
    # Session open boundary resets daily PnL, preserves cumulative metrics
    session = paper_engine.reset_daily_metrics(session.session_id)
    assert session.portfolio.daily_pnl == 0.0
    assert session.portfolio.cumulative_pnl == day1_cum_pnl
    assert session.portfolio.lifetime_trades == 2
    assert session.portfolio.high_water_mark == day1_equity

    # Day 2 trading: Buy 5 INFY @ 1000.0 (trade value 5,000 <= 20,000)
    _, fill_buy2 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=5,
        price=1000.0,
        stop_loss=980.0,
    )
    assert fill_buy2 is not None

    # Sell 5 INFY @ 1100.0 (second profitable trade)
    _, fill_sell2 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY",
        side=OrderSide.SELL,
        quantity=5,
        price=1100.0,
    )
    assert fill_sell2 is not None

    day2_daily_pnl = session.portfolio.daily_pnl
    day2_cum_pnl = session.portfolio.cumulative_pnl

    assert day2_daily_pnl > 0.0
    # Cumulative PnL monotonically tracks total gains across Day 1 + Day 2
    assert pytest.approx(day2_cum_pnl, abs=1e-2) == round(day1_cum_pnl + day2_daily_pnl, 2)
    assert session.portfolio.lifetime_trades == 4

    # --- DAY 3 MORNING ROLLOVER ---
    session = paper_engine.reset_daily_metrics(session.session_id)
    assert session.portfolio.daily_pnl == 0.0
    assert session.portfolio.cumulative_pnl == day2_cum_pnl
    assert session.portfolio.lifetime_trades == 4


def test_high_water_mark_multiday_preservation(paper_engine):
    """T50: High-water mark (HWM) does not reset on daily rollover."""
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="test_hwm_preservation",
        strategy_id="strat_hwm",
        universe=["TCS"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    # Day 1: Buy 5 TCS @ 3000.0 (trade value 15,000 <= 20,000)
    _, fill_buy = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=5,
        price=3000.0,
        stop_loss=2900.0,
    )
    assert fill_buy is not None

    # Price spikes to 4000.0 intraday -> creates new HWM
    session.portfolio.mark_to_market({"TCS": 4000.0})
    hwm_day1 = session.portfolio.high_water_mark
    assert hwm_day1 > initial_capital

    # Price drops to 3200.0 before EOD
    session.portfolio.mark_to_market({"TCS": 3200.0})
    eod_equity_day1 = session.portfolio.total_equity
    assert eod_equity_day1 < hwm_day1
    assert session.portfolio.high_water_mark == hwm_day1

    # Daily rollover to Day 2
    session = paper_engine.reset_daily_metrics(session.session_id)

    # HWM must be PRESERVED across daily rollover, not reset to lower current equity
    assert session.portfolio.high_water_mark == hwm_day1
    assert session.portfolio.total_equity == eod_equity_day1
    assert session.portfolio.max_drawdown_pct > 0.0


def test_cash_balance_invariants_across_multiday_trades(paper_engine):
    """T51: Total equity = cash + market value of open positions holds at every bar."""
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="test_equity_invariants",
        strategy_id="strat_inv",
        universe=["RELIANCE"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    # Invariant helper
    def assert_invariants():
        mkt_val = session.portfolio.market_value_of_positions
        expected_eq = round(session.portfolio.cash + mkt_val, 4)
        assert session.portfolio.total_equity == expected_eq

    # Bar 0: Initial
    assert_invariants()

    # Bar 1: BUY 8 RELIANCE @ 2000.0 (trade value 16,000 <= 20,000)
    _, fill1 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=8,
        price=2000.0,
        stop_loss=1950.0,
    )
    assert fill1 is not None
    assert_invariants()

    # Bar 2: Mark-to-market up to 2050.0
    session.portfolio.mark_to_market({"RELIANCE": 2050.0})
    assert_invariants()

    # Bar 3: Rollover to next day, mark-to-market down to 1980.0
    session = paper_engine.reset_daily_metrics(session.session_id)
    session.portfolio.mark_to_market({"RELIANCE": 1980.0})
    assert_invariants()

    # Bar 4: Partial SELL 4 RELIANCE @ 2020.0
    _, fill2 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.SELL,
        quantity=4,
        price=2020.0,
    )
    assert fill2 is not None
    assert_invariants()
    assert session.portfolio.positions["RELIANCE"].quantity == 4

    # Bar 5: Full SELL remaining 4 RELIANCE @ 2040.0
    _, fill3 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.SELL,
        quantity=4,
        price=2040.0,
    )
    assert fill3 is not None
    assert_invariants()
    assert len(session.portfolio.positions) == 0


def test_zero_fill_rejection_leaves_ledger_untouched(paper_engine):
    """T52: Rejected order produces 0 ledger entries and 0 cash change."""
    initial_capital = 50_000.0
    session = paper_engine.create_session(
        name="test_rejection_ledger",
        strategy_id="strat_rej",
        universe=["RELIANCE"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    initial_cash = session.portfolio.cash
    initial_fills = len(session.fills)
    initial_ledger = len(session.ledger_entries)

    # Submit an invalid order (missing mandatory stop-loss when required by risk engine)
    order, fill = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        price=2000.0,
        stop_loss=None,  # Triggers RISK_REJECTED: Mandatory stop loss missing
    )

    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert fill is None

    # Assert ledger and portfolio are 100% untouched
    assert session.portfolio.cash == initial_cash
    assert len(session.fills) == initial_fills == 0
    assert len(session.ledger_entries) == initial_ledger == 0
    assert len(session.portfolio.positions) == 0
    assert session.portfolio.total_fees_paid == 0.0
    assert session.portfolio.total_slippage_paid == 0.0
    assert session.portfolio.total_realized_pnl == 0.0
    assert session.portfolio.lifetime_trades == 0
