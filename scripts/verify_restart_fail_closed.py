import os
import sys
import tempfile
import json
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.contracts import CircuitBreakerConfig, GatewayState


def verify_restart_fail_closed():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_file = tf.name

    try:
        config = CircuitBreakerConfig(
            rearm_secret="REARM_SECRET_KEY_12345",
        )
        # Instance 1: Trip emergency halt and persist to state_file
        engine1 = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100000.0)
        engine1.trigger_emergency_halt("UNIT_TEST_TRIGGERED_HALT")
        assert engine1.is_halted is True

        # Instance 2 (Simulating process crash & restart): Should recover into EMERGENCY_HALT
        engine2 = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100000.0)
        if not engine2.is_halted:
            print("[FAIL] CircuitBreaker did not recover into EMERGENCY_HALT after restart!")
            sys.exit(1)

        # Instance 3 (Simulating malicious file tampering): Should detect HMAC mismatch and fail-closed
        with open(state_file, "r") as f:
            data = json.load(f)
        data["gateway_state"] = "NORMAL"  # Tamper with state
        with open(state_file, "w") as f:
            json.dump(data, f)

        engine3 = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100000.0)
        if not engine3.is_halted:
            print("[FAIL] CircuitBreaker allowed tampered file to bypass EMERGENCY_HALT!")
            sys.exit(1)

        print("[PASS] Verified: Circuit breaker restart recovery preserves active halt and fails closed on tampering.")
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)


if __name__ == "__main__":
    verify_restart_fail_closed()
