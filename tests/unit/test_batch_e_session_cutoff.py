"""Unit tests for Batch E: Exchange-Session Cutoff Handling (E01 - E08).

Adheres to Non-Negotiable Principles:
- Principle 13: Data validation must fail closed.
- Principle 14: Risk engine remains independent.
- Principle 25: Paper trading remains completely separate from live broker execution.
- Real behavioral testing: zero mocked-success or source-string checks.
"""

from datetime import datetime, timezone, timedelta
import math
import os
import pytest
import sqlite3

from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    OrderLifecycleState,
)
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from services.risk_engine.engine import RiskEngine
from services.market_data.calendar import IndianMarketCalendar, IST_TZ
from services.paper_engine.session import (
    PaperTradingEngine,
    PaperSession,
    SessionStatus,
)
from run_live_paper_daemon import (
    DaemonController,
    DaemonPhase,
    load_sentinel_state,
    save_sentinel_state,
)

UNIVERSE_E = ["TCS.NS", "INFY.NS", "RELIANCE.NS", "SBIN.NS", "HDFCBANK.NS"]


@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / "test_paper_batch_e.db")


@pytest.fixture
def paper_engine(test_db_path):
    limits = HardRiskLimits(
        max_daily_loss_pct=0.05,
        max_portfolio_drawdown_pct=0.15,
        max_capital_per_trade_pct=0.20,
        max_open_positions=5,
        enforce_mandatory_stop_loss=True,
    )
    risk_engine = RiskEngine(limits=limits)
    lifecycle_manager = ExecutionLifecycleManager(risk_engine=risk_engine)
    return PaperTradingEngine(test_db_path, lifecycle_manager=lifecycle_manager)


def test_e01_weekend_or_holiday_timestamps_reject_order_submission(paper_engine):
    """E01: Weekend or official exchange holiday timestamps reject order submission."""
    session = paper_engine.create_session("E01 Session", strategy_id="STRAT_SMA", universe=UNIVERSE_E, initial_capital=100000.0)
    paper_engine.start_session(session.session_id)

    # 1. Saturday timestamp: 2026-04-04 10:30 IST
    t_weekend = datetime(2026, 4, 4, 10, 30, tzinfo=IST_TZ)
    order_sat, fill_sat = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=3500.0,
        stop_loss=3400.0,
        current_time=t_weekend,
    )
    assert fill_sat is None
    assert order_sat.state == OrderLifecycleState.ORDER_REJECTED
    assert order_sat.rejection_code == RiskRejectionCode.SESSION_CLOSED.value
    assert "weekend" in order_sat.rejection_reason.lower()

    # 2. Sunday timestamp: 2026-04-05 11:00 IST
    t_sunday = datetime(2026, 4, 5, 11, 0, tzinfo=IST_TZ)
    order_sun, fill_sun = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1500.0,
        stop_loss=1450.0,
        current_time=t_sunday,
    )
    assert fill_sun is None
    assert order_sun.state == OrderLifecycleState.ORDER_REJECTED
    assert order_sun.rejection_code == RiskRejectionCode.SESSION_CLOSED.value

    # 3. Official exchange holiday: Republic Day 2026-01-26 10:30 IST
    t_holiday = datetime(2026, 1, 26, 10, 30, tzinfo=IST_TZ)
    order_hol, fill_hol = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=2500.0,
        stop_loss=2400.0,
        current_time=t_holiday,
    )
    assert fill_hol is None
    assert order_hol.state == OrderLifecycleState.ORDER_REJECTED
    assert order_hol.rejection_code == RiskRejectionCode.SESSION_CLOSED.value
    assert "holiday" in order_hol.rejection_reason.lower()

    # Portfolio invariants preserved: zero mutations
    sess_updated = paper_engine.get_session(session.session_id)
    assert sess_updated.portfolio.cash == 100000.0
    assert len(sess_updated.portfolio.positions) == 0
    assert sess_updated.portfolio.lifetime_trades == 0


