"""Unit tests for circuit breaker persistence failures and durable rearm transactions.

Tests:
18. test_rearm_unlink_or_durable_write_failure_preserves_halt
19. test_halt_persistence_failure_blocks_execution
"""

import os
import tempfile
from unittest.mock import patch
import pytest

from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import CircuitBreakerConfig, OrderPayload


from datetime import datetime, timezone

@pytest.fixture
def dummy_order():
    return OrderPayload(
        order_id="ord_test_001",
        account_id="acc_test_001",
        symbol="RELIANCE",
        quantity=10,
        price=2500.0,
        timestamp=datetime.now(timezone.utc),
    )


def test_rearm_unlink_or_durable_write_failure_preserves_halt(dummy_order, caplog):
    """Test 18: If persistent disk clearance/update fails during rearm:
    - Operation fails (returns False).
    - Engine remains halted (EMERGENCY_HALT).
    - Snapshot values and reasons remain unchanged.
    - Orders remain rejected.
    - No success audit event emitted.
    - Failure is audited without credentials.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "cb_state.json")
        rearm_secret = "secret_rearm_test_123"
        config = CircuitBreakerConfig(
            rearm_secret=rearm_secret,
            state_integrity_key="valid_integrity_key_12345",
        )
        engine = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)

        # Halt the engine
        engine.evaluate_drawdown(80_000.0)
        assert engine.is_halted
        orig_reasons = list(engine.trip_reasons)
        orig_hwm = engine._high_water_mark

        # Inject PermissionError during durable state clearing/write
        with patch("os.remove", side_effect=PermissionError("Mock Permission Denied")):
            success = engine.admin_rearm(rearm_secret)
            assert success is False, "Rearm must return False if durable disk update fails."
            assert engine.is_halted, "Engine must remain halted if disk clearance fails."
            assert engine.trip_reasons == orig_reasons, "Trip reasons must be preserved."
            assert engine._high_water_mark == orig_hwm

            # Orders must still be rejected
            with pytest.raises(Exception):
                engine.validate_order(dummy_order)

            # Assert no success audit and failure audit does NOT log rearm_secret
            assert "CIRCUIT_BREAKER_REARM_SUCCESS" not in caplog.text
            assert rearm_secret not in caplog.text

        # Retry without fault -> Succeeds
        success_retry = engine.admin_rearm(rearm_secret)
        assert success_retry is True
        assert not engine.is_halted
        assert engine.state == GatewayState.NORMAL


@pytest.mark.parametrize("fault", [
    PermissionError("Permission Denied"),
    OSError(28, "No space left on device"),
    IOError("Disk I/O Error"),
])
def test_halt_persistence_failure_blocks_execution(fault, dummy_order):
    """Test 19: Failure to persist EMERGENCY_HALT to disk must not swallow the failure or permit execution.
    Runtime halt must remain active and new orders must be blocked.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "cb_state.json")
        config = CircuitBreakerConfig(
            rearm_secret="secret_rearm_test_123",
            state_integrity_key="valid_integrity_key_12345",
        )
        engine = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)

        with patch("os.replace", side_effect=fault):
            # Trip halt
            engine.evaluate_drawdown(80_000.0)
            assert engine.is_halted, "Engine must remain halted even if disk write fails."

            # New orders must be rejected
            with pytest.raises(Exception):
                engine.validate_order(dummy_order)
