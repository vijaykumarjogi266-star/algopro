import os
import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import run_live_paper_daemon as daemon
from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.paper_engine.session import PaperTradingEngine, OrderSide


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "paper_test.db")
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    return {
        "db_path": db_path,
        "decisions_dir": str(decisions_dir),
        "tmp_path": tmp_path,
    }


def test_restart_restores_real_daily_loss_baseline(test_env):
    """
    Test 39: Persist baseline 60,000; restart with fresh equity 58,400.
    Assert 2.667% daily loss and new-entry freeze at the 2.5% threshold.
    """
    db_path = test_env["db_path"]
    now_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    session_date = daemon.get_ist_session_date(now_ist)

    # Persist baseline 60,000 for today's IST session
    daemon.save_sentinel_state(db_path, "day_start_equity", 60000.0, session_date=session_date)
    daemon.save_sentinel_state(db_path, "high_water_mark", 60000.0, session_date=session_date)

    # Restart daemon / sentinel with fresh equity 58,400
    controller = daemon.DaemonController(db_path=db_path, initial_capital=12000.0, leverage=5.0)
    controller.initialize_session(current_time=now_ist, current_equity=58400.0)

    # Assert baseline was restored as 60,000
    assert controller.day_start_equity == 60000.0

    risk_state = daemon.compute_risk_state(
        day_start_equity=controller.day_start_equity,
        high_water_mark=controller.high_water_mark,
        current_equity=58400.0,
    )
    # (60000 - 58400) / 60000 = 1600 / 60000 = 0.026666... (2.667%)
    assert pytest.approx(risk_state["daily_loss_pct"], abs=1e-4) == 0.02667
    
    # Check that sentinel killswitch trips at 2.5% threshold (2.667% > 2.5%)
    is_tripped = controller.sentinel.check_daily_drawdown_killswitch(58400.0)
    assert is_tripped is True
    assert controller.sentinel.is_killswitch_tripped is True


def test_session_rollover_resets_baseline_once(test_env):
    """
    Test 40: Advance fake clock into next IST session.
    Assert sentinel and risk engine share the same new baseline.
    Assert lifetime HWM unchanged and repeated cycles do not reset baseline.
    """
    db_path = test_env["db_path"]
    day1_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    day2_ist = datetime(2026, 4, 2, 9, 30, tzinfo=daemon.IST_TZ)

    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=day1_ist, current_equity=50000.0)
    controller.high_water_mark = 55000.0
    daemon.save_sentinel_state(db_path, "high_water_mark", 55000.0, session_date=daemon.get_ist_session_date(day1_ist))

    # Advance clock to day 2 (next IST session) with current equity 52,000
    controller.on_session_check(current_time=day2_ist, current_equity=52000.0)

    # Sentinel and controller must share the new day-start baseline of 52,000
    assert controller.day_start_equity == 52000.0
    assert controller.sentinel.daily_starting_equity == 52000.0
    # Lifetime HWM must remain 55,000 (not reset)
    assert controller.high_water_mark == 55000.0

    # Repeated cycles on day 2 with equity changes must NOT reset the daily baseline
    controller.on_session_check(current_time=day2_ist + timedelta(minutes=15), current_equity=51500.0)
    assert controller.day_start_equity == 52000.0
    assert controller.sentinel.daily_starting_equity == 52000.0


def test_ist_midnight_not_host_date_controls_session(test_env):
    """
    Test 41: Restart while IST and UTC dates differ.
    Assert state belongs to the correct exchange session.
    """
    db_path = test_env["db_path"]
    # UTC: 2026-03-31 20:30:00 -> IST: 2026-04-01 02:00:00 (+5:30)
    utc_time = datetime(2026, 3, 31, 20, 30, 0, tzinfo=timezone.utc)
    ist_time = utc_time.astimezone(daemon.IST_TZ)

    assert utc_time.strftime("%Y-%m-%d") == "2026-03-31"
    assert ist_time.strftime("%Y-%m-%d") == "2026-04-01"

    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=utc_time, current_equity=50000.0)

    # The persisted session_date must be "2026-04-01" (IST session date), NOT "2026-03-31"
    state = daemon.load_sentinel_state(db_path)
    assert state["day_start_equity"]["session_date"] == "2026-04-01"


