"""Unit tests for complete durable breaker recovery (Section 8).

Regressions covered:
- R44: test_failed_halt_persistence_then_restart_is_blocked
- R45: test_missing_established_state_requires_explicit_recovery
- R46: test_directory_fsync_failure_propagates
- R47: test_signed_nonfinite_equity_is_rejected
- R48: test_successful_recovery_clears_only_resolved_errors
"""

import hashlib
import hmac
import json
import math
import os
from unittest.mock import patch
import pytest

from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import CircuitBreakerConfig, OrderPayload


REARM_SECRET = "super_secret_rearm_token_final_test"
INTEGRITY_KEY = b"final_state_integrity_key_32bytes"


def _make_signed_state(payload: dict, key: bytes = INTEGRITY_KEY) -> dict:
    content = json.dumps(payload, sort_keys=True)
    digest = hmac.new(key, content.encode("utf-8"), hashlib.sha256).hexdigest()
    signed = dict(payload)
    signed["hmac_digest"] = digest
    return signed


def _write_state_file(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def test_failed_halt_persistence_then_restart_is_blocked(tmp_path):
    """R44: Failed halt persistence must write durable marker so subsequent restart is blocked from NORMAL."""
    state_file = str(tmp_path / "cb_state.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
        allow_uninitialized=True,
    )

    # Incur halt while injecting persistence failure (e.g. disk write / replace fails)
    with patch("os.replace", side_effect=OSError("Disk write I/O failure")):
        engine.trigger_emergency_halt("TEST_FAILED_PERSIST_HALT")
        assert engine.is_halted is True
        assert engine._persistence_error is not None

    # Verify failure marker was created
    marker_path = state_file + ".failed"
    assert os.path.exists(marker_path), "Persistence failure marker must exist on disk"

    # Simulate process restart
    restarted_engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
        allow_uninitialized=True,
    )

    # Breaker MUST be blocked from NORMAL on restart
    assert restarted_engine.is_halted is True
    assert restarted_engine.state == GatewayState.EMERGENCY_HALT
    assert "FAILED_PERSISTENCE_RESTART_BLOCKED" in restarted_engine.trip_reasons


def test_missing_established_state_requires_explicit_recovery(tmp_path):
    """R45: In production (or when require_established_state=True), missing state fails closed and requires explicit rearm."""
    state_file = str(tmp_path / "cb_missing.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
        require_established_state=True,
    )

    # Assert file does not exist initially
    assert not os.path.exists(state_file)

    engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
        env="production",
    )

    # Must fail closed to EMERGENCY_HALT
    assert engine.is_halted is True
    assert engine.state == GatewayState.EMERGENCY_HALT
    assert "MISSING_ESTABLISHED_STATE_FAIL_CLOSED" in engine.trip_reasons

    # Explicit recovery via admin_rearm restores NORMAL
    rearmed = engine.admin_rearm(REARM_SECRET)
    assert rearmed is True
    assert engine.is_halted is False
    assert engine.state == GatewayState.NORMAL


def test_directory_fsync_failure_propagates(tmp_path):
    """R46: Directory fsync failures must propagate as failure and not be swallowed."""
    state_file = str(tmp_path / "cb_fsync.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
        allow_uninitialized=True,
    )

    # 1. Test direct sync_directory failure propagation
    with patch("os.fsync", side_effect=OSError(5, "I/O error during directory fsync")):
        with pytest.raises(OSError) as exc_info:
            engine.sync_directory(str(tmp_path))
        assert "I/O error during directory fsync" in str(exc_info.value)

    # 2. Halt the engine cleanly
    engine.trigger_emergency_halt("HALT_FOR_FSYNC_TEST")
    assert engine.is_halted is True
    assert os.path.exists(state_file)

    # 3. Test _clear_disk_state propagation during directory fsync failure
    with patch("os.fsync", side_effect=OSError(5, "Directory fsync failed on clearance")):
        with pytest.raises(OSError) as exc_info:
            engine._clear_disk_state()
        assert "Directory fsync failed on clearance" in str(exc_info.value)

    # Re-persist halt state file so state file is present for rearm clearance
    engine._persist_disk_state()
    assert os.path.exists(state_file)

    # 4. admin_rearm must capture clearance failure, preserve halt, and return False
    with patch("os.fsync", side_effect=OSError(5, "Directory fsync failed on rearm")):
        success = engine.admin_rearm(REARM_SECRET)
        assert success is False
        assert engine.is_halted is True


@pytest.mark.parametrize("corrupt_key,corrupt_val", [
    ("current_equity", float("nan")),
    ("current_equity", float("inf")),
    ("current_equity", -500.0),
    ("current_equity", 0.0),
    ("high_water_mark", float("nan")),
    ("high_water_mark", -100.0),
    ("day_start_equity", float("inf")),
    ("day_start_equity", -1.0),
    ("inconsistent_hwm", 50_000.0),  # HWM (50,000) < Current (100,000)
])
def test_signed_nonfinite_equity_is_rejected(tmp_path, corrupt_key, corrupt_val):
    """R47: Signed states containing nonfinite or non-positive equity, or inconsistent HWM, fail closed."""
    state_file = str(tmp_path / f"cb_corrupt_{corrupt_key}.json")
    payload = {
        "schema_version": 1,
        "gateway_state": GatewayState.EMERGENCY_HALT.value,
        "trip_reasons": ["ORIGINAL_HALT"],
        "high_water_mark": 100_000.0,
        "day_start_equity": 100_000.0,
        "current_equity": 100_000.0,
        "timestamp_utc": "2026-01-01T00:00:00Z",
    }
    if corrupt_key == "inconsistent_hwm":
        payload["high_water_mark"] = corrupt_val
        payload["current_equity"] = 100_000.0
    else:
        payload[corrupt_key] = corrupt_val

    # Sign with valid integrity key
    signed = _make_signed_state(payload)
    _write_state_file(state_file, signed)

    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
    )

    # Must fail closed to EMERGENCY_HALT and record corrupted state reason
    assert engine.is_halted is True
    assert engine.state == GatewayState.EMERGENCY_HALT
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in engine.trip_reasons


def test_successful_recovery_clears_only_resolved_errors(tmp_path):
    """R48: Clear stale persistence errors only after verified recovery; failed rearm preserves errors."""
    state_file = str(tmp_path / "cb_errors.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    engine = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100_000.0,
        allow_uninitialized=True,
    )

    # Trigger halt with persistence failure
    with patch("os.replace", side_effect=OSError("Injected persistence error")):
        engine.trigger_emergency_halt("TEST_ERROR_HALT")
        assert engine.is_halted is True
        assert engine._persistence_error == "Injected persistence error"

    # Rearm attempt with invalid token fails and preserves persistence error
    failed_rearm = engine.admin_rearm("wrong_rearm_token")
    assert failed_rearm is False
    assert engine.is_halted is True
    assert engine._persistence_error == "Injected persistence error"

    # Rearm attempt with filesystem I/O error fails and preserves/updates persistence error
    with patch("os.remove", side_effect=OSError("Read-only filesystem on unlink")):
        failed_rearm_io = engine.admin_rearm(REARM_SECRET)
        assert failed_rearm_io is False
        assert engine.is_halted is True
        assert engine._persistence_error is not None

    # Verified clean rearm clears all persistence errors and trip reasons
    success = engine.admin_rearm(REARM_SECRET)
    assert success is True
    assert engine.is_halted is False
    assert engine.state == GatewayState.NORMAL
    assert engine._persistence_error is None
    assert len(engine.trip_reasons) == 0
