"""Unit tests for Manifest Freshness, Provenance, and Replay Protection (R38–R43).

Tests:
R38: test_current_session_but_expired_generation_yields_wait
R39: test_future_or_naive_timestamp_yields_wait
R40: test_missing_or_wrong_target_session_yields_wait
R41: test_multiplier_validation
R42: test_replayed_decision_is_not_reapplied_unsafely
R43: test_valid_manifest_executes_selected_strategy
"""

import os
import json
import math
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from run_live_paper_daemon import (
    DaemonController,
    validate_manifest,
    DaemonPhase,
    IST_TZ,
)
import services.paper_engine.autonomous_orchestrator as orch
from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
from services.backtest_engine.contracts import OrderSide


@pytest.fixture
def manifest_env(tmp_path):
    db_path = str(tmp_path / "manifest_test.db")
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    return {
        "db_path": db_path,
        "decisions_dir": str(decisions_dir),
        "tmp_path": tmp_path,
    }


def _create_sample_manifest(
    current_date: str,
    gen_time: datetime,
    strat: str = "STRAT_EMA_MOMENTUM",
    risk_mult: float = 1.0,
    dec_id: str = "dec_test_001",
    tz_aware: bool = True,
) -> dict:
    ts_str = gen_time.isoformat() if tz_aware else gen_time.strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "schema_version": "1.0.0",
        "decision_id": dec_id,
        "generated_at_utc": ts_str,
        "target_session_date": current_date,
        "selected_strategy": strat,
        "parameters": {"stop_loss_atr": 1.5, "target_atr": 3.0},
        "risk_multiplier": risk_mult,
        "dataset_id": "NSE_DAILY_2026",
        "dataset_checksum": "sha256_mock_abc123",
        "code_version": "1.0.0",
    }


def test_current_session_but_expired_generation_yields_wait(manifest_env):
    """R38: Manifest matching current session date but expired generation timestamp (>24h) yields WAIT."""
    current_date = "2026-04-01"
    now_utc = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    expired_time = now_utc - timedelta(hours=25)  # 25h old

    manifest = _create_sample_manifest(current_date, expired_time)

    # 1. Direct validation rejects expired generation
    is_ok, err = validate_manifest(manifest, current_date, now_dt=now_utc)
    assert is_ok is False
    assert "expired" in err.lower() or "stale" in err.lower()

    # 2. Sentinel reader fail-closed emits WAIT
    decisions_dir = manifest_env["decisions_dir"]
    with patch.object(orch, "PROJECT_ROOT", str(manifest_env["tmp_path"])):
        mpath = os.path.join(decisions_dir, "decision_20260401.json")
        with open(mpath, "w") as f:
            json.dump(manifest, f)

        sentinel = AutonomousSentinel(db_path=manifest_env["db_path"])
        decision = sentinel.get_latest_strategy_decision(current_ist_date=current_date)
        assert decision["selected_strategy"] == "WAIT"
        assert decision["risk_multiplier"] == 0.0


def test_future_or_naive_timestamp_yields_wait(manifest_env):
    """R39: Timezone-naive or future generation timestamp yields WAIT."""
    current_date = "2026-04-01"
    now_utc = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

    # Case 1: Timezone-naive timestamp
    naive_dt = datetime(2026, 4, 1, 9, 30)  # No tzinfo
    manifest_naive = _create_sample_manifest(current_date, naive_dt, tz_aware=False)
    is_ok_naive, err_naive = validate_manifest(manifest_naive, current_date, now_dt=now_utc)
    assert is_ok_naive is False
    assert "naive" in err_naive.lower() or "timezone-aware" in err_naive.lower()

    # Case 2: Future timestamp (> 5 minutes into the future)
    future_dt = now_utc + timedelta(hours=2)
    manifest_future = _create_sample_manifest(current_date, future_dt, tz_aware=True)
    is_ok_future, err_future = validate_manifest(manifest_future, current_date, now_dt=now_utc)
    assert is_ok_future is False
    assert "future" in err_future.lower()

    # Case 3: Sentinel emits WAIT for naive or future manifests
    decisions_dir = manifest_env["decisions_dir"]
    with patch.object(orch, "PROJECT_ROOT", str(manifest_env["tmp_path"])):
        mpath = os.path.join(decisions_dir, "decision_future.json")
        with open(mpath, "w") as f:
            json.dump(manifest_future, f)

        sentinel = AutonomousSentinel(db_path=manifest_env["db_path"])
        dec = sentinel.get_latest_strategy_decision(current_ist_date=current_date)
        assert dec["selected_strategy"] == "WAIT"
        assert dec["risk_multiplier"] == 0.0