def test_fresh_marks_precede_buy_risk_evaluation(test_env):
    """
    Test 42: Existing position quote reduces equity 50,000 -> 48,000.
    Another symbol emits BUY.
    Assert daily-loss gate blocks the entry using fresh equity.
    """
    db_path = test_env["db_path"]
    now_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=now_ist, current_equity=50000.0)
    controller.day_start_equity = 50000.0
    controller.sentinel.daily_starting_equity = 50000.0

    # Inject an existing open position in INFY (10 shares bought at 1200)
    # Price drops to 1000 (-2000 INR loss -> equity drops 50k -> 48k)
    controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="INFY.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=1200.0,
        stop_loss=900.0,
    )
    # Update cash to 38,000 so total equity initially was 50,000
    controller.session.portfolio.cash = 38000.0
    controller.paper_engine._persist_session(controller.session)

    # In scan data, INFY is priced at 1000 (fresh mark causes equity = 38000 + 10000 = 48000 -> 4% daily loss)
    # RELIANCE emits a BUY signal
    scan_results = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 1000.0,
            "high": 1010.0,
            "low": 990.0,
            "signal": "WAIT",
            "atr": 10.0,
            "historical_returns": [0.01] * 25,
        },
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2500.0,
            "high": 2510.0,
            "low": 2490.0,
            "signal": "BUY",
            "stop_loss": 2450.0,
            "target": 2600.0,
            "atr": 20.0,
            "historical_returns": [0.01] * 25,
        },
    }

    # Valid strategy manifest
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value={
        "selected_strategy": "STRAT_SMA",
        "risk_multiplier": 1.0,
        "session_date": "2026-04-01",
    })

    # Run cycle: fresh marks of INFY must happen before evaluating RELIANCE BUY
    # Daily loss = (50000 - 48000) / 50000 = 4.0%, which breaches the 2.5% limit!
    cycle_summary = controller.run_cycle(scan_results=scan_results, current_time=now_ist)

    # RELIANCE BUY must be rejected/blocked due to daily loss limit
    orders = controller.paper_engine.list_orders(controller.session.session_id)
    buy_orders = [o for o in orders if o.symbol == "RELIANCE.NS"]
    assert len(buy_orders) == 0, "RELIANCE BUY should have been blocked by fresh position mark breach"


def test_hwm_updates_without_buy_signal(test_env):
    """
    Test 43: WAIT-only valuations: 50,000 -> 55,000 -> 50,000.
    Assert persisted HWM 55,000 and drawdown approximately 9.0909%.
    """
    db_path = test_env["db_path"]
    now_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=now_ist, current_equity=50000.0)

    scan_wait = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2500.0,
            "signal": "WAIT",
            "atr": 20.0,
        }
    }

    # Step 1: Equity 50,000
    controller.session.portfolio.cash = 50000.0
    controller.run_cycle(scan_results=scan_wait, current_time=now_ist)
    assert controller.high_water_mark == 50000.0

    # Step 2: Equity rises to 55,000 on WAIT-only cycle
    controller.session.portfolio.cash = 55000.0
    controller.run_cycle(scan_results=scan_wait, current_time=now_ist + timedelta(minutes=1))
    assert controller.high_water_mark == 55000.0
    state = daemon.load_sentinel_state(db_path)
    assert state["high_water_mark"]["value"] == 55000.0

    # Step 3: Equity drops back to 50,000 on WAIT-only cycle
    controller.session.portfolio.cash = 50000.0
    res = controller.run_cycle(scan_results=scan_wait, current_time=now_ist + timedelta(minutes=2))
    assert controller.high_water_mark == 55000.0
    # (55000 - 50000) / 55000 = 5000 / 55000 = 0.090909...
    assert pytest.approx(res["drawdown_pct"], abs=1e-4) == 0.090909


@pytest.mark.parametrize("manifest, expected_blocked", [
    (None, True),  # missing manifest
    ({"selected_strategy": "WAIT", "risk_multiplier": 1.0}, True),  # WAIT
    ({"selected_strategy": "STRAT_SMA", "risk_multiplier": 0.0}, True),  # risk_mult = 0
    ({"selected_strategy": "STRAT_SMA", "risk_multiplier": float("nan")}, True),  # non-finite multiplier
    ({"selected_strategy": "STRAT_SMA", "risk_multiplier": float("inf")}, True),  # inf multiplier
    ({"selected_strategy": "STRAT_SMA", "risk_multiplier": 1.0, "session_date": "2026-03-30"}, True),  # wrong session
    ({"selected_strategy": "STRAT_SMA", "risk_multiplier": 1.0, "session_date": "2026-04-01"}, False),  # valid
])
def test_wait_or_invalid_allocation_blocks_entries(test_env, manifest, expected_blocked):
    """
    Test 44: Parameterize missing, corrupt, stale, wrong-session manifest,
    selected_strategy=WAIT, risk_multiplier=0, invalid/non-finite multiplier.
    Scanner emits BUY during valid market hours.
    Assert zero BUY proposals/fills.
    Assert protective exits remain available under the documented policy.
    """
    db_path = test_env["db_path"]
    now_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=now_ist, current_equity=50000.0)

    # Existing position with SL to verify protective exits still trigger even when allocation blocks entries
    controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=2,
        price=3500.0,
        stop_loss=3400.0,
    )
    controller.trade_stops["TCS.NS"] = 3400.0
    controller.trade_targets["TCS.NS"] = 3800.0

    # Mock manifest provider
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest)

    # RELIANCE emits BUY; TCS hits stop loss at 3390
    scan_results = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2500.0,
            "high": 2510.0,
            "low": 2490.0,
            "signal": "BUY",
            "stop_loss": 2450.0,
            "target": 2600.0,
            "atr": 20.0,
            "historical_returns": [0.01] * 25,
        },
        "TCS.NS": {
            "symbol": "TCS.NS",
            "status": "OK",
            "price": 3390.0,
            "high": 3410.0,
            "low": 3380.0,
            "signal": "WAIT",
            "atr": 30.0,
            "historical_returns": [0.01] * 25,
        },
    }

    controller.run_cycle(scan_results=scan_results, current_time=now_ist)

    # Protective exit for TCS must ALWAYS execute
    orders = controller.paper_engine.list_orders(controller.session.session_id)
    tcs_sells = [o for o in orders if o.symbol == "TCS.NS" and o.side == OrderSide.SELL]
    assert len(tcs_sells) == 1, "Protective SL exit must remain active"

    # BUY for RELIANCE must be blocked if expected_blocked is True
    reliance_buys = [o for o in orders if o.symbol == "RELIANCE.NS" and o.side == OrderSide.BUY]
    if expected_blocked:
        assert len(reliance_buys) == 0, f"BUY should have been blocked for manifest {manifest}"
    else:
        assert len(reliance_buys) == 1, "BUY should have executed for valid manifest"


