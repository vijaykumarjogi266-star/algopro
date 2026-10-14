"""Unit tests for Batch F: Production Configuration, Secret Discipline, and Durable Breaker Recovery (F01 - F09).

Adheres to Non-Negotiable Principles:
- Principle 13: Data validation and security must fail closed.
- Principle 14: Independent risk controls cannot be bypassed.
- Real behavioral testing: zero mocked-success or source-string checks.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
import pytest
from cryptography.fernet import Fernet

from apps.api.core.config import Settings
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.contracts import (
    CircuitBreakerConfig,
    CircuitBreakerTripped,
    GatewayState,
    OrderPayload,
)
from services.backtest_engine.contracts import OrderSide
from run_live_paper_daemon import DaemonController, SessionStatus, IST_TZ


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


def test_f01_production_mode_rejects_insecure_defaults_weak_keys_and_wildcard_cors(temp_dir):
    """F01: Production mode rejects insecure default secrets, weak keys, and wildcard CORS."""
    valid_fernet = Fernet.generate_key().decode()

    # 1. Reject placeholder secrets in production
    with pytest.raises(ValueError, match="known placeholder"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="CHANGE_ME_STRONG_RANDOM_API_KEY",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=["https://app.algolab.com"],
        )

    # 2. Reject short/weak key (< 16 chars)
    with pytest.raises(ValueError, match="minimum length is 16 characters"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="short_key_123",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=["https://app.algolab.com"],
        )

    # 3. Reject low-entropy repetitive key
    with pytest.raises(ValueError, match="repetitive pattern detected"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="aaaaaaaaaaaaaaaa",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=["https://app.algolab.com"],
        )

    # 4. Reject purely numeric key
    with pytest.raises(ValueError, match="purely numeric key is prohibited"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="1234567890123456",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=["https://app.algolab.com"],
        )

    # 5. Reject wildcard CORS in production
    with pytest.raises(ValueError, match="CORS_ORIGINS cannot allow wildcard"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="strong_admin_key_production_7777",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=["*"],
        )

    # 6. Reject empty CORS in production
    with pytest.raises(ValueError, match="CORS_ORIGINS must contain explicit authorized origins"):
        Settings(
            ENVIRONMENT="production",
            ALGO_LAB_API_KEY="strong_admin_key_production_7777",
            CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
            CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
            BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
            CORS_ORIGINS=[],
        )


def test_f02_validated_configuration_succeeds_under_production_environment():
    """F02: Validated configuration succeeds under production environment."""
    valid_fernet = Fernet.generate_key().decode()
    prod_settings = Settings(
        ENVIRONMENT="production",
        ALGO_LAB_API_KEY="strong_admin_key_production_7777",
        CIRCUIT_BREAKER_REARM_SECRET="strong_rearm_secret_prod_9999",
        CIRCUIT_BREAKER_STATE_KEY="strong_state_integrity_key_8888",
        BROKER_CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
        CORS_ORIGINS=["https://app.algolab.com", "https://admin.algolab.com"],
    )
    assert prod_settings.ENVIRONMENT == "production"
    assert prod_settings.ALLOW_LOCAL_AUTH_BYPASS is False
    assert prod_settings.ALLOW_LIVE_TRADING is False

    exported = prod_settings.export_security_settings()
    assert exported["environment"] == "production"
    assert exported["rearm_secret"] == "strong_rearm_secret_prod_9999"


def test_f03_circuit_breaker_trips_into_halt_on_critical_condition(temp_dir):
    """F03: Circuit breaker trips into HALT on persistent critical condition."""
    state_file = os.path.join(temp_dir, "cb_f03.json")
    rearm_sec = "strong_rearm_token_12345"
    state_key = "strong_state_key_12345678"

    engine = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        allow_uninitialized=True,
    )
    assert engine.is_halted is False
    assert engine.state == GatewayState.NORMAL

    # Simulate critical drawdown breach (100k -> 80k: 20% drawdown, threshold is 15%)
    state_after = engine.evaluate_drawdown(80000.0)
    assert state_after == GatewayState.EMERGENCY_HALT
    assert engine.is_halted is True
    assert any("DRAWDOWN_BREACH" in r for r in engine.trip_reasons)
    assert os.path.exists(state_file)

    # Subsequent orders must be rejected
    payload = OrderPayload(
        order_id="ord_f03",
        account_id="acc_01",
        symbol="TCS",
        quantity=10,
        price=3500.0,
        timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(CircuitBreakerTripped, match="EMERGENCY_HALT"):
        engine.validate_order(payload)


def test_f04_restart_without_state_file_preserves_halt_status_when_unverified(temp_dir):
    """F04: Restart without state file preserves halt status when unverified."""
    state_file = os.path.join(temp_dir, "cb_f04_missing.json")
    rearm_sec = "strong_rearm_token_12345"
    state_key = "strong_state_key_12345678"

    # Case 1: require_established_state=True fails closed when file missing
    engine = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        require_established_state=True,
    )
    assert engine.is_halted is True
    assert "MISSING_ESTABLISHED_STATE_FAIL_CLOSED" in engine.trip_reasons

    # Case 2: .failed marker forces halt even if allow_uninitialized
    marker_path = state_file + ".failed"
    with open(marker_path, "w") as mf:
        mf.write("PERSISTENCE_FAILURE: unrecoverable disk crash\n")

    engine2 = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        allow_uninitialized=True,
    )
    assert engine2.is_halted is True
    assert "FAILED_PERSISTENCE_RESTART_BLOCKED" in engine2.trip_reasons


def test_f05_tampered_or_invalid_hmac_on_state_file_triggers_halt(temp_dir):
    """F05: Tampered or invalid HMAC on breaker state file triggers HALT."""
    state_file = os.path.join(temp_dir, "cb_f05_tampered.json")
    state_key = "strong_state_key_12345678"
    rearm_sec = "strong_rearm_token_12345"

    tampered_payload = {
        "schema_version": 1,
        "sequence_id": 1,
        "gateway_state": "EMERGENCY_HALT",
        "trip_reasons": ["CRITICAL_INCIDENT"],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 80000.0,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hmac_digest": "deadbeef0000111122223333444455556666777788889999aaaabbbbccccdddd",
    }
    with open(state_file, "w") as f:
        json.dump(tampered_payload, f)

    engine = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
    )
    assert engine.is_halted is True
    assert "CORRUPTED_DISK_STATE_FAIL_CLOSED" in engine.trip_reasons


def test_f06_replay_of_stale_normal_state_file_is_rejected_by_timestamp_sequence(temp_dir):
    """F06: Replay of stale NORMAL state file is rejected by sequence/timestamp validation."""
    state_file = os.path.join(temp_dir, "cb_f06_replay.json")
    state_key = b"strong_state_key_12345678_bytes!"
    rearm_sec = "strong_rearm_token_12345"

    # Case A: Stale NORMAL state file (2 hours old, max allowed is 3600s)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stale_payload = {
        "schema_version": 1,
        "sequence_id": 1,
        "gateway_state": "NORMAL",
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": stale_ts,
    }
    content = json.dumps(stale_payload, sort_keys=True)
    digest = hmac.new(state_key, content.encode("utf-8"), hashlib.sha256).hexdigest()
    stale_payload["hmac_digest"] = digest

    with open(state_file, "w") as f:
        json.dump(stale_payload, f)

    engine_stale = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
    )
    assert engine_stale.is_halted is True
    assert "STALE_NORMAL_STATE_REPLAY_REJECTED" in engine_stale.trip_reasons

    # Case B: Replay sequence rollback (sequence 2 when expected_min_sequence is 10)
    fresh_ts = datetime.now(timezone.utc).isoformat()
    replayed_seq_payload = {
        "schema_version": 1,
        "sequence_id": 2,
        "gateway_state": "NORMAL",
        "trip_reasons": [],
        "high_water_mark": 100000.0,
        "day_start_equity": 100000.0,
        "current_equity": 100000.0,
        "timestamp_utc": fresh_ts,
    }
    content_seq = json.dumps(replayed_seq_payload, sort_keys=True)
    digest_seq = hmac.new(state_key, content_seq.encode("utf-8"), hashlib.sha256).hexdigest()
    replayed_seq_payload["hmac_digest"] = digest_seq

    with open(state_file, "w") as f:
        json.dump(replayed_seq_payload, f)

    cfg = CircuitBreakerConfig(expected_min_sequence=10)
    engine_seq = CircuitBreakerEngine(
        config=cfg,
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
    )
    assert engine_seq.is_halted is True
    assert "STALE_NORMAL_STATE_REPLAY_REJECTED" in engine_seq.trip_reasons


def test_f07_admin_rearm_with_valid_secret_clears_halt(temp_dir):
    """F07: Admin rearm with valid signature/secret clears HALT and logs authoritative recovery."""
    state_file = os.path.join(temp_dir, "cb_f07.json")
    rearm_sec = "strong_rearm_token_12345"
    state_key = "strong_state_key_12345678"

    engine = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        allow_uninitialized=True,
    )
    engine.trigger_emergency_halt("MANUAL_AUDIT_HALT")
    assert engine.is_halted is True
    assert os.path.exists(state_file)

    # Valid rearm
    rearm_ok = engine.admin_rearm(rearm_sec)
    assert rearm_ok is True
    assert engine.is_halted is False
    assert engine.state == GatewayState.NORMAL
    assert not os.path.exists(state_file)


def test_f08_admin_rearm_with_invalid_credentials_preserves_halt(temp_dir):
    """F08: Admin rearm with invalid credentials preserves HALT."""
    state_file = os.path.join(temp_dir, "cb_f08.json")
    rearm_sec = "strong_rearm_token_12345"
    state_key = "strong_state_key_12345678"

    engine = CircuitBreakerEngine(
        state_file_path=state_file,
        initial_equity=100000.0,
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        allow_uninitialized=True,
    )
    engine.trigger_emergency_halt("TEST_HALT")
    assert engine.is_halted is True

    # Rearm with wrong credentials
    assert engine.admin_rearm("invalid_token_999") is False
    assert engine.is_halted is True
    assert engine.state == GatewayState.EMERGENCY_HALT
    assert os.path.exists(state_file)


def test_f09_recovery_verifies_clean_ledger_state_before_allowing_order_flow(temp_dir):
    """F09: Recovery verifies clean ledger state before allowing order flow."""
    db_path = os.path.join(temp_dir, "daemon_f09.db")
    rearm_sec = "strong_rearm_token_12345"
    state_key = "strong_state_key_12345678"

    cb = CircuitBreakerEngine(
        rearm_secret=rearm_sec,
        state_integrity_key=state_key,
        allow_uninitialized=True,
    )
    controller = DaemonController(
        db_path=db_path,
        initial_capital=100000.0,
        leverage=5.0,
        circuit_breaker=cb,
    )
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    controller.initialize_session(current_time=t_market)

    # Establish an open position
    order, fill = controller.paper_engine.submit_manual_order(
        session_id=controller.session.session_id,
        symbol="TCS.NS",
        side=OrderSide.BUY,
        quantity=5,
        price=3500.0,
        stop_loss=3400.0,
        current_time=t_market,
    )
    assert fill is not None
    controller.session = controller.paper_engine.get_session(controller.session.session_id)

    # Induce an unresolved square-off failure at cutoff
    t_cutoff = datetime(2026, 4, 1, 15, 15, tzinfo=IST_TZ)
    res_cutoff = controller.run_cycle(scan_results={}, current_time=t_cutoff)
    assert res_cutoff["unresolved"] is True
    assert controller.is_halted is True
    assert controller.has_unresolved_square_off is True

    # Attempt to rearm while ledger has unresolved square-off / quarantined position:
    # Must fail closed!
    rearm_failed = controller.admin_rearm(rearm_sec)
    assert rearm_failed is False
    assert controller.is_halted is True

    # Now provide valid quotes to resolve square-off
    valid_quotes = {
        "TCS.NS": {
            "symbol": "TCS.NS",
            "status": "OK",
            "price": 3520.0,
            "bar_timestamp": datetime(2026, 4, 1, 15, 20, tzinfo=IST_TZ),
        }
    }
    res_resolve = controller.run_cycle(scan_results=valid_quotes, current_time=datetime(2026, 4, 1, 15, 20, tzinfo=IST_TZ))
    assert res_resolve["status"] == "SQUARE_OFF_COMPLETED"
    assert controller.has_unresolved_square_off is False

    # Now that the ledger is verified clean and settled, admin rearm succeeds!
    rearm_success = controller.admin_rearm(rearm_sec)
    assert rearm_success is True
    assert controller.is_halted is False
    assert controller.session.status == SessionStatus.RUNNING
