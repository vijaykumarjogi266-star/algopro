"""Unit tests for circuit breaker state integrity, schema validation, and fail-closed behavior.

Tests:
15. test_unsigned_or_invalid_existing_state_fails_closed
16. test_signed_but_invalid_schema_fails_closed
17. test_rearm_verifier_cannot_sign_persisted_state
"""

import hmac
import hashlib
import json
import os
import tempfile
import pytest

from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import CircuitBreakerConfig


def _sign_document(doc: dict, key: bytes) -> dict:
    """Helper to sign a document dict with HMAC-SHA256."""
    copied = dict(doc)
    copied.pop("hmac_digest", None)
    content = json.dumps(copied, sort_keys=True)
    digest = hmac.new(key, content.encode("utf-8"), hashlib.sha256).hexdigest()
    copied["hmac_digest"] = digest
    return copied


@pytest.mark.parametrize("replacement_doc", [
    {},
    {"gateway_state": "NORMAL", "trip_reasons": []},
    {"gateway_state": "BOGUS"},
    {"gateway_state": "EMERGENCY_HALT", "trip_reasons": ["untrusted"]},
])
def test_unsigned_or_invalid_existing_state_fails_closed(replacement_doc):
    """Test 15: Create an authentic halt, replace with unsigned/bogus document, restart.
    Must fail closed to EMERGENCY_HALT with corruption/tamper reason, not trusting attacker reasons.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "cb_state.json")
        integrity_key = b"test_integrity_key_32_bytes_long_123"

        config = CircuitBreakerConfig(
            rearm_secret="test_rearm_secret_12345",
            state_integrity_key=integrity_key.decode("latin1"),
        )
        engine = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)

        # Trip to EMERGENCY_HALT and persist
        engine.evaluate_drawdown(80_000.0)
        assert engine.is_halted
        assert os.path.exists(state_file)

        # Tamper: replace state file with unsigned / bogus document
        with open(state_file, "w") as f:
            json.dump(replacement_doc, f)

        # Restart with original configuration
        restarted = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)
        assert restarted.is_halted, "Must fail closed to EMERGENCY_HALT on unsigned/invalid state."
        assert any("CORRUPT" in r or "TAMPER" in r for r in restarted.trip_reasons)
        assert "untrusted" not in restarted.trip_reasons


@pytest.mark.parametrize("invalid_schema_doc", [
    {"schema_version": 999, "gateway_state": "NORMAL", "trip_reasons": []},
    {"schema_version": 1, "gateway_state": "INVALID_ENUM", "trip_reasons": []},
    {"schema_version": 1, "gateway_state": "EMERGENCY_HALT"},  # missing trip_reasons
    {"schema_version": 1, "gateway_state": "EMERGENCY_HALT", "trip_reasons": "not_a_list"},
])
def test_signed_but_invalid_schema_fails_closed(invalid_schema_doc):
    """Test 16: Documents signed with valid integrity key but violating schema must fail closed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "cb_state.json")
        integrity_key = b"test_integrity_key_32_bytes_long_123"

        # Sign the invalid document with legitimate key
        signed = _sign_document(invalid_schema_doc, integrity_key)
        with open(state_file, "w") as f:
            json.dump(signed, f)

        config = CircuitBreakerConfig(
            rearm_secret="test_rearm_secret_12345",
            state_integrity_key=integrity_key.decode("latin1"),
        )
        restarted = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)
        assert restarted.is_halted, "Must fail closed to EMERGENCY_HALT on schema violation."
        assert any("CORRUPT" in r or "TAMPER" in r or "SCHEMA" in r for r in restarted.trip_reasons)


def test_rearm_verifier_cannot_sign_persisted_state():
    """Test 17: Rearm verifier cannot sign persisted state; separate integrity key must be enforced.
    Forging NORMAL using rearm verifier must be detected and rejected on restart.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "cb_state.json")
        rearm_secret = "independent_rearm_secret_token"
        rearm_verifier = hashlib.sha256(rearm_secret.encode()).digest()
        integrity_key = b"independent_integrity_signing_key_999"

        config = CircuitBreakerConfig(
            rearm_secret=rearm_secret,
            state_integrity_key=integrity_key.decode("latin1"),
        )
        engine = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)
        engine.evaluate_drawdown(80_000.0)
        assert engine.is_halted

        # Attacker tries to forge NORMAL state using rearm verifier bytes as HMAC key
        forged_doc = {
            "schema_version": 1,
            "gateway_state": "NORMAL",
            "trip_reasons": [],
            "high_water_mark": 100_000.0,
            "day_start_equity": 100_000.0,
            "current_equity": 100_000.0,
        }
        forged_signed = _sign_document(forged_doc, rearm_verifier)
        with open(state_file, "w") as f:
            json.dump(forged_signed, f)

        # Restart
        restarted = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100_000.0)
        assert restarted.is_halted, "Forged state using rearm verifier must fail closed."
        assert any("TAMPER" in r or "CORRUPT" in r for r in restarted.trip_reasons)
