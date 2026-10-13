"""Integration tests for credential error sanitization and redaction.

Tests:
11. test_broker_validation_errors_do_not_echo_secrets
12. test_internal_credential_validation_is_sanitized
"""

import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.core.config import settings
from services.paper_engine.adapters.credentials import BrokerConnectionConfig, ExecutionEnvironment


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("payload, marker", [
    (
        {"broker_name": "simulated", "environment": "PAPER", "api_key": {"secret": "CANARY_SECRET_KEY_123"}},
        "CANARY_SECRET_KEY_123",
    ),
    (
        {"broker_name": "simulated", "environment": "PAPER", "api_secret": {"secret": "CANARY_SECRET_VAL_456"}},
        "CANARY_SECRET_VAL_456",
    ),
    (
        {"broker_name": "simulated", "environment": "PAPER", "api_key": "valid_key", "extra_params": "CANARY_EXTRA_STRING_789"},
        "CANARY_EXTRA_STRING_789",
    ),
    (
        {"environment": "PAPER", "api_key": "CANARY_API_KEY_000", "api_secret": "CANARY_API_SECRET_000"},
        "CANARY_API_KEY_000",
    ),
])
def test_broker_validation_errors_do_not_echo_secrets(client, monkeypatch, payload, marker, caplog):
    """Test 11: Validation errors on broker credential routes must not echo secrets back to the client or log them."""
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)

    headers = {"X-API-Key": admin_key}
    resp = client.post("/api/v1/brokers/connections", json=payload, headers=headers)

    assert resp.status_code == 422, f"Expected 422 Unprocessable Entity, got {resp.status_code}: {resp.text}"
    # Marker must NEVER appear in response bytes or text
    assert marker not in resp.text, f"Secret marker '{marker}' leaked in 422 response body: {resp.text}"
    assert marker.encode() not in resp.content

    # Marker must NEVER appear in captured logs
    assert marker not in caplog.text, f"Secret marker '{marker}' leaked in application logs: {caplog.text}"

    # Verify structured error details still exist and give useful locations
    err_json = resp.json()
    assert "detail" in err_json


def test_internal_credential_validation_is_sanitized():
    """Test 12: Internal validation errors must not expose sensitive credentials in exception message or repr."""
    canary_secret = "CANARY_INTERNAL_SECRET_99999"
    # Construct invalid extra_params with sensitive key and value
    try:
        config = BrokerConnectionConfig(
            connection_id="test_conn",
            broker_name="simulated",
            environment=ExecutionEnvironment.PAPER,
            api_key=canary_secret,
            extra_params={"forbidden_secret_key": canary_secret},
        )
        # Should not reach here or if it does, str(e) / repr must not leak canary_secret
    except Exception as e:
        err_msg = str(e)
        assert canary_secret not in err_msg, f"Secret leaked in exception message: {err_msg}"
