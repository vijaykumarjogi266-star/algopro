"""Unit tests for durable circuit breaker state persistence, MAC verification, and recovery (T13–T19).

Tests:
T13: test_state_file_schema_version_enforced
T14: test_hmac_tampering_fails_closed
T15: test_unkeyed_checksum_rejected
T16: test_fsync_data_and_directory
T17: test_rearm_clears_state_atomically
T18: test_uninitialized_vs_corrupted_state
T19: test_state_integrity_key_independent_from_rearm_secret
"""

import hashlib
import hmac
import json
import os
from unittest.mock import patch
import pytest

from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import CircuitBreakerConfig


INTEGRITY_KEY = b"test_dedicated_state_key_32bytes!"
REARM_SECRET = "super_secret_admin_rearm_token"


def _make_signed_state(payload: dict, key: bytes = INTEGRITY_KEY) -> dict:
    """Helper creating state dictionary signed with HMAC-SHA256."""
    content = json.dumps(payload, sort_keys=True)
    digest = hmac.new(key, content.encode("utf-8"), hashlib.sha256).hexdigest()
    signed = dict(payload)
    signed["hmac_digest"] = digest
    return signed


def _write_state_file(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def test_state_file_schema_version_enforced(tmp_path):
    """T13: Unsupported state file schema versions fail-closed to EMERGENCY_HALT."""
    state_file = str(tmp_path / "cb_schema.json")
    payload = {
        "schema_version": 99,  # Unsupported schema version
        "gateway_state": GatewayState.NORMAL.value,
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": "2026-01-01T00:00:00Z",
    }
    _write_state_file(state_file, _make_signed_state(payload))

    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)

    # Must fail closed to EMERGENCY_HALT
    assert cb.state == GatewayState.EMERGENCY_HALT
    assert cb.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb.trip_reasons


def test_hmac_tampering_fails_closed(tmp_path):
    """T14: Modifying state payload or HMAC fails-closed to EMERGENCY_HALT."""
    state_file = str(tmp_path / "cb_tamper.json")
    payload = {
        "schema_version": 1,
        "gateway_state": GatewayState.NORMAL.value,
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": "2026-01-01T00:00:00Z",
    }
    signed = _make_signed_state(payload)
    # Tamper with current equity without updating HMAC
    signed["current_equity"] = 999999.0
    _write_state_file(state_file, signed)

    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)

    assert cb.state == GatewayState.EMERGENCY_HALT
    assert cb.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb.trip_reasons


def test_unkeyed_checksum_rejected(tmp_path):
    """T15: State without keyed HMAC (or with unkeyed SHA-256) fails closed."""
    state_file = str(tmp_path / "cb_unkeyed.json")
    payload = {
        "schema_version": 1,
        "gateway_state": GatewayState.NORMAL.value,
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": "2026-01-01T00:00:00Z",
    }
    # Unkeyed raw SHA-256 instead of HMAC
    content = json.dumps(payload, sort_keys=True)
    payload["sha256_checksum"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _write_state_file(state_file, payload)

    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)

    # Missing hmac_digest must fail closed
    assert cb.state == GatewayState.EMERGENCY_HALT
    assert cb.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb.trip_reasons


def test_fsync_data_and_directory(tmp_path):
    """T16: State persistence calls os.fsync on both data file and parent directory."""
    state_file = str(tmp_path / "cb_fsync.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)

    fsync_count = 0
    original_fsync = os.fsync

    def counting_fsync(fd):
        nonlocal fsync_count
        fsync_count += 1
        return original_fsync(fd)

    with patch("os.fsync", side_effect=counting_fsync):
        cb.trigger_emergency_halt("FSYNC_TEST_HALT")

    # Both the temporary file descriptor and directory descriptor were fsynced
    assert fsync_count >= 2, f"Expected at least 2 fsync calls (data + dir), got {fsync_count}"
    assert os.path.exists(state_file)


def test_rearm_clears_state_atomically(tmp_path):
    """T17: Rearm fails closed if durable state clearance fails, preserving halt and baseline."""
    state_file = str(tmp_path / "cb_atomic_clear.json")
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)
    cb.trigger_emergency_halt("TEST_PERSISTED_HALT")
    assert cb.is_halted is True
    assert os.path.exists(state_file)

    # Simulate filesystem I/O error during unlink
    with patch("os.remove", side_effect=OSError("Read-only filesystem")):
        rearmed = cb.admin_rearm(REARM_SECRET)
        assert rearmed is False
        # Breaker MUST remain halted
        assert cb.is_halted is True
        assert cb.state == GatewayState.EMERGENCY_HALT
        assert "TEST_PERSISTED_HALT" in cb.trip_reasons

    # Normal rearm should now succeed
    rearmed_ok = cb.admin_rearm(REARM_SECRET)
    assert rearmed_ok is True
    assert cb.is_halted is False
    assert cb.state == GatewayState.NORMAL
    assert not os.path.exists(state_file)


def test_uninitialized_vs_corrupted_state(tmp_path):
    """T18: Missing file is uninitialized (NORMAL); corrupt/empty file fails closed (EMERGENCY_HALT)."""
    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )

    # Case A: Uninitialized (file does not exist) -> NORMAL
    nonexistent_path = str(tmp_path / "cb_nonexistent.json")
    cb_clean = CircuitBreakerEngine(config=cfg, state_file_path=nonexistent_path, initial_equity=100000.0)
    assert cb_clean.state == GatewayState.NORMAL
    assert cb_clean.is_halted is False
    assert len(cb_clean.trip_reasons) == 0

    # Case B1: Corrupted (0 bytes empty file) -> EMERGENCY_HALT
    empty_path = str(tmp_path / "cb_empty.json")
    with open(empty_path, "w") as f:
        pass  # 0 bytes
    cb_empty = CircuitBreakerEngine(config=cfg, state_file_path=empty_path, initial_equity=100000.0)
    assert cb_empty.state == GatewayState.EMERGENCY_HALT
    assert cb_empty.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb_empty.trip_reasons

    # Case B2: Corrupted (malformed JSON) -> EMERGENCY_HALT
    malformed_path = str(tmp_path / "cb_bad_json.json")
    with open(malformed_path, "w") as f:
        f.write("{this is not valid json")
    cb_bad_json = CircuitBreakerEngine(config=cfg, state_file_path=malformed_path, initial_equity=100000.0)
    assert cb_bad_json.state == GatewayState.EMERGENCY_HALT
    assert cb_bad_json.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb_bad_json.trip_reasons


def test_state_integrity_key_independent_from_rearm_secret(tmp_path):
    """T19: Signing state with rearm secret instead of state integrity key is rejected."""
    state_file = str(tmp_path / "cb_wrong_key.json")
    payload = {
        "schema_version": 1,
        "gateway_state": GatewayState.NORMAL.value,
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": "2026-01-01T00:00:00Z",
    }
    # Adversary signs state with REARM_SECRET instead of INTEGRITY_KEY
    fake_signed = _make_signed_state(payload, key=REARM_SECRET.encode("utf-8"))
    _write_state_file(state_file, fake_signed)

    cfg = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key=INTEGRITY_KEY.decode("latin1"),
    )
    cb = CircuitBreakerEngine(config=cfg, state_file_path=state_file, initial_equity=100000.0)

    # HMAC verification must fail, causing engine to fail closed
    assert cb.state == GatewayState.EMERGENCY_HALT
    assert cb.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in cb.trip_reasons
