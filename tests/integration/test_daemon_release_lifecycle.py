"""Integration tests for Daemon Release Lifecycle (T40–T47).

Tests:
T40: test_daemon_1515_ist_mandatory_square_off
T41: test_no_stale_quote_invention_on_square_off
T42: test_scheduled_phases_transition_cleanly
T43: test_daemon_idempotent_restart_midday
T44: test_reason_specific_halt_survives_rollover
T45: test_manifest_target_session_date_validation
T46: test_daemon_stops_on_circuit_breaker_halt
T47: test_admin_rearm_unpauses_daemon
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
    get_daemon_phase,
    validate_manifest,
    save_sentinel_state,
    load_sentinel_state,
    IST_TZ,
)
from services.backtest_engine.contracts import OrderSide
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.contracts import CircuitBreakerConfig
from services.paper_engine.session import SessionStatus


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "paper_lifecycle_test.db")
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    return {
        "db_path": db_path,
        "decisions_dir": str(decisions_dir),
        "tmp_path": tmp_path,
    }


def test_daemon_1515_ist_mandatory_square_off(test_env):
    """T40: Open positions are forcefully squared off at or after 15:15 IST using valid quote."""
    db_path = test_env["db_path"]
    # Wednesday 2026-04-01 10:00 IST (regular market day)
    t_morning = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_morning)

    # Open a long position during morning trading
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="RELIANCE.NS",
        side=OrderSide.BUY,
        quantity=4,
        price=2000.0,
        stop_loss=1960.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert len(controller.session.portfolio.positions) == 1
    assert controller.session.portfolio.positions["RELIANCE.NS"].quantity == 4

    # Advance clock to 15:15 IST on the same trading day
    t_1515 = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    scan_results = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2050.0,
            "high": 2055.0,
            "low": 2045.0,
        }
    }

    res = controller.run_cycle(scan_results=scan_results, current_time=t_1515)

    assert res["status"] == "SQUARE_OFF_COMPLETED"
    assert res["open_positions"] == 0
    assert len(res["squared_off"]) == 1
    assert res["squared_off"][0]["symbol"] == "RELIANCE.NS"
    assert res["squared_off"][0]["quantity"] == 4
    assert res["squared_off"][0]["price"] == 2050.0

    # Verify portfolio is flat
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert len(controller.session.portfolio.positions) == 0


def test_no_stale_quote_invention_on_square_off(test_env, caplog):
    """T41: If market closed or no valid quote exists, square-off logs error rather than inventing prices."""
    db_path = test_env["db_path"]
    t_morning = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_morning)

    # Open a position in INFY
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=1500.0,
        stop_loss=1470.0,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert controller.session.portfolio.positions["INFY.NS"].quantity == 5

    # Clear cached quotes to simulate lack of market data
    controller.last_valid_quotes.clear()

    # Advance clock to 15:15 IST with missing/failing quote feed
    t_1515 = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    scan_results = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "ERROR",
            "error": "Quote feed unavailable",
        }
    }

    res = controller.run_cycle(scan_results=scan_results, current_time=t_1515)

    # Square-off must NOT invent synthetic price (e.g., 0.0 or random guess)
    assert res["status"] == "SQUARE_OFF_PARTIAL"
    assert len(res["square_off_errors"]) == 1
    assert "no valid quote available" in res["square_off_errors"][0]["error"]
    assert "Refusing to invent synthetic quote" in res["square_off_errors"][0]["error"]

    # Position must remain intact rather than filled at invented price
    controller.session = controller.paper_engine.get_session(controller.session.session_id)
    assert "INFY.NS" in controller.session.portfolio.positions
    assert controller.session.portfolio.positions["INFY.NS"].quantity == 5


def test_scheduled_phases_transition_cleanly():
    """T42: Verify premarket -> regular -> eod -> maintenance transitions."""
    base_day = datetime(2026, 4, 1, 0, 0, tzinfo=IST_TZ)  # Wednesday (Market Day)

    # 1. Before pre-market (e.g. 08:30 IST) -> MAINTENANCE
    p_early = get_daemon_phase(base_day.replace(hour=8, minute=30), is_market_day=True)
    assert p_early == DaemonPhase.MAINTENANCE

    # 2. Premarket: 09:00 - 09:15 IST
    p_pre1 = get_daemon_phase(base_day.replace(hour=9, minute=0), is_market_day=True)
    p_pre2 = get_daemon_phase(base_day.replace(hour=9, minute=14), is_market_day=True)
    assert p_pre1 == DaemonPhase.PREMARKET
    assert p_pre2 == DaemonPhase.PREMARKET

    # 3. Regular: 09:15 - 15:15 IST
    p_reg1 = get_daemon_phase(base_day.replace(hour=9, minute=15), is_market_day=True)
    p_reg2 = get_daemon_phase(base_day.replace(hour=12, minute=0), is_market_day=True)
    p_reg3 = get_daemon_phase(base_day.replace(hour=15, minute=14), is_market_day=True)
    assert p_reg1 == DaemonPhase.REGULAR
    assert p_reg2 == DaemonPhase.REGULAR
    assert p_reg3 == DaemonPhase.REGULAR

    # 4. Post-market EOD: 15:15 - 15:30 IST
    p_eod1 = get_daemon_phase(base_day.replace(hour=15, minute=15), is_market_day=True)
    p_eod2 = get_daemon_phase(base_day.replace(hour=15, minute=29), is_market_day=True)
    assert p_eod1 == DaemonPhase.POST_MARKET_EOD
    assert p_eod2 == DaemonPhase.POST_MARKET_EOD

    # 5. After EOD: 15:30 IST onwards -> MAINTENANCE
    p_post1 = get_daemon_phase(base_day.replace(hour=15, minute=30), is_market_day=True)
    p_post2 = get_daemon_phase(base_day.replace(hour=17, minute=0), is_market_day=True)
    assert p_post1 == DaemonPhase.MAINTENANCE
    assert p_post2 == DaemonPhase.MAINTENANCE

    # 6. Non-market day (weekend/holiday) -> MAINTENANCE at any time
    p_weekend = get_daemon_phase(base_day.replace(hour=10, minute=0), is_market_day=False)
    assert p_weekend == DaemonPhase.MAINTENANCE


def test_daemon_idempotent_restart_midday(test_env):
    """T43: Restarting daemon mid-session recovers existing session without duplicating trades."""
    db_path = test_env["db_path"]
    t_start = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)

    # Initial daemon instance runs and executes a trade
    c1 = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    c1.initialize_session(current_time=t_start)
    session_id_original = c1.session.session_id

    order, fill = c1.paper_engine.submit_manual_order(
        session_id=session_id_original,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=3,
        price=3000.0,
        stop_loss=2940.0,
    )
    assert fill is not None
    original_cash = c1.session.portfolio.cash
    original_fills_count = len(c1.session.fills)

    # Midday restart (new daemon controller pointing to same SQLite database)
    t_restart = datetime(2026, 4, 1, 12, 30, tzinfo=IST_TZ)
    c2 = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    c2.initialize_session(current_time=t_restart)

    # Assert idempotent recovery
    assert c2.session.session_id == session_id_original
    assert len(c2.session.portfolio.positions) == 1
    assert c2.session.portfolio.positions["TCS.NS"].quantity == 3
    assert c2.session.portfolio.cash == original_cash
    assert len(c2.session.fills) == original_fills_count

    # Verify no duplicate sessions created
    all_sessions = c2.paper_engine.list_sessions()
    running_sessions = [s for s in all_sessions if s.status == SessionStatus.RUNNING]
    assert len(running_sessions) == 1


def test_reason_specific_halt_survives_rollover(test_env):
    """T44: Emergency reason-specific halt persists across midnight UTC / session rollover until explicit admin rearm."""
    db_path = test_env["db_path"]
    day1_ist = datetime(2026, 4, 1, 14, 0, tzinfo=IST_TZ)

    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=day1_ist)

    # Trigger emergency halt
    controller.trigger_emergency_halt("EMERGENCY_VOLATILITY_CIRCUIT_BREAKER")
    assert controller.is_halted is True
    assert "EMERGENCY_VOLATILITY_CIRCUIT_BREAKER" in controller.halt_reason

    # Rollover to Day 2
    day2_ist = datetime(2026, 4, 2, 9, 30, tzinfo=IST_TZ)
    controller.on_session_check(current_time=day2_ist)

    # Assert halt SURVIVED the rollover
    assert controller.current_session_date == "2026-04-02"
    assert controller.is_halted is True
    assert "EMERGENCY_VOLATILITY_CIRCUIT_BREAKER" in controller.halt_reason

    # Re-initialize on day 2 (process restart): halt state must still be loaded from DB
    c_day2 = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    c_day2.initialize_session(current_time=day2_ist)
    assert c_day2.is_halted is True
    assert "EMERGENCY_VOLATILITY_CIRCUIT_BREAKER" in c_day2.halt_reason


def test_manifest_target_session_date_validation(test_env):
    """T45: Manifest target session date must match current session date; mismatched or invalid rejected."""
    current_date = "2026-04-01"

    # Case 1: Target date matches current session date -> Valid
    manifest_valid = {
        "selected_strategy": "STRAT_ALPHA",
        "risk_multiplier": 1.0,
        "target_session_date": "2026-04-01",
    }
    is_ok, err = validate_manifest(manifest_valid, current_date)
    assert is_ok is True
    assert err is None

    # Case 2: Target date is yesterday (stale manifest) -> Rejected
    manifest_stale = {
        "selected_strategy": "STRAT_ALPHA",
        "risk_multiplier": 1.0,
        "target_session_date": "2026-03-31",
    }
    is_ok, err = validate_manifest(manifest_stale, current_date)
    assert is_ok is False
    assert "does not match current session" in err

    # Case 3: Missing date -> Rejected
    manifest_no_date = {
        "selected_strategy": "STRAT_ALPHA",
        "risk_multiplier": 1.0,
    }
    is_ok, err = validate_manifest(manifest_no_date, current_date)
    assert is_ok is False

    # Case 4: Selected strategy is WAIT -> Rejected
    manifest_wait = {
        "selected_strategy": "WAIT",
        "risk_multiplier": 1.0,
        "target_session_date": "2026-04-01",
    }
    is_ok, err = validate_manifest(manifest_wait, current_date)
    assert is_ok is False

    # Case 5: In run_cycle, mismatched manifest blocks BUY signal
    db_path = test_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Mock sentinel to return stale manifest
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_stale)

    scan_res = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2000.0,
            "signal": "BUY",
            "stop_loss": 1960.0,
            "target": 2080.0,
            "atr": 20.0,
        }
    }
    cycle_out = controller.run_cycle(scan_results=scan_res, current_time=t_market)
    assert cycle_out["open_positions"] == 0
    assert len(controller.session.portfolio.positions) == 0


def test_daemon_stops_on_circuit_breaker_halt(test_env, tmp_path):
    """T46: Daemon main loop pauses trading when execution gateway circuit breaker halts."""
    db_path = test_env["db_path"]
    cb_state_path = str(tmp_path / "cb_state.json")
    cb = CircuitBreakerEngine(
        config=CircuitBreakerConfig(
            rearm_secret="test_secret_rearm_12345678",
            state_integrity_key="test_state_integrity_key_12345",
        ),
        state_file_path=cb_state_path,
        initial_equity=50000.0,
    )

    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(
        db_path=db_path,
        initial_capital=10000.0,
        leverage=5.0,
        circuit_breaker=cb,
    )
    controller.initialize_session(current_time=t_market)

    # Mock valid manifest
    controller.sentinel.get_latest_strategy_decision = MagicMock(
        return_value={
            "selected_strategy": "STRAT_ALPHA",
            "risk_multiplier": 1.0,
            "target_session_date": "2026-04-01",
        }
    )

    # Trip breaker
    cb.trigger_emergency_halt("MAX_DRAWDOWN_BREACH_15%")
    assert controller.is_halted is True

    # Run cycle with BUY signal
    scan_res = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2000.0,
            "signal": "BUY",
            "stop_loss": 1960.0,
            "target": 2080.0,
            "atr": 20.0,
        }
    }
    cycle_out = controller.run_cycle(scan_results=scan_res, current_time=t_market)

    assert cycle_out["status"] == "HALTED"
    assert "MAX_DRAWDOWN_BREACH_15%" in cycle_out["reason"]
    assert len(controller.session.portfolio.positions) == 0


def test_admin_rearm_unpauses_daemon(test_env, tmp_path):
    """T47: Explicit admin rearm restores circuit breaker and unpauses daemon order flow."""
    db_path = test_env["db_path"]
    cb_state_path = str(tmp_path / "cb_state.json")
    rearm_secret = "test_secret_rearm_12345678"
    cb = CircuitBreakerEngine(
        config=CircuitBreakerConfig(
            rearm_secret=rearm_secret,
            state_integrity_key="test_state_integrity_key_12345",
        ),
        state_file_path=cb_state_path,
        initial_equity=50000.0,
    )

    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller = DaemonController(
        db_path=db_path,
        initial_capital=10000.0,
        leverage=5.0,
        circuit_breaker=cb,
    )
    controller.initialize_session(current_time=t_market)

    # Mock valid manifest
    controller.sentinel.get_latest_strategy_decision = MagicMock(
        return_value={
            "selected_strategy": "STRAT_ALPHA",
            "risk_multiplier": 1.0,
            "target_session_date": "2026-04-01",
        }
    )

    # Trip breaker
    controller.trigger_emergency_halt("MANUAL_EMERGENCY_HALT")
    assert controller.is_halted is True

    # Attempt rearm with invalid token -> fails
    rearmed_fail = controller.admin_rearm("wrong_token")
    assert rearmed_fail is False
    assert controller.is_halted is True

    # Rearm with valid secret -> succeeds
    rearmed_ok = controller.admin_rearm(rearm_secret)
    assert rearmed_ok is True
    assert controller.is_halted is False
    assert cb.is_halted is False

    # Execute cycle: order flow must be restored
    scan_res = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2000.0,
            "signal": "BUY",
            "stop_loss": 1960.0,
            "target": 2080.0,
            "atr": 20.0,
        }
    }
    cycle_out = controller.run_cycle(scan_results=scan_res, current_time=t_market)

    assert cycle_out["status"] == "OK"
    assert cycle_out["open_positions"] == 1
    assert "RELIANCE.NS" in controller.session.portfolio.positions