def test_e02_timestamps_outside_market_hours_reject(paper_engine):
    """E02: Timestamps outside market hours (09:15 - 15:30 IST) reject."""
    session = paper_engine.create_session("E02 Session", strategy_id="STRAT_SMA", universe=UNIVERSE_E, initial_capital=100000.0)
    paper_engine.start_session(session.session_id)

    # 1. Pre-market on a regular trading day (Wednesday 2026-04-01 09:10 IST)
    t_pre = datetime(2026, 4, 1, 9, 10, tzinfo=IST_TZ)
    order_pre, fill_pre = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="SBIN.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=750.0,
        stop_loss=730.0,
        current_time=t_pre,
    )
    assert fill_pre is None
    assert order_pre.state == OrderLifecycleState.ORDER_REJECTED
    assert order_pre.rejection_code == RiskRejectionCode.SESSION_CLOSED.value
    assert "before session open" in order_pre.rejection_reason.lower()

    # 2. Post-market on a regular trading day (Wednesday 2026-04-01 15:35 IST)
    t_post = datetime(2026, 4, 1, 15, 35, tzinfo=IST_TZ)
    order_post, fill_post = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="SBIN.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=750.0,
        stop_loss=730.0,
        current_time=t_post,
    )
    assert fill_post is None
    assert order_post.state == OrderLifecycleState.ORDER_REJECTED
    assert order_post.rejection_code == RiskRejectionCode.SESSION_CLOSED.value
    assert "after session close" in order_post.rejection_reason.lower()

    # 3. Nighttime (Wednesday 2026-04-01 22:00 IST)
    t_night = datetime(2026, 4, 1, 22, 0, tzinfo=IST_TZ)
    order_night, fill_night = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="SBIN.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=750.0,
        stop_loss=730.0,
        current_time=t_night,
    )
    assert fill_night is None
    assert order_night.state == OrderLifecycleState.ORDER_REJECTED
    assert order_night.rejection_code == RiskRejectionCode.SESSION_CLOSED.value

    # 4. Valid regular session time (Wednesday 2026-04-01 10:00 IST) succeeds!
    t_valid = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    order_ok, fill_ok = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="SBIN.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=750.0,
        stop_loss=730.0,
        current_time=t_valid,
    )
    assert fill_ok is not None
    assert order_ok.state == OrderLifecycleState.ORDER_FILLED


def test_e03_stale_and_future_quotes_reject(paper_engine):
    """E03: Stale quotes exceeding max age (>900s) or future quotes reject."""
    session = paper_engine.create_session("E03 Session", strategy_id="STRAT_SMA", universe=UNIVERSE_E, initial_capital=100000.0)
    paper_engine.start_session(session.session_id)

    t_now = datetime(2026, 4, 1, 11, 0, tzinfo=IST_TZ)

    # 1. Stale quote: 1200 seconds (20 minutes) old relative to reference time
    t_stale = t_now - timedelta(seconds=1200)
    order_stale, fill_stale = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="HDFCBANK.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1600.0,
        stop_loss=1560.0,
        current_time=t_now,
        quote_timestamp=t_stale,
        max_quote_age_seconds=900.0,
    )
    assert fill_stale is None
    assert order_stale.state == OrderLifecycleState.ORDER_REJECTED
    assert order_stale.rejection_code == RiskRejectionCode.STALE_MARKET_DATA.value
    assert "stale quote timestamp" in order_stale.rejection_reason.lower()

    # 2. Future quote: 5 minutes into the future relative to reference time
    t_future = t_now + timedelta(minutes=5)
    order_fut, fill_fut = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="HDFCBANK.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1600.0,
        stop_loss=1560.0,
        current_time=t_now,
        quote_timestamp=t_future,
    )
    assert fill_fut is None
    assert order_fut.state == OrderLifecycleState.ORDER_REJECTED
    assert order_fut.rejection_code == RiskRejectionCode.STALE_MARKET_DATA.value
    assert "future quote timestamp" in order_fut.rejection_reason.lower()

    # 3. Fresh quote: 30 seconds old relative to reference time succeeds
    t_fresh = t_now - timedelta(seconds=30)
    order_fresh, fill_fresh = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="HDFCBANK.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1600.0,
        stop_loss=1560.0,
        current_time=t_now,
        quote_timestamp=t_fresh,
    )
    assert fill_fresh is not None
    assert order_fresh.state == OrderLifecycleState.ORDER_FILLED


