import os
import tempfile
import pytest
from run_live_paper_daemon import compute_risk_state, _load_sentinel_state, _save_sentinel_state


def test_compute_risk_state_daily_loss():
    # Day start = 100k, Current = 97k (3% loss)
    res = compute_risk_state(day_start_equity=100000.0, high_water_mark=100000.0, current_equity=97000.0)
    assert pytest.approx(res["daily_loss_pct"], rel=1e-4) == 0.03
    assert pytest.approx(res["drawdown_pct"], rel=1e-4) == 0.03
    assert res["new_high_water_mark"] == 100000.0


def test_compute_risk_state_drawdown_from_hwm():
    # Day start = 100k, HWM = 120k, Current = 108k (10% drawdown from HWM, but +8% gain for the day)
    res = compute_risk_state(day_start_equity=100000.0, high_water_mark=120000.0, current_equity=108000.0)
    assert res["daily_loss_pct"] == 0.0
    assert pytest.approx(res["drawdown_pct"], rel=1e-4) == 0.10
    assert res["new_high_water_mark"] == 120000.0


def test_monotonic_high_water_mark():
    # Equity rallies to new peak
    res = compute_risk_state(day_start_equity=100000.0, high_water_mark=105000.0, current_equity=110000.0)
    assert res["new_high_water_mark"] == 110000.0
    assert res["drawdown_pct"] == 0.0
    assert res["daily_loss_pct"] == 0.0


def test_sentinel_state_persistence_across_restarts():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        _save_sentinel_state(db_path, "day_start_equity", 50000.0)
        _save_sentinel_state(db_path, "high_water_mark", 55000.0)

        # Reload state as if fresh process startup
        loaded = _load_sentinel_state(db_path)
        assert loaded["day_start_equity"]["value"] == 50000.0
        assert loaded["high_water_mark"]["value"] == 55000.0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
