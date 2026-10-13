"""End-to-End Security Configuration & Secret Lifecycle Integration Tests.

Regressions covered:
- R01: test_dotenv_only_production_uses_configured_breaker_keys
- R02: test_dotenv_only_credentials_survive_restart
- R03: test_missing_dotenv_secrets_fail_closed
- R04: test_exported_environment_and_dotenv_have_equivalent_security
- R05: test_json_role_map_is_validated_and_redacted
"""

import json
import logging
import os
import sqlite3
import pytest
from cryptography.fernet import Fernet

from apps.api.core.config import Settings, export_security_settings
from apps.api.core.auth import Role, resolve_key_role, get_configured_key_roles
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import CircuitBreakerConfig
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
)


CANARY_KEY = "canary_secret_key_999888777666"


def _write_env_file(path, entries: dict):
    with open(path, "w", encoding="utf-8") as f:
        for k, v in entries.items():
            f.write(f"{k}={v}\n")


def test_dotenv_only_production_uses_configured_breaker_keys(tmp_path):
    """R01: Verify breaker configured via .env restores halt and rearm works with configured rearm token."""
    state_file = str(tmp_path / "circuit_breaker_state.json")
    env_file = tmp_path / ".env.prod"
    rearm_secret = "strong_rearm_token_production_9999"
    state_key = "strong_state_integrity_key_production_8888"
    fernet_key = Fernet.generate_key().decode()

    env_data = {
        "ENVIRONMENT": "production",
        "ALGO_LAB_API_KEY": "strong_admin_key_production_7777",
        "CIRCUIT_BREAKER_REARM_SECRET": rearm_secret,
        "CIRCUIT_BREAKER_STATE_KEY": state_key,
        "CIRCUIT_BREAKER_STATE_PATH": state_file,
        "BROKER_CREDENTIAL_ENCRYPTION_KEY": fernet_key,
    }
    _write_env_file(env_file, env_data)

    settings = Settings(_env_file=str(env_file))

    # Breaker initialized using settings loaded from .env
    engine = CircuitBreakerEngine(
        state_file_path=settings.CIRCUIT_BREAKER_STATE_PATH,
        rearm_secret=settings.CIRCUIT_BREAKER_REARM_SECRET,
        state_integrity_key=settings.CIRCUIT_BREAKER_STATE_KEY,
        env=settings.ENVIRONMENT,
        allow_uninitialized=True,
    )

    # Trigger emergency halt
    engine.trigger_emergency_halt("TEST_PRODUCTION_HALT")
    assert engine.is_halted is True
    assert os.path.exists(state_file)

    # Restart: instantiate new breaker engine with same settings
    restarted_engine = CircuitBreakerEngine(
        state_file_path=settings.CIRCUIT_BREAKER_STATE_PATH,
        rearm_secret=settings.CIRCUIT_BREAKER_REARM_SECRET,
        state_integrity_key=settings.CIRCUIT_BREAKER_STATE_KEY,
        env=settings.ENVIRONMENT,
    )

    assert restarted_engine.is_halted is True
    assert restarted_engine.state == GatewayState.EMERGENCY_HALT

    # Rearm with wrong token must fail
    assert restarted_engine.admin_rearm("wrong_admin_token") is False
    assert restarted_engine.is_halted is True

    # Rearm with configured rearm secret from .env must succeed
    assert restarted_engine.admin_rearm(rearm_secret) is True
    assert restarted_engine.is_halted is False
    assert restarted_engine.state == GatewayState.NORMAL
    assert not os.path.exists(state_file)


