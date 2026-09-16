"""Unit tests for Paper Trading Engine, Sessions & Portfolio Accounting (Stage 6)."""

from datetime import datetime, timezone, timedelta
import tempfile
import os
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import OrderLifecycleState
from services.paper_engine.adapters.credentials import ExecutionEnvironment
from services.paper_engine.session import (
    PaperTradingEngine,
    PaperSession,
    SessionStatus,
    PaperPortfolio,
)


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
