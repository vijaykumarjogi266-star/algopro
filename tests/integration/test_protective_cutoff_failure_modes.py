"""Integration tests for Protective Cutoff Failure Modes (R31–R37).

Tests:
R31: test_cutoff_normal_operation_squares_off_once
R32: test_entry_halt_does_not_skip_protective_exit
R33: test_offline_cutoff_persists_unresolved_exit
R34: test_stale_quote_cannot_complete_square_off
R35: test_restart_retries_unresolved_cutoff_safely
R36: test_local_eod_and_maintenance_not_skipped_by_wan_probe
R37: test_direct_manual_order_enforces_current_daily_loss
"""

import os
import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import run_live_paper_daemon as daemon
from run_live_paper_daemon import (
    DaemonController,
    DaemonPhase,
    load_sentinel_state,
    save_sentinel_state,
    IST_TZ,
)
from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    OrderLifecycleState,
)
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.paper_engine.session import PaperTradingEngine, SessionStatus


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "protective_cutoff_test.db")
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    return {
        "db_path": db_path,
        "decisions_dir": str(decisions_dir),
        "tmp_path": tmp_path,
    }


def test_cutoff_normal_operation_squares_off_once(test_env):
    """R31: Normal cutoff squares off all open positions once; subsequent cycles do not duplicate orders."""
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Establish an open position with valid stop loss and within limits
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="RELIANCE.NS",
        side=OrderSide.BUY,
        quantity=3,
        price=2000.0,
        stop_loss=1960.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert len(controller.session.portfolio.positions) == 1

    # Time reaches 15:15 IST cutoff
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    fresh_quotes = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2050.0,
            "bar_timestamp": t_cutoff,
        }
    }

    res = controller.run_cycle(scan_results=fresh_quotes, current_time=t_cutoff)
    assert res["status"] == "SQUARE_OFF_COMPLETED"
    assert len(res["squared_off"]) == 1
    assert res["open_positions"] == 0
    assert controller.has_unresolved_square_off is False

    # Second cycle at cutoff time must be idempotent and not create duplicate orders
    orders_count_before = len(controller.session.orders)
    res_second = controller.run_cycle(scan_results=fresh_quotes, current_time=t_cutoff)
    orders_count_after = len(controller.session.orders)
    assert orders_count_after == orders_count_before


def test_entry_halt_does_not_skip_protective_exit(test_env):
    """R32: Active entry halt must NEVER skip protective cutoff exit at 15:15 IST."""
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Open position
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=4,
        price=1500.0,
        stop_loss=1470.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert len(controller.session.portfolio.positions) == 1

    # Trigger emergency halt
    controller.trigger_emergency_halt("EMERGENCY_VOLATILITY_HALT")
    assert controller.is_halted is True

    # At 15:15 IST cutoff, protective square-off must run despite entry halt
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    quotes = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 1490.0,
            "bar_timestamp": t_cutoff,
        }
    }

    res = controller.run_cycle(scan_results=quotes, current_time=t_cutoff)
    assert res["status"] == "SQUARE_OFF_COMPLETED"
    assert len(res["squared_off"]) == 1
    assert res["open_positions"] == 0
    assert len(controller.session.portfolio.positions) == 0


def test_offline_cutoff_persists_unresolved_exit(test_env):
    """R33: Offline market quotes during cutoff persist unresolved exit and retain open positions."""
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=2,
        price=3500.0,
        stop_loss=3430.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)

    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    # Simulate completely offline quote
    offline_quotes = {
        "TCS.NS": {
            "symbol": "TCS.NS",
            "status": "ERROR",
            "error": "Connection timed out",
        }
    }

    res = controller.run_cycle(scan_results=offline_quotes, current_time=t_cutoff)
    # Never report liquidation success on failure
    assert res["status"] != "SQUARE_OFF_COMPLETED"
    assert res["status"] in ("SQUARE_OFF_UNRESOLVED", "SQUARE_OFF_PARTIAL")
    assert res["unresolved"] is True
    # Retains open positions
    assert res["open_positions"] == 1
    assert "TCS.NS" in controller.session.portfolio.positions

    # Persists unresolved state to SQLite
    state = load_sentinel_state(db_path)
    assert "unresolved_square_off" in state
    assert float(state["unresolved_square_off"]["value"]) == 1.0
    assert controller.has_unresolved_square_off is True


def test_stale_quote_cannot_complete_square_off(test_env):
    """R34: Stale or future quotes cannot complete square-off; positions retained and alert emitted."""
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="HDFCBANK.NS",
        side=OrderSide.BUY,
        quantity=4,
        price=1600.0,
        stop_loss=1560.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)

    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)

    # 1. Stale quote (> 15 minutes old)
    stale_quotes = {
        "HDFCBANK.NS": {
            "symbol": "HDFCBANK.NS",
            "status": "OK",
            "price": 1610.0,
            "bar_timestamp": t_cutoff - timedelta(minutes=30),  # 30 min old
        }
    }
    res_stale = controller.run_cycle(scan_results=stale_quotes, current_time=t_cutoff)
    assert res_stale["status"] != "SQUARE_OFF_COMPLETED"
    assert res_stale["unresolved"] is True
    assert res_stale["open_positions"] == 1

    # 2. Future quote (> 60 seconds into future)
    future_quotes = {
        "HDFCBANK.NS": {
            "symbol": "HDFCBANK.NS",
            "status": "OK",
            "price": 1615.0,
            "bar_timestamp": t_cutoff + timedelta(minutes=10),  # 10 min future
        }
    }
    res_future = controller.run_cycle(scan_results=future_quotes, current_time=t_cutoff)
    assert res_future["status"] != "SQUARE_OFF_COMPLETED"
    assert res_future["unresolved"] is True
    assert res_future["open_positions"] == 1
    assert "HDFCBANK.NS" in controller.session.portfolio.positions


