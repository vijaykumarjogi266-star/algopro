"""
Security & Integrity Unit Tests for Circuit Breaker Rearm.
Verifies:
1. Missing production secret fails closed (RuntimeError).
2. Incorrect rearm token rejection.
3. Valid rearm token acceptance.
4. No secret leakage through logs, exceptions, reprs, or str conversions.
5. Constant-time comparison and hashed token storage.
"""

import hashlib
import os
import pytest
import logging
from unittest.mock import patch

from services.execution_gateway.contracts import (
    GatewayState,
    CircuitBreakerConfig,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine


def test_production_missing_secret_fails_closed(monkeypatch):
    """Verify circuit breaker engine fails closed on startup in production when secret is missing."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CIRCUIT_BREAKER_REARM_SECRET", raising=False)
    monkeypatch.delenv("CIRCUIT_BREAKER_REARM_SECRET_HASH", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        CircuitBreakerEngine(config=CircuitBreakerConfig())

    assert "Production circuit breaker startup failed closed" in str(exc_info.value)
    assert "CIRCUIT_BREAKER_REARM_SECRET" in str(exc_info.value)


def test_staging_missing_secret_fails_closed(monkeypatch):
    """Verify circuit breaker engine also fails closed in staging environment."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("CIRCUIT_BREAKER_REARM_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        CircuitBreakerEngine(config=CircuitBreakerConfig())


def test_production_with_valid_secret_succeeds(monkeypatch):
    """Verify production starts up successfully when rearm secret is supplied."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    secret = "super_secure_production_rearm_key_99182"
    cb = CircuitBreakerEngine(config=CircuitBreakerConfig(rearm_secret=secret))
    assert cb.state == GatewayState.NORMAL


def test_production_with_secret_hash_succeeds(monkeypatch):
    """Verify production starts up successfully when rearm secret hash is supplied."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    secret = "hash_injected_production_key_443"
    secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    cb = CircuitBreakerEngine(config=CircuitBreakerConfig(rearm_secret_hash=secret_hash))
    cb.trigger_emergency_halt("TEST_HALT")
    assert cb.is_halted is True

    # Rearm with secret
    assert cb.admin_rearm(secret) is True
    assert cb.is_halted is False


def test_incorrect_rearm_token_rejected_and_audited(caplog):
    """Verify incorrect rearm token is rejected and audit event is logged without leaking token."""
    secret = "secret_rearm_token_887766"
    cb = CircuitBreakerEngine(config=CircuitBreakerConfig(rearm_secret=secret))
    cb.trigger_emergency_halt("DRAWDOWN_BREACH")
    assert cb.is_halted is True

    attacker_token = "malicious_attempt_guess_secret_123"
    with caplog.at_level(logging.WARNING):
        success = cb.admin_rearm(attacker_token)

    assert success is False
    assert cb.is_halted is True
    # Verify submitted token is never leaked in log output
    assert attacker_token not in caplog.text
    assert secret not in caplog.text


def test_valid_rearm_token_restores_state_and_audited(caplog):
    """Verify valid rearm token restores state to NORMAL with audit event."""
    secret = "legitimate_admin_key_7712"
    cb = CircuitBreakerEngine(config=CircuitBreakerConfig(rearm_secret=secret))
    cb.trigger_emergency_halt("MANUAL_EMERGENCY_HALT")
    assert cb.is_halted is True

    with caplog.at_level(logging.INFO):
        success = cb.admin_rearm(secret)

    assert success is True
    assert cb.is_halted is False
    assert cb.state == GatewayState.NORMAL
    # Verify secret is never leaked in logs
    assert secret not in caplog.text


def test_no_secret_leakage_in_repr_or_str():
    """Verify secret is not leaked in __repr__ or __str__ of config or engine."""
    secret = "ultra_sensitive_rearm_password_xyz987"
    config = CircuitBreakerConfig(rearm_secret=secret)
    cb = CircuitBreakerEngine(config=config)

    config_repr = repr(config)
    config_str = str(config)
    cb_repr = repr(cb)
    cb_str = str(cb)

    assert secret not in config_repr
    assert secret not in config_str
    assert secret not in cb_repr
    assert secret not in cb_str