def test_dotenv_only_credentials_survive_restart(tmp_path):
    """R02: Verify credential store with .env-only key encrypts and survives restart."""
    db_file = str(tmp_path / "credentials.sqlite")
    env_file = tmp_path / ".env.creds"
    fernet_key = Fernet.generate_key().decode()

    env_data = {
        "ENVIRONMENT": "production",
        "ALGO_LAB_API_KEY": "strong_admin_key_production_7777",
        "CIRCUIT_BREAKER_REARM_SECRET": "rearm_secret_prod_12345",
        "CIRCUIT_BREAKER_STATE_KEY": "state_key_prod_12345678",
        "BROKER_CREDENTIAL_ENCRYPTION_KEY": fernet_key,
    }
    _write_env_file(env_file, env_data)

    settings = Settings(_env_file=str(env_file))

    # Initialize credential store
    store1 = BrokerCredentialStore(
        db_path=db_file,
        encryption_key=settings.BROKER_CREDENTIAL_ENCRYPTION_KEY,
        env=settings.ENVIRONMENT,
    )

    # Save sensitive credentials
    cfg = BrokerConnectionConfig(
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key="real_api_key_secret_value",
        api_secret="real_api_secret_secret_value",
    )
    saved = store1.save_connection(cfg)

    # Verify directly in SQLite that credentials are never stored in plaintext
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT api_key, api_secret FROM broker_connections WHERE connection_id = ?", (saved.connection_id,))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0].startswith("gAAAAA"), "API key must be encrypted with Fernet"
    assert "real_api_key_secret_value" not in row[0], "Raw API key must not appear in ciphertext"
    assert row[1].startswith("gAAAAA"), "API secret must be encrypted with Fernet"
    assert "real_api_secret_secret_value" not in row[1], "Raw API secret must not appear in ciphertext"

    # Simulate restart by instantiating new store with same db and .env key
    store2 = BrokerCredentialStore(
        db_path=db_file,
        encryption_key=settings.BROKER_CREDENTIAL_ENCRYPTION_KEY,
        env=settings.ENVIRONMENT,
    )

    retrieved = store2.get_connection(saved.connection_id)
    assert retrieved is not None
    assert retrieved.api_key == "real_api_key_secret_value"
    assert retrieved.api_secret == "real_api_secret_secret_value"


