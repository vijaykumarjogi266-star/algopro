"""Unit tests for Paper Trading Engine, Sessions & Portfolio Accounting (Stage 6)."""

from datetime import datetime, timezone, timedelta
import tempfile
import os
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import OrderLifecycleState, ExecutionFill
from services.paper_engine.adapters.credentials import ExecutionEnvironment
from services.paper_engine.session import (
    PaperTradingEngine,
    PaperSession,
    SessionStatus,
    PaperPortfolio,
    PositionDetail,
)
from services.risk_engine.contracts import RiskRejectionCode


def test_session_lifecycle():
    """Verify session state transitions: CREATED -> RUNNING -> PAUSED -> STOPPED."""
    engine = PaperTradingEngine(":memory:")

    session = engine.create_session(
        name="Momentum Alpha",
        strategy_id="strat_mom_1",
        universe=["TCS", "INFY"],
        initial_capital=1_000_000.0,
    )
    assert session.status == SessionStatus.CREATED
    assert session.initial_capital == 1_000_000.0
    assert session.portfolio.cash == 1_000_000.0
    assert session.portfolio.total_equity == 1_000_000.0

    # Start
    started = engine.start_session(session.session_id)
    assert started.status == SessionStatus.RUNNING
    assert started.started_at is not None

    # Pause
    paused = engine.pause_session(session.session_id)
    assert paused.status == SessionStatus.PAUSED

    # Resume (Start again)
    resumed = engine.start_session(session.session_id)
    assert resumed.status == SessionStatus.RUNNING

    # Stop
    stopped = engine.stop_session(session.session_id)
    assert stopped.status == SessionStatus.STOPPED
    assert stopped.stopped_at is not None


def test_paper_order_execution_and_accounting():
    """Valid paper order fills, updates positions, cash, and satisfies accounting invariants."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session(
        name="Accounting Test",
        strategy_id="strat_test",
        universe=["TCS"],
        initial_capital=1_000_000.0,
    )
    engine.start_session(session.session_id)

    # 1. Submit valid BUY order (10 shares at 3500 INR = 35,000 INR, well within 5% capital limit)
    order, fill = engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        price=3500.0,
        stop_loss=3400.0,
    )
    assert order.state == OrderLifecycleState.ORDER_FILLED
    assert fill is not None
    assert fill.symbol == "TCS"
    assert fill.quantity == 10

    # Verify portfolio state
    sess = engine.get_session(session.session_id)
    pos = sess.portfolio.positions["TCS"]
    assert pos.quantity == 10
    assert pos.average_entry_price == fill.fill_price
    assert sess.portfolio.cash < 1_000_000.0 - (10 * 3500.0)  # Cash reduced by trade + slippage + fees
    assert sess.portfolio.total_fees_paid > 0
    assert sess.portfolio.total_slippage_paid > 0

    # Invariant: total_equity = cash + market value of open positions
    expected_equity = sess.portfolio.cash + (pos.quantity * pos.current_price)
    assert sess.portfolio.total_equity == pytest.approx(expected_equity, abs=1e-3)


def test_risk_rejection_zero_portfolio_mutation():
    """Rejected orders must cause ZERO mutation to cash, positions, or equity."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session(
        name="Risk Rejection Test",
        strategy_id="strat_test",
        universe=["INFY"],
        initial_capital=1_000_000.0,
    )
    engine.start_session(session.session_id)

    initial_cash = session.portfolio.cash
    initial_equity = session.portfolio.total_equity

    # Submit order violating 5% max capital limit (500 shares * 1500 = 750,000 INR > 50,000 INR limit)
    order, fill = engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=500,
        price=1500.0,
        stop_loss=1400.0,
    )
    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert fill is None

    # Verify zero portfolio mutation
    sess = engine.get_session(session.session_id)
    assert sess.portfolio.cash == initial_cash
    assert sess.portfolio.total_equity == initial_equity
    assert len(sess.portfolio.positions) == 0
    assert sess.portfolio.total_fees_paid == 0.0


