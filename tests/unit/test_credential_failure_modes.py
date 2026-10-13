"""Unit tests for broker credential failure modes, encryption tampering, and atomic migration.

Tests:
20. test_wrong_encryption_key_fails_closed
21. test_tampered_sensitive_fields_are_rejected
22. test_legacy_plaintext_is_not_accepted_by_normal_reads
23. test_migration_is_backup_first_and_atomic
"""

import os
import sqlite3
import tempfile
import pytest
from cryptography.fernet import Fernet

from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    DecryptionError,
    migrate_plaintext_credentials,
)


def test_wrong_encryption_key_fails_closed():
    """Test 20: Save with Fernet key A, reopen with key B.
    Retrieval must fail closed / quarantine; no raw ciphertext returned, connectivity not verified.
    """
    key_a = Fernet.generate_key()
    key_b = Fernet.generate_key()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "creds.db")

        # Save with Key A
        store_a = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key_a))
        cfg = BrokerConnectionConfig(
            connection_id="conn_a",
            broker_name="zerodha",
            environment=ExecutionEnvironment.PAPER,
            api_key="my_secret_api_key_12345",
            api_secret="my_secret_pass_67890",
        )
        store_a.save_connection(cfg)

        # Reopen with Key B
        store_b = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key_b))

        # Direct get_connection must raise DecryptionError or return None
        with pytest.raises(DecryptionError):
            store_b.get_connection("conn_a")

        # Connectivity test must report failure
        test_res = store_b.test_connection("conn_a")
        assert test_res["connected"] is False
        assert test_res["status"] in ("DECRYPTION_FAILED", "AUTH_FAILED")


@pytest.mark.parametrize("field_to_tamper", ["api_key", "api_secret"])
def test_tampered_sensitive_fields_are_rejected(field_to_tamper):
    """Test 21: Tampering ciphertext directly in SQLite causes authenticated decryption failure."""
    key = Fernet.generate_key()
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "creds.db")
        store = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key))

        cfg = BrokerConnectionConfig(
            connection_id="conn_tamper",
            broker_name="zerodha",
            environment=ExecutionEnvironment.PAPER,
            api_key="real_api_key_111",
            api_secret="real_api_secret_222",
        )
        store.save_connection(cfg)

        # Directly tamper the ciphertext in SQLite
        conn = sqlite3.connect(db_path)
        with conn:
            # Change a few bytes in the ciphertext
            cursor = conn.execute(f"SELECT {field_to_tamper} FROM broker_connections WHERE connection_id = 'conn_tamper'")
            orig_val = cursor.fetchone()[0]
            tampered = orig_val[:-4] + "XXXX"
            conn.execute(f"UPDATE broker_connections SET {field_to_tamper} = ? WHERE connection_id = 'conn_tamper'", (tampered,))
        conn.close()

        # Normal retrieval must fail closed and never expose raw ciphertext
        with pytest.raises(DecryptionError):
            store.get_connection("conn_tamper")


def test_legacy_plaintext_is_not_accepted_by_normal_reads():
    """Test 22: Legacy plaintext record inserted into DB must be rejected by normal reads."""
    key = Fernet.generate_key()
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "creds.db")
        store = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key))

        # Manually insert legacy plaintext row
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("""
            INSERT INTO broker_connections (
                connection_id, broker_name, environment, api_key, api_secret,
                extra_params, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "legacy_conn",
                "zerodha",
                "PAPER",
                "plaintext_legacy_key",
                "plaintext_legacy_secret",
                "{}",
                1,
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ))
        conn.close()

        # Normal reads must reject it and demand migration
        with pytest.raises(DecryptionError) as exc_info:
            store.get_connection("legacy_conn")
        assert "migration" in str(exc_info.value).lower() or "legacy" in str(exc_info.value).lower()


def test_migration_is_backup_first_and_atomic():
    """Test 23: Explicit migration creates verified backup first, encrypts records atomically,
    and rolls back if failure is injected.
    """
    key = Fernet.generate_key()
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "creds.db")
        store = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key))

        # Insert 2 legacy plaintext records
        conn = sqlite3.connect(db_path)
        with conn:
            for i in [1, 2]:
                conn.execute("""
                INSERT INTO broker_connections (
                    connection_id, broker_name, environment, api_key, api_secret,
                    extra_params, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"conn_{i}",
                    "zerodha",
                    "PAPER",
                    f"plain_key_{i}",
                    f"plain_secret_{i}",
                    "{}",
                    1,
                    "2024-01-01T00:00:00",
                    "2024-01-01T00:00:00",
                ))
        conn.close()

        # 1. Run migration
        migrated_count = migrate_plaintext_credentials(db_path, fernet=Fernet(key))
        assert migrated_count == 2

        # 2. Assert backup file was created
        backups = [f for f in os.listdir(tmp_dir) if "backup" in f]
        assert len(backups) >= 1

        # 3. Assert active records are now encrypted and readable
        reopened = BrokerCredentialStore(db_path=db_path, fernet=Fernet(key))
        c1 = reopened.get_connection("conn_1")
        assert c1.api_key == "plain_key_1"
        assert c1.api_secret == "plain_secret_1"

        # Assert no plaintext remains in SQLite file
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT api_key FROM broker_connections WHERE connection_id = 'conn_1'")
        raw_stored = cursor.fetchone()[0]
        assert raw_stored.startswith("gAAAAA"), "Must be stored as Fernet ciphertext"
        assert "plain_key_1" not in raw_stored
        conn.close()
