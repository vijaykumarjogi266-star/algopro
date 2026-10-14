"""Unit Tests for Workstream D: Encrypted Backup & Restore Operations.

Verifies:
1. AES-256 authenticated encryption of database backups.
2. HMAC SHA-256 integrity verification preventing tampered restore.
3. Exact row-level reconstruction upon restore.
4. Retention policy enforcement pruning older snapshots.
5. Fail-closed behavior on invalid keys or corrupted ciphertext.
"""

import json
import os
import sqlite3
import tempfile
import pytest

from scripts.backup_database import create_encrypted_backup, prune_old_backups
from scripts.restore_database import BackupVerificationError, restore_encrypted_backup


@pytest.fixture
def sample_sqlite_db():
    """Creates a temporary SQLite database populated with test records."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY, balance REAL)")
    conn.execute("INSERT INTO accounts VALUES ('acc_001', 500000.0)")
    conn.execute("INSERT INTO accounts VALUES ('acc_002', 125000.5)")
    conn.commit()
    conn.close()

    yield db_path

    if os.path.exists(db_path):
        os.remove(db_path)


def test_backup_encryption_and_integrity(sample_sqlite_db):
    """Backup produces encrypted ciphertext and HMAC manifest."""
    with tempfile.TemporaryDirectory() as backup_dir:
        res = create_encrypted_backup(
            source_db_path=sample_sqlite_db,
            output_dir=backup_dir,
            key_override="test_secret_key_12345",
        )

        assert os.path.exists(res["backup_path"])
        assert os.path.exists(res["manifest_path"])
        assert len(res["hmac_sha256"]) == 64

        # Verify ciphertext is not plaintext
        with open(res["backup_path"], "rb") as f:
            ciphertext = f.read()
        assert b"acc_001" not in ciphertext
        assert b"500000" not in ciphertext


def test_successful_restore_reconstructs_data(sample_sqlite_db):
    """Restore successfully recovers exact SQLite tables and records."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = os.path.join(temp_dir, "backups")
        restored_db = os.path.join(temp_dir, "restored.db")

        res = create_encrypted_backup(
            source_db_path=sample_sqlite_db,
            output_dir=backup_dir,
            key_override="test_secret_key_12345",
        )

        # Execute restore
        success = restore_encrypted_backup(
            encrypted_file_path=res["backup_path"],
            target_db_path=restored_db,
            manifest_path=res["manifest_path"],
            key_override="test_secret_key_12345",
        )
        assert success is True
        assert os.path.exists(restored_db)

        # Verify restored contents
        conn = sqlite3.connect(restored_db)
        rows = conn.execute("SELECT id, balance FROM accounts ORDER BY id").fetchall()
        conn.close()

        assert rows == [("acc_001", 500000.0), ("acc_002", 125000.5)]


def test_restore_fails_closed_on_tampered_ciphertext(sample_sqlite_db):
    """Restore aborts with BackupVerificationError if ciphertext has been modified."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = os.path.join(temp_dir, "backups")
        restored_db = os.path.join(temp_dir, "restored.db")

        res = create_encrypted_backup(
            source_db_path=sample_sqlite_db,
            output_dir=backup_dir,
            key_override="test_secret_key_12345",
        )

        # Tamper with 1 byte in ciphertext
        with open(res["backup_path"], "r+b") as f:
            f.seek(50)
            f.write(b"X")

        with pytest.raises(BackupVerificationError, match="HMAC verification failed"):
            restore_encrypted_backup(
                encrypted_file_path=res["backup_path"],
                target_db_path=restored_db,
                manifest_path=res["manifest_path"],
                key_override="test_secret_key_12345",
            )


def test_restore_fails_on_wrong_key(sample_sqlite_db):
    """Restore fails closed when provided an incorrect encryption key."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = os.path.join(temp_dir, "backups")
        restored_db = os.path.join(temp_dir, "restored.db")

        res = create_encrypted_backup(
            source_db_path=sample_sqlite_db,
            output_dir=backup_dir,
            key_override="correct_key_12345",
        )

        with pytest.raises(BackupVerificationError):
            restore_encrypted_backup(
                encrypted_file_path=res["backup_path"],
                target_db_path=restored_db,
                manifest_path=res["manifest_path"],
                key_override="wrong_key_99999",
            )


def test_backup_retention_policy_pruning(sample_sqlite_db):
    """Retention policy prunes older backup snapshots beyond retention limit."""
    with tempfile.TemporaryDirectory() as backup_dir:
        # Create 5 backups with retention count = 3
        for i in range(5):
            # Create dummy backup files
            fpath = os.path.join(backup_dir, f"backup_20261014_000{i}.enc")
            mpath = os.path.join(backup_dir, f"backup_20261014_000{i}_manifest.json")
            with open(fpath, "wb") as f:
                f.write(b"dummy_data")
            with open(mpath, "w") as f:
                json.dump({}, f)

        remaining = sorted(os.listdir(backup_dir))
        assert len(remaining) == 10  # 5 enc + 5 json

        pruned = prune_old_backups(backup_dir, retention_count=3)
        assert pruned == 2

        remaining_enc = [f for f in os.listdir(backup_dir) if f.endswith(".enc")]
        assert len(remaining_enc) == 3