def test_e04_zero_negative_or_nan_prices_reject_before_execution(paper_engine):
    """E04: Zero, negative, or NaN prices reject before execution and leave portfolio unchanged."""
    session = paper_engine.create_session("E04 Session", strategy_id="STRAT_SMA", universe=UNIVERSE_E, initial_capital=50000.0)
    paper_engine.start_session(session.session_id)
    t_valid = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)

    # 1. Zero price
    order_zero, fill_zero = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=0.0,
        current_time=t_valid,
    )
    assert fill_zero is None
    assert order_zero.state == OrderLifecycleState.ORDER_REJECTED
    assert "Price must be strictly positive and finite" in order_zero.rejection_reason

    # 2. Negative price
    order_neg, fill_neg = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=-150.0,
        current_time=t_valid,
    )
    assert fill_neg is None
    assert order_neg.state == OrderLifecycleState.ORDER_REJECTED

    # 3. NaN price
    order_nan, fill_nan = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=float("nan"),
        current_time=t_valid,
    )
    assert fill_nan is None
    assert order_nan.state == OrderLifecycleState.ORDER_REJECTED

    # 4. Inf price
    order_inf, fill_inf = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=float("inf"),
        current_time=t_valid,
    )
    assert fill_inf is None
    assert order_inf.state == OrderLifecycleState.ORDER_REJECTED

    # Portfolio state must remain completely unmutated
    sess_after = paper_engine.get_session(session.session_id)
    assert sess_after.portfolio.cash == 50000.0
    assert len(sess_after.portfolio.positions) == 0
    assert sess_after.portfolio.lifetime_trades == 0


def test_e05_unresolved_exit_marks_quarantine_until_verified_recovery(test_db_path, paper_engine):
    """E05: Unresolved exit state marks position quarantine and prohibits new entries until verified recovery."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=test_db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Establish an open position
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1500.0,
        stop_loss=1450.0,
        current_time=t_market,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    pos = controller.session.portfolio.positions["INFY.NS"]
    assert pos.quantity == 5
    assert pos.is_quarantined is False

    # Trigger cutoff with missing/offline quote to induce unresolved exit failure
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    res_cutoff = controller.run_cycle(scan_results={}, current_time=t_cutoff)
    assert res_cutoff["unresolved"] is True
    assert controller.has_unresolved_square_off is True

    # Position must now be marked quarantined
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    pos_quarantined = controller.session.portfolio.positions["INFY.NS"]
    assert pos_quarantined.is_quarantined is True
    assert pos_quarantined.quarantine_reason is not None

    # Test quarantine defense on running session:
    # If the session is resumed/re-armed but position remains quarantined:
    controller.session.status = SessionStatus.RUNNING
    controller.paper_engine._persist_session(controller.session)
    order_avg, fill_avg = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=2,
        price=1500.0,
        current_time=datetime(2026, 4, 1, 15, 20, tzinfo=IST_TZ),
    )
    assert fill_avg is None
    assert order_avg.state == OrderLifecycleState.ORDER_REJECTED
    assert order_avg.rejection_code == RiskRejectionCode.PROHIBITED_INSTRUMENT.value
    assert "quarantined" in order_avg.rejection_reason.lower()

    # Recovery: Provide fresh quote to resolve the cutoff
    fresh_quotes = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 1510.0,
            "bar_timestamp": datetime(2026, 4, 1, 15, 25, tzinfo=IST_TZ),
        }
    }
    res_recover = controller.run_cycle(scan_results=fresh_quotes, current_time=datetime(2026, 4, 1, 15, 25, tzinfo=IST_TZ))
    assert res_recover["status"] == "SQUARE_OFF_COMPLETED"
    assert res_recover["open_positions"] == 0
    assert controller.has_unresolved_square_off is False


def test_e06_auto_square_off_triggers_strictly_at_1515_ist(test_db_path):
    """E06: Auto-square-off triggers strictly at session cutoff (15:15 IST)."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=test_db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Establish an open position
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="RELIANCE.NS",
        side=OrderSide.BUY,
        quantity=4,
        price=2000.0,
        stop_loss=1950.0,
        current_time=t_market,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert len(controller.session.portfolio.positions) == 1

    # Cycle at 15:14 IST (1 minute before cutoff) -> Position must NOT be squared off
    t_before = datetime(2026, 4, 1, 15, 14, tzinfo=IST_TZ)
    scan_before = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2010.0,
            "bar_timestamp": t_before,
        }
    }
    res_before = controller.run_cycle(scan_results=scan_before, current_time=t_before)
    assert res_before["status"] != "SQUARE_OFF_COMPLETED"
    assert res_before["open_positions"] == 1
    assert "RELIANCE.NS" in controller.session.portfolio.positions

    # Cycle at 15:15 IST (exact cutoff boundary) -> Square-off MUST trigger and complete!
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    scan_cutoff = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2012.0,
            "bar_timestamp": t_cutoff,
        }
    }
    res_cutoff = controller.run_cycle(scan_results=scan_cutoff, current_time=t_cutoff)
    assert res_cutoff["status"] == "SQUARE_OFF_COMPLETED"
    assert res_cutoff["open_positions"] == 0
    assert len(res_cutoff["squared_off"]) == 1
    assert res_cutoff["squared_off"][0]["symbol"] == "RELIANCE.NS"
    assert res_cutoff["squared_off"][0]["price"] == 2012.0