def test_missing_or_wrong_target_session_yields_wait(manifest_env):
    """R40: Missing or mismatched target_session_date yields WAIT."""
    current_date = "2026-04-01"
    now_utc = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

    # Case 1: Wrong target session date (yesterday)
    manifest_wrong_date = _create_sample_manifest("2026-03-31", now_utc)
    is_ok, err = validate_manifest(manifest_wrong_date, current_date, now_dt=now_utc)
    assert is_ok is False
    assert "does not match current session" in err

    # Case 2: Missing target session date
    manifest_no_date = _create_sample_manifest(current_date, now_utc)
    del manifest_no_date["target_session_date"]
    is_ok2, err2 = validate_manifest(manifest_no_date, current_date, now_dt=now_utc)
    assert is_ok2 is False

    # Sentinel verification
    decisions_dir = manifest_env["decisions_dir"]
    with patch.object(orch, "PROJECT_ROOT", str(manifest_env["tmp_path"])):
        mpath = os.path.join(decisions_dir, "decision_wrong.json")
        with open(mpath, "w") as f:
            json.dump(manifest_wrong_date, f)

        sentinel = AutonomousSentinel(db_path=manifest_env["db_path"])
        dec = sentinel.get_latest_strategy_decision(current_ist_date=current_date)
        assert dec["selected_strategy"] == "WAIT"
        assert dec["risk_multiplier"] == 0.0


def test_multiplier_validation():
    """R41: Risk multiplier must be finite, non-negative, and bounded (<= 5.0)."""
    current_date = "2026-04-01"
    now_utc = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

    # Negative multiplier
    m_neg = _create_sample_manifest(current_date, now_utc, risk_mult=-1.0)
    assert validate_manifest(m_neg, current_date, now_dt=now_utc)[0] is False

    # Zero multiplier
    m_zero = _create_sample_manifest(current_date, now_utc, risk_mult=0.0)
    assert validate_manifest(m_zero, current_date, now_dt=now_utc)[0] is False

    # NaN / Inf multiplier
    m_nan = _create_sample_manifest(current_date, now_utc, risk_mult=float("nan"))
    assert validate_manifest(m_nan, current_date, now_dt=now_utc)[0] is False
    m_inf = _create_sample_manifest(current_date, now_utc, risk_mult=float("inf"))
    assert validate_manifest(m_inf, current_date, now_dt=now_utc)[0] is False

    # Unbounded excessive multiplier (> 5.0)
    m_huge = _create_sample_manifest(current_date, now_utc, risk_mult=10.0)
    assert validate_manifest(m_huge, current_date, now_dt=now_utc)[0] is False

    # Valid bounded multipliers
    for valid_rm in [0.5, 1.0, 2.0, 5.0]:
        m_valid = _create_sample_manifest(current_date, now_utc, risk_mult=valid_rm)
        assert validate_manifest(m_valid, current_date, now_dt=now_utc)[0] is True


def test_replayed_decision_is_not_reapplied_unsafely(manifest_env):
    """R42: Replayed decision_id is not reapplied unsafely; duplicate order execution is prevented."""
    db_path = manifest_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    # Valid manifest with specific decision_id
    manifest = _create_sample_manifest(current_date, t_market, dec_id="dec_unique_101")
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest)

    scan_buy = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2000.0,
            "stop_loss": 1960.0,
            "target": 2080.0,
            "signal": "BUY",
            "atr": 20.0,
            "historical_returns": [0.01] * 25,
        }
    }

    # Cycle 1: Executes BUY order under this decision_id
    res1 = controller.run_cycle(scan_results=scan_buy, current_time=t_market)
    assert res1["status"] == "OK"
    assert "dec_unique_101" in controller.processed_decision_ids
    assert len(controller.session.orders) == 1

    # Cycle 2: Replay exact same decision_id -> must NOT submit duplicate BUY order
    res2 = controller.run_cycle(scan_results=scan_buy, current_time=t_market + timedelta(minutes=1))
    assert res2["status"] == "OK"
    assert len(controller.session.orders) == 1  # Still 1 order, duplicate suppressed!


def test_valid_manifest_executes_selected_strategy(manifest_env):
    """R43: Valid manifest driving selected strategy and parameters executes order under that strategy."""
    db_path = manifest_env["db_path"]
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    selected_strat = "STRAT_DONCHIAN_BREAKOUT"
    manifest = _create_sample_manifest(
        current_date,
        t_market,
        strat=selected_strat,
        risk_mult=1.5,
        dec_id="dec_strat_exec_43",
    )
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest)

    scan_buy = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 1500.0,
            "stop_loss": 1470.0,
            "target": 1560.0,
            "signal": "BUY",
            "atr": 15.0,
            "historical_returns": [0.01] * 25,
        }
    }

    res = controller.run_cycle(scan_results=scan_buy, current_time=t_market)
    assert res["status"] == "OK"
    assert len(controller.session.orders) == 1
    # Verify session strategy was updated to the allocated strategy
    assert controller.session.strategy_id == selected_strat
    assert "INFY.NS" in controller.session.portfolio.positions