def test_mark_to_market_and_pnl():
    """Test mark-to-market updates on incoming market data bars."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session(
        name="MTM Test",
        strategy_id="strat_test",
        universe=["SBIN"],
        initial_capital=1_000_000.0,
    )
    engine.start_session(session.session_id)

    # Buy 50 shares of SBIN at 750 INR
    engine.submit_manual_order(
        session_id=session.session_id,
        symbol="SBIN",
        side=OrderSide.BUY,
        quantity=50,
        price=750.0,
        stop_loss=740.0,
    )

    # Process market bar with higher price (770 INR)
    now = datetime.now(timezone.utc)
    bar_up = CanonicalMarketDataBar(
        timestamp=now,
        symbol="SBIN",
        open=755.0,
        high=772.0,
        low=750.0,
        close=770.0,
        volume=10000.0,
    )
    engine.process_bar(session.session_id, bar_up)

    sess = engine.get_session(session.session_id)
    pos = sess.portfolio.positions["SBIN"]
    assert pos.current_price == 770.0
    assert pos.unrealized_pnl > 0
    assert sess.portfolio.total_unrealized_pnl > 0


def test_live_trading_hard_disable_in_session():
    """Creating a session with LIVE environment must fail closed."""
    engine = PaperTradingEngine(":memory:")

    with pytest.raises(PermissionError) as exc:
        engine.create_session(
            name="Illegal Live",
            strategy_id="strat_live",
            universe=["RELIANCE"],
            environment=ExecutionEnvironment.LIVE,
        )
    assert "LIVE trading session creation is strictly prohibited" in str(exc.value)


def test_session_persistence():
    """Ensure sessions persist and recover accurately from SQLite database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        eng1 = PaperTradingEngine(db_path=db_path)
        sess = eng1.create_session(
            name="Persistent Session",
            strategy_id="strat_persist",
            universe=["HDFCBANK"],
            initial_capital=500_000.0,
        )
        eng1.start_session(sess.session_id)

        # Re-open with new engine instance
        eng2 = PaperTradingEngine(db_path=db_path)
        recovered = eng2.get_session(sess.session_id)
        assert recovered is not None
        assert recovered.name == "Persistent Session"
        assert recovered.status == SessionStatus.RUNNING
        assert recovered.initial_capital == 500_000.0
        assert len(eng2.list_sessions()) == 1
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_cash_solvency_cash_10k_buy_20k_rejected():
    """Test 1: Cash 10,000, BUY 20,000 must be rejected with zero mutation."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Test 10k/20k", "s1", ["TCS", "INFY"], initial_capital=1_000_000.0)
    engine.start_session(session.session_id)

    # Set cash to 10k, open position in INFY to maintain 1M equity (allowing 50k trade cap)
    session.portfolio.cash = 10_000.0
    session.portfolio.positions["INFY"] = PositionDetail(
        symbol="INFY", quantity=660, average_entry_price=1500.0, current_price=1500.0,
        cost_basis=990_000.0, market_value=990_000.0
    )

    # BUY 10 TCS @ 2000 = 20,000 INR (under 50k equity cap, but cash is only 10k)
    order, fill = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 10, 2000.0, stop_loss=1900.0)

    # Invariants 1, 6, 7, 8, 9, 10:
    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert order.rejection_code == RiskRejectionCode.INSUFFICIENT_CASH.value
    assert fill is None
    assert session.portfolio.cash == 10_000.0
    assert "TCS" not in session.portfolio.positions
    assert session.portfolio.positions["INFY"].quantity == 660

    # Test 10: Session retrieval from DB succeeds cleanly
    del engine._sessions[session.session_id]
    recovered = engine.get_session(session.session_id)
    assert recovered is not None
    assert recovered.portfolio.cash == 10_000.0
    assert recovered.portfolio.total_equity == 1_000_000.0


def test_cash_solvency_fees_slippage_exceeding_cash_rejected():
    """Test 2: Cash 20,000, BUY 20,000 rejected because slippage + costs exceed cash."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Test Fees", "s1", ["TCS", "INFY"], initial_capital=1_000_000.0)
    engine.start_session(session.session_id)

    session.portfolio.cash = 20_000.0
    session.portfolio.positions["INFY"] = PositionDetail(
        symbol="INFY", quantity=653, average_entry_price=1500.0, current_price=1500.0,
        cost_basis=979_500.0, market_value=980_000.0
    )

    # Trade value is 20,000. Required outflow will be ~20,021 INR > 20,000 INR
    order, fill = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 10, 2000.0, stop_loss=1900.0)

    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert order.rejection_code == RiskRejectionCode.INSUFFICIENT_CASH.value
    assert fill is None
    assert session.portfolio.cash == 20_000.0
    assert "TCS" not in session.portfolio.positions

    # Database reload must succeed
    del engine._sessions[session.session_id]
    recovered = engine.get_session(session.session_id)
    assert recovered is not None
    assert recovered.portfolio.cash == 20_000.0