@pytest.mark.parametrize("missing_param", [
    "ALGO_LAB_API_KEY",
    "BROKER_CREDENTIAL_ENCRYPTION_KEY",
    "CIRCUIT_BREAKER_REARM_SECRET",
    "CIRCUIT_BREAKER_STATE_KEY",
])
def test_missing_dotenv_secrets_fail_closed(tmp_path, missing_param):
    """R03: Parameterize missing API key, encryption key, rearm secret, state-integrity key. Assert startup failure."""
    env_file = tmp_path / f".env.missing_{missing_param}"
    valid_data = {
        "ENVIRONMENT": "production",
        "ALGO_LAB_API_KEY": "valid_strong_admin_key_12345",
        "CIRCUIT_BREAKER_REARM_SECRET": "valid_rearm_secret_12345",
        "CIRCUIT_BREAKER_STATE_KEY": "valid_state_key_12345678",
        "BROKER_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    # Remove the targeted parameter
    del valid_data[missing_param]
    _write_env_file(env_file, valid_data)

    with pytest.raises(ValueError) as exc_info:
        Settings(_env_file=str(env_file))

    assert "Production startup failed" in str(exc_info.value) or missing_param in str(exc_info.value)


def test_exported_environment_and_dotenv_have_equivalent_security(tmp_path, monkeypatch):
    """R04: Assert permissions, encryption persistence, and breaker recovery behave consistently under both env and .env."""
    fernet_key = Fernet.generate_key().decode()
    rearm_secret = "rearm_secret_equivalent_test_1234"
    state_key = "state_key_equivalent_test_5678"
    admin_key = "admin_key_equivalent_test_9012"
    reader_key = "reader_key_equivalent_test_3456"

    # 1. Test via .env
    env_file = tmp_path / ".env.equiv"
    env_data = {
        "ENVIRONMENT": "production",
        "ALGO_LAB_API_KEY_ADMIN": admin_key,
        "ALGO_LAB_API_KEY_READER": reader_key,
        "CIRCUIT_BREAKER_REARM_SECRET": rearm_secret,
        "CIRCUIT_BREAKER_STATE_KEY": state_key,
        "BROKER_CREDENTIAL_ENCRYPTION_KEY": fernet_key,
    }
    _write_env_file(env_file, env_data)
    dotenv_settings = Settings(_env_file=str(env_file))
    exported = export_security_settings(dotenv_settings)

    assert exported["environment"] == "production"
    assert exported["rearm_secret"] == rearm_secret
    assert exported["state_integrity_key"] == state_key
    assert exported["broker_credential_encryption_key"] == fernet_key
    assert exported["api_key_admin"] == admin_key
    assert exported["api_key_reader"] == reader_key

    # 2. Test via OS environment
    for k, v in env_data.items():
        monkeypatch.setenv(k, v)
    env_settings = Settings(_env_file=None)
    exported_env = export_security_settings(env_settings)

    assert exported == exported_env

    # 3. Test equivalence of credential store encryption and recovery
    shared_db = str(tmp_path / "shared_creds.sqlite")
    store_dotenv = BrokerCredentialStore(db_path=shared_db, encryption_key=exported["broker_credential_encryption_key"], env=exported["environment"])
    store_os = BrokerCredentialStore(db_path=shared_db, encryption_key=exported_env["broker_credential_encryption_key"], env=exported_env["environment"])

    cfg = BrokerConnectionConfig(broker_name="simulated", api_key="secret123", api_secret="pass123")
    saved = store_dotenv.save_connection(cfg)
    loaded = store_os.get_connection(saved.connection_id)
    assert loaded is not None
    assert loaded.api_key == "secret123"

    # 4. Test equivalence of circuit breaker rearm
    state_file = str(tmp_path / "equiv_cb.json")
    cb_dotenv = CircuitBreakerEngine(
        state_file_path=state_file,
        rearm_secret=exported["rearm_secret"],
        state_integrity_key=exported["state_integrity_key"],
        env=exported["environment"],
        allow_uninitialized=True,
    )
    cb_dotenv.trigger_emergency_halt("TEST_EQUIVALENT_HALT")
    assert cb_dotenv.is_halted is True

    cb_os = CircuitBreakerEngine(
        state_file_path=state_file,
        rearm_secret=exported_env["rearm_secret"],
        state_integrity_key=exported_env["state_integrity_key"],
        env=exported_env["environment"],
    )
    assert cb_os.is_halted is True
    assert cb_os.admin_rearm(exported_env["rearm_secret"]) is True
    assert cb_os.is_halted is False


@pytest.mark.parametrize("scenario,payload,canary", [
    ("malformed_json", "{not_valid_json_string", CANARY_KEY),
    ("invalid_role", json.dumps({CANARY_KEY: "super_root"}), CANARY_KEY),
    ("placeholder_key", json.dumps({"CHANGE_ME_STRONG_RANDOM_API_KEY": "reader"}), "CHANGE_ME_STRONG_RANDOM_API_KEY"),
    ("duplicate_conflicting_keys", f'{{"{CANARY_KEY}": "reader", "{CANARY_KEY}": "operator"}}', CANARY_KEY),
    ("short_weak_key", json.dumps({"short_key": "reader"}), "short_key"),
    ("whitespace_key", json.dumps({"spaced canary key 12345": "reader"}), "spaced canary key 12345"),
])
def test_json_role_map_is_validated_and_redacted(tmp_path, caplog, scenario, payload, canary):
    """R05: Parameterize malformed JSON, invalid roles, placeholders, duplicate/conflicting keys, weak keys.
    Assert rejection. Capture logs/errors and assert canaries absent."""
    env_file = tmp_path / f".env.test_{scenario}"
    env_data = {
        "ENVIRONMENT": "development",
        "ALGO_LAB_API_KEYS_JSON": payload,
    }
    _write_env_file(env_file, env_data)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=str(env_file))

    err_msg = str(exc_info.value)
    log_text = caplog.text

    # Assert error occurred as expected
    assert err_msg != ""

    # CRITICAL: Verify canary secrets are NEVER present in error message or logs
    assert canary not in err_msg, f"Security violation: canary secret '{canary}' leaked in exception message: {err_msg}"
    assert canary not in log_text, f"Security violation: canary secret '{canary}' leaked in log output: {log_text}"
