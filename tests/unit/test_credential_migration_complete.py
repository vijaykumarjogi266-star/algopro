"""Unit tests for complete credential migration, backup safety, WAL handling, and fail-closed tampering.

Tests:
- T20 test_migration_creates_backup_and_preserves_wal
- T21 test_migration_encrypts_sensitive_extra_params
- T22 test_migration_failure_triggers_atomic_rollback
- T23 test_authenticated_fernet_fails_closed_on_tampering
- test_broker_test_connection_verification_levels
"""

import json
import os
import sqlite3
import tempfile
import pytest
from cryptography.fernet import Fernet
from unittest.mock import patch

from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    DecryptionError,
    migrate_plaintext_credentials,
)


def _create_legacy_db(db_path: str, rows: list) -> None:
    """Helper to initialize a sqlite database with legacy unencrypted broker_connections."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("""
        CREATE TABLE broker_connections (
            connection_id TEXT PRIMARY KEY,
            broker_name TEXT NOT NULL,
            environment TEXT NOT NULL,
            api_key TEXT,
            api_secret TEXT,
            extra_params TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        for r in rows:
            conn.execute("""
            INSERT INTO broker_connections (
                connection_id, broker_name, environment, api_key, api_secret,
                extra_params, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, r)
    conn.close()


def test_migration_creates_backup_and_preserves_wal():
    """T20: Migration creates verified timestamped backup copy and preserves -wal and -shm files."""
    key = Fernet.generate_key()
    fernet = Fernet(key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_creds.db")
        wal_path = f"{db_path}-wal"
        shm_path = f"{db_path}-shm"

        # Create initial legacy database
        _create_legacy_db(db_path, [
            (
                "conn_wal_1",
                "zerodha",
                "PAPER",
                "plaintext_key_123",
                "plaintext_secret_456",
                "{}",
                1,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            )
        ])

        # Create synthetic -wal and -shm files to simulate active WAL state
        with open(wal_path, "wb") as f:
            f.write(b"SIMULATED_WAL_PAGE_BUFFER_12345")
        with open(shm_path, "wb") as f:
            f.write(b"SIMULATED_SHM_INDEX_BUFFER_67890")

        # Execute migration
        migrated_count = migrate_plaintext_credentials(db_path, fernet=fernet)
        assert migrated_count == 1

        # Assert timestamped backup copy was created
        all_files = os.listdir(tmp_dir)
        backup_dbs = [f for f in all_files if f.startswith("test_creds.db.backup_") and not f.endswith(("-wal", "-shm"))]
        assert len(backup_dbs) >= 1, "Timestamped backup file must exist"

        backup_file = backup_dbs[0]
        backup_full_path = os.path.join(tmp_dir, backup_file)

        # Assert backup copies of -wal and -shm were preserved
        assert os.path.exists(f"{backup_full_path}-wal"), "Backup of -wal must exist"
        assert os.path.exists(f"{backup_full_path}-shm"), "Backup of -shm must exist"

        with open(f"{backup_full_path}-wal", "rb") as f:
            assert f.read() == b"SIMULATED_WAL_PAGE_BUFFER_12345"
        assert os.path.getsize(f"{backup_full_path}-shm") > 0

        # Assert backup database is a valid sqlite file with original unencrypted data
        bconn = sqlite3.connect(backup_full_path)
        brow = bconn.execute("SELECT api_key, api_secret FROM broker_connections WHERE connection_id = 'conn_wal_1'").fetchone()
        assert brow[0] == "plaintext_key_123"
        assert brow[1] == "plaintext_secret_456"
        bconn.close()

        # Assert main db is now encrypted
        store = BrokerCredentialStore(db_path=db_path, fernet=fernet)
        loaded = store.get_connection("conn_wal_1")
        assert loaded is not None
        assert loaded.api_key == "plaintext_key_123"
        assert loaded.api_secret == "plaintext_secret_456"


def test_migration_encrypts_sensitive_extra_params():
    """T21: Migration encrypts sensitive fields in extra_params (totp_token, access_token) at rest."""
    key = Fernet.generate_key()
    fernet = Fernet(key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_extra.db")

        extra_payload = {
            "account_id": "ACC_9988",
            "exchange": "NSE",
            "totp_token": "PLAINTEXT_TOTP_SECRET_888",
            "access_token": "PLAINTEXT_OAUTH_TOKEN_777",
            "user_id": "USER_VIP_101",
        }

        _create_legacy_db(db_path, [
            (
                "conn_extra_1",
                "upstox",
                "PAPER",
                "raw_api_key_001",
                "raw_api_secret_002",
                json.dumps(extra_payload),
                1,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            )
        ])

        # Prior to migration, normal store read must fail closed on legacy plaintext
        pre_store = BrokerCredentialStore(db_path=db_path, fernet=fernet)
        with pytest.raises(DecryptionError):
            pre_store.get_connection("conn_extra_1")

        # Run migration
        migrated = migrate_plaintext_credentials(db_path, fernet=fernet)
        assert migrated == 1

        # Check raw SQLite table directly
        raw_conn = sqlite3.connect(db_path)
        row = raw_conn.execute("SELECT api_key, api_secret, extra_params FROM broker_connections WHERE connection_id = 'conn_extra_1'").fetchone()
        raw_conn.close()

        raw_key = row[0]
        raw_secret = row[1]
        raw_extra = json.loads(row[2])

        # Verify raw values are encrypted Fernet tokens (starts with gAAAAA)
        assert raw_key.startswith("gAAAAA")
        assert raw_secret.startswith("gAAAAA")
        assert "raw_api_key_001" not in raw_key
        assert "raw_api_secret_002" not in raw_secret

        # Sensitive extra_params keys must be encrypted Fernet tokens
        assert raw_extra["totp_token"].startswith("gAAAAA")
        assert "PLAINTEXT_TOTP_SECRET_888" not in raw_extra["totp_token"]
        assert raw_extra["access_token"].startswith("gAAAAA")
        assert "PLAINTEXT_OAUTH_TOKEN_777" not in raw_extra["access_token"]

        # Non-sensitive keys remain plaintext
        assert raw_extra["account_id"] == "ACC_9988"
        assert raw_extra["exchange"] == "NSE"
        assert raw_extra["user_id"] == "USER_VIP_101"

        # Reopen with BrokerCredentialStore and verify seamless authenticated decryption
        store = BrokerCredentialStore(db_path=db_path, fernet=fernet)
        cfg = store.get_connection("conn_extra_1")
        assert cfg is not None
        assert cfg.api_key == "raw_api_key_001"
        assert cfg.api_secret == "raw_api_secret_002"
        assert cfg.extra_params["totp_token"] == "PLAINTEXT_TOTP_SECRET_888"
        assert cfg.extra_params["access_token"] == "PLAINTEXT_OAUTH_TOKEN_777"
        assert cfg.extra_params["account_id"] == "ACC_9988"


def test_migration_failure_triggers_atomic_rollback():
    """T22: Migration failure rolls back atomic transaction, restores original db, and removes WAL/SHM."""
    key = Fernet.generate_key()
    fernet = Fernet(key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_rollback.db")
        wal_path = f"{db_path}-wal"
        shm_path = f"{db_path}-shm"

        _create_legacy_db(db_path, [
            (
                "conn_fail_1",
                "zerodha",
                "PAPER",
                "original_plain_key",
                "original_plain_secret",
                json.dumps({"totp_token": "token_123"}),
                1,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            )
        ])

        # Create active WAL and SHM files
        with open(wal_path, "wb") as f:
            f.write(b"DIRTY_WAL_BYTES_THAT_SHOULD_BE_CLEANED")
        with open(shm_path, "wb") as f:
            f.write(b"DIRTY_SHM_BYTES_THAT_SHOULD_BE_CLEANED")

        # Inject simulated failure during migration
        with patch.object(fernet, "encrypt", side_effect=RuntimeError("Simulated crypto failure mid-migration")):
            with pytest.raises(RuntimeError, match="Migration failed and was rolled back to backup"):
                migrate_plaintext_credentials(db_path, fernet=fernet)

        # Database must be restored to original state
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT api_key, api_secret, extra_params FROM broker_connections WHERE connection_id = 'conn_fail_1'").fetchone()
        conn.close()

        assert row[0] == "original_plain_key"
        assert row[1] == "original_plain_secret"
        assert "token_123" in row[2]

        # Stale WAL and SHM files must have been cleaned up to prevent dirty WAL overwrite
        assert not os.path.exists(wal_path), "Stale WAL file must be removed during rollback"
        assert not os.path.exists(shm_path), "Stale SHM file must be removed during rollback"


def test_authenticated_fernet_fails_closed_on_tampering():
    """T23: Authenticated Fernet fails closed (DecryptionError) on tampered ciphertext or wrong key."""
    key = Fernet.generate_key()
    fernet = Fernet(key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_tamper.db")
        store = BrokerCredentialStore(db_path=db_path, fernet=fernet)

        cfg = BrokerConnectionConfig(
            connection_id="conn_tamper_test",
            broker_name="zerodha",
            environment=ExecutionEnvironment.PAPER,
            api_key="valid_api_key_abc",
            api_secret="valid_api_secret_def",
            extra_params={"totp_token": "valid_totp_999", "access_token": "valid_oauth_888"},
        )
        store.save_connection(cfg)

        # Verify normal read succeeds
        assert store.get_connection("conn_tamper_test") is not None

        # 1. Tamper api_key in SQLite
        conn = sqlite3.connect(db_path)
        with conn:
            cur = conn.execute("SELECT api_key FROM broker_connections WHERE connection_id = 'conn_tamper_test'")
            orig_key = cur.fetchone()[0]
            tampered_key = orig_key[:-6] + "BADKEY"
            conn.execute("UPDATE broker_connections SET api_key = ? WHERE connection_id = 'conn_tamper_test'", (tampered_key,))
        conn.close()

        with pytest.raises(DecryptionError, match="Authenticated credential decryption failed"):
            store.get_connection("conn_tamper_test")

        res_test = store.test_connection("conn_tamper_test")
        assert res_test["connected"] is False
        assert res_test["status"] == "DECRYPTION_FAILED"
        assert res_test["verification_level"] == "FAILED"

        # 2. Re-save valid, then tamper sensitive extra_params token
        store.save_connection(cfg)
        conn = sqlite3.connect(db_path)
        with conn:
            cur = conn.execute("SELECT extra_params FROM broker_connections WHERE connection_id = 'conn_tamper_test'")
            params = json.loads(cur.fetchone()[0])
            params["totp_token"] = params["totp_token"][:-6] + "TAMPER"
            conn.execute("UPDATE broker_connections SET extra_params = ? WHERE connection_id = 'conn_tamper_test'", (json.dumps(params),))
        conn.close()

        with pytest.raises(DecryptionError, match="Authenticated credential decryption failed"):
            store.get_connection("conn_tamper_test")

        # 3. Wrong Fernet key on valid ciphertext
        store.save_connection(cfg)
        wrong_fernet = Fernet(Fernet.generate_key())
        store_wrong_key = BrokerCredentialStore(db_path=db_path, fernet=wrong_fernet)
        with pytest.raises(DecryptionError):
            store_wrong_key.get_connection("conn_tamper_test")


def test_broker_test_connection_verification_levels():
    """Verify test_connection returns VERIFIED_SIMULATED for simulated brokers, and UNVERIFIED_SANDBOX for external."""
    store = BrokerCredentialStore(db_path=":memory:")

    # Simulated broker
    sim_cfg = BrokerConnectionConfig(
        connection_id="sim_1",
        broker_name="simulated",
        environment=ExecutionEnvironment.PAPER,
    )
    store.save_connection(sim_cfg)
    sim_res = store.test_connection("sim_1")
    assert sim_res["connected"] is True
    assert sim_res["status"] == "SIMULATED_HEALTHY"
    assert sim_res["verification_level"] == "VERIFIED_SIMULATED"

    # External broker
    ext_cfg = BrokerConnectionConfig(
        connection_id="ext_1",
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key="key123",
        api_secret="secret123",
    )
    store.save_connection(ext_cfg)
    ext_res = store.test_connection("ext_1")
    assert ext_res["connected"] is False
    assert ext_res["status"] == "UNVERIFIED_SANDBOX"
    assert ext_res["verification_level"] == "UNVERIFIED_SANDBOX"