def test_preentry_hourly_extreme_cannot_trigger_exit(test_env):
    """
    Test 45: Enter at 10:30 at 100 with target 103.
    At 10:31, provide unchanged 10:00 hourly bar with earlier high 105
    and current price 100.
    Assert no target fill from that pre-entry high.
    """
    db_path = test_env["db_path"]
    t_entry = datetime(2026, 4, 1, 10, 30, tzinfo=daemon.IST_TZ)
    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_entry, current_equity=50000.0)

    # Position entered at 10:30 at 100 with target 103
    controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="ABC.NS",
        side=OrderSide.BUY,
        quantity=10,
        price=100.0,
        stop_loss=97.0,
    )
    controller.trade_stops["ABC.NS"] = 97.0
    controller.trade_targets["ABC.NS"] = 103.0
    controller.trade_entry_times["ABC.NS"] = t_entry

    # At 10:31, scanner provides 10:00 hourly bar with bar_high = 105 (formed before 10:30), but current price = 100
    t_scan = datetime(2026, 4, 1, 10, 31, tzinfo=daemon.IST_TZ)
    scan_results = {
        "ABC.NS": {
            "symbol": "ABC.NS",
            "status": "OK",
            "price": 100.0,
            "high": 105.0,  # Extreme formed prior to 10:30 entry!
            "low": 99.0,
            "bar_timestamp": datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ),
            "signal": "WAIT",
            "atr": 1.0,
        }
    }

    controller.run_cycle(scan_results=scan_results, current_time=t_scan)

    # Assert no target fill / sell order triggered!
    orders = controller.paper_engine.list_orders(controller.session.session_id)
    sell_orders = [o for o in orders if o.symbol == "ABC.NS" and o.side == OrderSide.SELL]
    assert len(sell_orders) == 0, "Pre-entry high (105) must not trigger post-entry target profit exit"


def test_state_storage_failure_blocks_new_entries(test_env):
    """
    Test 46: Inject load/save failures.
    Assert no fresh entry, explicit health/audit failure, and no implicit
    baseline reset enabling trading.
    """
    db_path = test_env["db_path"]
    now_ist = datetime(2026, 4, 1, 10, 0, tzinfo=daemon.IST_TZ)
    controller = daemon.DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=now_ist, current_equity=50000.0)

    # Valid manifest
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value={
        "selected_strategy": "STRAT_SMA",
        "risk_multiplier": 1.0,
        "session_date": "2026-04-01",
    })

    scan_results = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2500.0,
            "high": 2510.0,
            "low": 2490.0,
            "signal": "BUY",
            "stop_loss": 2450.0,
            "target": 2600.0,
            "atr": 20.0,
            "historical_returns": [0.01] * 25,
        }
    }

    # Inject save failure on sentinel state
    with patch("run_live_paper_daemon.save_sentinel_state", side_effect=sqlite3.OperationalError("disk I/O error")):
        cycle_res = controller.run_cycle(scan_results=scan_results, current_time=now_ist)
        assert cycle_res.get("storage_error") is not None
        assert controller.sentinel.is_killswitch_tripped is True, "Storage failure must trip killswitch"

        # Assert no orders were placed
        orders = controller.paper_engine.list_orders(controller.session.session_id)
        assert len(orders) == 0, "State storage failure must block new entries fail-closed"