def test_e07_forced_exit_failure_transitions_to_emergency_halt(test_db_path):
    """E07: Forced exit failure during square-off transitions session to EMERGENCY_HALT."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=test_db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Establish an open position
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=2,
        price=3500.0,
        stop_loss=3400.0,
        current_time=t_market,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert controller.session.status == SessionStatus.RUNNING
    assert controller.is_halted is False

    # Force square-off failure at 15:15 IST with offline quote
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    offline_scan = {
        "TCS.NS": {
            "symbol": "TCS.NS",
            "status": "OFFLINE",
            "error": "Quote feed unavailable",
        }
    }
    res = controller.run_cycle(scan_results=offline_scan, current_time=t_cutoff)

    # Must transition to EMERGENCY_HALT
    assert controller.is_halted is True
    assert "Forced exit failure during square-off" in (controller.halt_reason or "")
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert controller.session.status == SessionStatus.EMERGENCY_HALT

    # In EMERGENCY_HALT, routine BUY order submissions must be blocked
    with pytest.raises(ValueError, match="Cannot submit buy order to session in state"):
        controller.paper_engine.submit_manual_order(
            session_id=controller.session.session_id,
            symbol="INFY.NS",
            side=OrderSide.BUY,
            quantity=5,
            price=1500.0,
            current_time=datetime(2026, 4, 1, 15, 20, tzinfo=IST_TZ),
        )


def test_e08_reconnect_during_closed_session_keeps_trading_halted(test_db_path):
    """E08: Reconnect during closed session attaches to session but keeps trading halted."""
    # Scenario A: Reconnect to clean session without open positions
    t_closed = datetime(2026, 4, 1, 20, 0, tzinfo=IST_TZ)
    ctrl_clean = DaemonController(db_path=test_db_path, initial_capital=10000.0, leverage=5.0)
    ctrl_clean.initialize_session(current_time=t_closed)

    assert ctrl_clean.session is not None
    assert ctrl_clean.session.status == SessionStatus.PAUSED
    assert ctrl_clean.is_halted is True

    # New BUY orders are prohibited during paused closed session
    with pytest.raises(ValueError, match="Cannot submit buy order to session in state"):
        ctrl_clean.paper_engine.submit_manual_order(
            session_id=ctrl_clean.session.session_id,
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=2,
            price=3500.0,
            current_time=t_closed,
        )

    # Cycle execution reflects halted phase with zero new trades
    scan_night = {
        "SBIN.NS": {"symbol": "SBIN.NS", "status": "OK", "price": 752.0},
        "TCS.NS": {"symbol": "TCS.NS", "status": "OK", "price": 3500.0, "signal": "BUY"},
    }
    cycle_clean = ctrl_clean.run_cycle(scan_results=scan_night, current_time=t_closed)
    assert cycle_clean["status"] == "HALTED"
    assert cycle_clean["open_positions"] == 0
    assert "TCS.NS" not in ctrl_clean.session.portfolio.positions

    # Scenario B: Existing session created during market hours, daemon restarts at night
    db_path2 = test_db_path + "_b"
    t_market = datetime(2026, 4, 1, 11, 0, tzinfo=IST_TZ)
    ctrl1 = DaemonController(db_path=db_path2, initial_capital=10000.0, leverage=5.0)
    ctrl1.initialize_session(current_time=t_market)
    orig_sess_id = ctrl1.session.session_id

    ctrl2 = DaemonController(db_path=db_path2, initial_capital=10000.0, leverage=5.0)
    ctrl2.initialize_session(current_time=t_closed)
    assert ctrl2.session.session_id == orig_sess_id
    assert ctrl2.session.status == SessionStatus.PAUSED
    assert ctrl2.is_halted is True