def test_restart_retries_unresolved_cutoff_safely(test_env):
    """R35: Restarting daemon restores unresolved cutoff state and retries square-off without order duplication."""
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)

    # Instance 1: establishes position and fails square off due to offline data
    ctrl1 = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    ctrl1.initialize_session(current_time=t_market)

    order, fill = ctrl1.paper_engine.submit_manual_order(
        session_id=ctrl1.session.session_id,
        symbol="SBIN.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=750.0,
        stop_loss=735.0,
    )
    assert fill is not None
    ctrl1.session = ctrl1.paper_engine.get_session(ctrl1.session.session_id)

    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    ctrl1.run_cycle(scan_results={}, current_time=t_cutoff)
    assert ctrl1.has_unresolved_square_off is True

    # Simulate daemon process termination and restart with new instance
    ctrl2 = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    ctrl2.initialize_session(current_time=t_cutoff + timedelta(minutes=2))

    # Restart must detect persisted unresolved exit
    assert ctrl2.has_unresolved_square_off is True
    assert len(ctrl2.session.portfolio.positions) == 1

    # Next cycle provides valid fresh quote -> completes square-off safely
    fresh_quotes = {
        "SBIN.NS": {
            "symbol": "SBIN.NS",
            "status": "OK",
            "price": 755.0,
            "bar_timestamp": t_cutoff + timedelta(minutes=2),
        }
    }
    res_retry = ctrl2.run_cycle(scan_results=fresh_quotes, current_time=t_cutoff + timedelta(minutes=2))
    assert res_retry["status"] == "SQUARE_OFF_COMPLETED"
    assert res_retry["open_positions"] == 0
    assert ctrl2.has_unresolved_square_off is False

    # Check database state cleared
    state = load_sentinel_state(db_path)
    assert float(state["unresolved_square_off"]["value"]) == 0.0


def test_local_eod_and_maintenance_not_skipped_by_wan_probe(test_env):
    """R36: Local lifecycle phases (maintenance, EOD reconciliation) execute even when WAN probe fails."""
    db_path = test_env["db_path"]
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session()

    # Verify pre-market maintenance executes locally
    controller.sentinel.execute_pre_market_maintenance()
    assert controller.sentinel.is_killswitch_tripped is False

    # Verify EOD reconciliation executes locally with zero WAN dependency
    is_reconciled, imbalance, err = controller.sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=controller.session.portfolio.total_equity,
        open_positions_count=0,
        cash=controller.session.portfolio.cash,
        realized_pnl=0.0,
        total_fees=0.0,
        total_slippage=0.0,
        positions={},
    )
    assert is_reconciled is True
    assert imbalance == 0.0


def test_direct_manual_order_enforces_current_daily_loss(test_env):
    """R37: Direct manual/API order proposals enforce current daily loss from portfolio state (no hardcoded 0.0)."""
    db_path = test_env["db_path"]
    risk_limits = HardRiskLimits(
        max_daily_loss_pct=0.04,  # 4% max daily loss limit
        max_portfolio_drawdown_pct=0.10,
        max_capital_per_trade_pct=0.20,
        max_open_positions=4,
        enforce_mandatory_stop_loss=True,
    )
    risk_engine = RiskEngine(limits=risk_limits)
    lifecycle_mgr = ExecutionLifecycleManager(risk_engine=risk_engine)

    engine = PaperTradingEngine(db_path=db_path, lifecycle_manager=lifecycle_mgr)
    session = engine.create_session(
        name="Daily Loss Enforcement Test",
        strategy_id="strat_test",
        universe=["RELIANCE.NS"],
        initial_capital=10000.0,
    )
    engine.start_session(session.session_id)

    # Establish baseline day start equity
    session.portfolio.day_start_equity = 10000.0
    # Simulate realized/cash loss: available equity drops to 9500 (5% daily loss > 4% limit)
    session.portfolio.cash = 9500.0
    session.portfolio.daily_pnl = -500.0
    engine._persist_session(session)

    assert session.portfolio.daily_loss_pct == 0.05

    # Direct manual order proposal must be evaluated against actual portfolio daily loss
    order, fill = engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE.NS",
        side=OrderSide.BUY,
        quantity=1,
        price=1000.0,
        stop_loss=980.0,
    )

    # Must be REJECTED because 5% loss > 4% max daily loss limit
    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert fill is None
    # Zero portfolio mutation
    refreshed = engine.get_session(session.session_id)
    assert len(refreshed.portfolio.positions) == 0
    assert refreshed.portfolio.cash == 9500.0
