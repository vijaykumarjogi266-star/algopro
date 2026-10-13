import os
import sqlite3
import pytest
from cryptography.fernet import Fernet
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    mask_secret,
)


def test_fernet_encryption_at_rest():
    key = Fernet.generate_key().decode()
    store = BrokerCredentialStore(db_path=":memory:", fernet=Fernet(key.encode()))

    cfg = BrokerConnectionConfig(
        connection_id="test_conn_1",
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key="super_secret_api_key_12345",
        api_secret="super_secret_broker_password_999",
        extra_params={"user_id": "AB1234", "access_token": "token_abcdef123"},
    )
    store.save_connection(cfg)

    # Inspect raw database to ensure plaintext does NOT exist in SQLite table
    conn = store._get_connection()
    cursor = conn.execute("SELECT api_key, api_secret, extra_params FROM broker_connections WHERE connection_id = 'test_conn_1'")
    row = cursor.fetchone()
    raw_key = row["api_key"]
    raw_secret = row["api_secret"]
    raw_extra = row["extra_params"]

    assert raw_key != "super_secret_api_key_12345"
    assert "super_secret_api_key_12345" not in raw_key
    assert "super_secret_broker_password_999" not in raw_secret
    assert "token_abcdef123" not in raw_extra

    # Decrypt upon retrieval
    loaded = store.get_connection("test_conn_1")
    assert loaded is not None
    assert loaded.api_key == "super_secret_api_key_12345"
    assert loaded.api_secret == "super_secret_broker_password_999"
    assert loaded.extra_params["access_token"] == "token_abcdef123"
    assert loaded.extra_params["user_id"] == "AB1234"


def test_extra_params_allowlist_enforcement():
    store = BrokerCredentialStore(db_path=":memory:")

    # Disallowed extra param should fail closed
    bad_cfg = BrokerConnectionConfig(
        connection_id="test_conn_bad",
        broker_name="upstox",
        extra_params={"disallowed_random_hack": "malicious_payload"},
    )
    with pytest.raises(ValueError, match="Disallowed extra_param"):
        store.save_connection(bad_cfg)


def test_safe_dict_redaction():
    cfg = BrokerConnectionConfig(
        broker_name="zerodha",
        api_key="AKIA1234567890SECRET",
        api_secret="SEC1234567890VALUE",
        extra_params={"access_token": "MY_SECRET_ACCESS_TOKEN", "user_id": "USER123"},
    )
    safe = cfg.to_safe_dict()
    assert safe["api_key_masked"] == "AK****CRET"
    assert "SECRET" not in safe["api_key_masked"]
    assert "MY_SECRET_ACCESS_TOKEN" not in str(safe["extra_params"])
    assert safe["extra_params"]["user_id"] == "USER123"


def test_production_fail_closed_without_encryption_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("BROKER_CREDENTIAL_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Production credential store requires BROKER_CREDENTIAL_ENCRYPTION_KEY"):
        BrokerCredentialStore(db_path=":memory:", fernet=None)