def test_cash_solvency_cash_30k_buy_20k_accepted():
    """Test 3: Cash 30,000, BUY 20,000 accepted and cash remains strictly positive."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Test Sufficient", "s1", ["TCS", "INFY"], initial_capital=1_000_000.0)
    engine.start_session(session.session_id)

    session.portfolio.cash = 30_000.0
    session.portfolio.positions["INFY"] = PositionDetail(
        symbol="INFY", quantity=646, average_entry_price=1500.0, current_price=1500.0,
        cost_basis=969_000.0, market_value=970_000.0
    )

    order, fill = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 10, 2000.0, stop_loss=1900.0)

    assert order.state == OrderLifecycleState.ORDER_FILLED
    assert fill is not None
    assert fill.symbol == "TCS"
    assert session.portfolio.cash > 0
    assert session.portfolio.cash == pytest.approx(30_000.0 - fill.net_traded_value - fill.transaction_costs, abs=1e-3)
    assert "TCS" in session.portfolio.positions
    assert session.portfolio.positions["TCS"].quantity == 10

    # DB reload
    del engine._sessions[session.session_id]
    recovered = engine.get_session(session.session_id)
    assert recovered is not None
    assert recovered.portfolio.cash > 0


def test_cash_solvency_partial_sell_then_buy():
    """Test 4: Partial SELL frees cash allowing subsequent BUY to succeed."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Partial Sell Buy", "s1", ["TCS"], initial_capital=1_000_000.0)
    engine.start_session(session.session_id)

    # Buy 20 TCS @ 2000
    o1, f1 = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 20, 2000.0, stop_loss=1900.0)
    assert o1.state == OrderLifecycleState.ORDER_FILLED
    cash_after_buy1 = session.portfolio.cash

    # Partial sell 10 TCS @ 2100 -> cash increases
    o2, f2 = engine.submit_manual_order(session.session_id, "TCS", OrderSide.SELL, 10, 2100.0, stop_loss=2200.0)
    assert o2.state == OrderLifecycleState.ORDER_FILLED
    assert session.portfolio.cash > cash_after_buy1
    assert session.portfolio.positions["TCS"].quantity == 10

    # Subsequent BUY 10 TCS @ 2100 -> succeeds
    o3, f3 = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 10, 2100.0, stop_loss=2000.0)
    assert o3.state == OrderLifecycleState.ORDER_FILLED
    assert session.portfolio.positions["TCS"].quantity == 20
    assert session.portfolio.cash > 0


def test_cash_solvency_shared_cash_pool_multiple_symbols():
    """Test 5: Multiple symbols share cash pool; second BUY rejected when cash depleted."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Multi Symbol Shared Cash", "s1", ["TCS", "INFY", "SBIN"], initial_capital=1_000_000.0)
    engine.start_session(session.session_id)

    # Set cash to 30k, open position in SBIN (970k)
    session.portfolio.cash = 30_000.0
    session.portfolio.positions["SBIN"] = PositionDetail(
        symbol="SBIN", quantity=1293, average_entry_price=750.0, current_price=750.0,
        cost_basis=969_750.0, market_value=970_000.0
    )

    # First BUY: TCS 10 @ 2000 consumes ~20,021 INR
    o1, f1 = engine.submit_manual_order(session.session_id, "TCS", OrderSide.BUY, 10, 2000.0, stop_loss=1900.0)
    assert o1.state == OrderLifecycleState.ORDER_FILLED
    assert f1 is not None
    remaining_cash = session.portfolio.cash
    assert remaining_cash == pytest.approx(30_000.0 - f1.net_traded_value - f1.transaction_costs, abs=1e-3)
    assert remaining_cash < 10_000.0

    # Second BUY: INFY 10 @ 1500 requires ~15,016 INR > remaining cash (~9,978 INR)
    o2, f2 = engine.submit_manual_order(session.session_id, "INFY", OrderSide.BUY, 10, 1500.0, stop_loss=1400.0)

    # Invariants 5, 6, 7, 8, 9, 10:
    assert o2.state == OrderLifecycleState.ORDER_REJECTED
    assert o2.rejection_code == RiskRejectionCode.INSUFFICIENT_CASH.value
    assert f2 is None
    # Cash must remain exactly unchanged by second rejected order
    assert session.portfolio.cash == remaining_cash
    assert "INFY" not in session.portfolio.positions
    assert len(session.portfolio.positions) == 2  # SBIN and TCS only

    # Session recovery from DB must succeed
    del engine._sessions[session.session_id]
    recovered = engine.get_session(session.session_id)
    assert recovered is not None
    assert recovered.portfolio.cash == remaining_cash
    assert len(recovered.portfolio.positions) == 2


def test_defensive_cash_invariant_in_paper_portfolio():
    """Defensive Invariant: PaperPortfolio.on_fill() raises ValueError on insufficient cash."""
    portfolio = PaperPortfolio.initialize(10_000.0)
    fill = ExecutionFill(
        order_id="o_excess",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=10,
        base_price=2000.0,
        fill_price=2001.0,
        slippage_pts=1.0,
        slippage_cost=10.0,
        transaction_costs=20.0,
        net_traded_value=20_010.0,
    )

    with pytest.raises(ValueError) as exc:
        portfolio.on_fill(fill)
    assert "Defensive cash invariant violation" in str(exc.value)
    # Cash must remain positive and unmutated
    assert portfolio.cash == 10_000.0
    assert len(portfolio.positions) == 0
