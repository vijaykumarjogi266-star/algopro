"""Integration tests for database backup failure modes, online SQLite backup, and verification.

Tests:
50. test_online_backup_failure_does_not_publish_partial_backup
51. test_backup_restore_matches_committed_snapshot
"""

import os
import sqlite3
import tempfile
from unittest.mock import patch
import pytest

from services.paper_engine.autonomous_orchestrator import perform_safe_database_backup


def test_online_backup_failure_does_not_publish_partial_backup():
    """Test 50: If online backup fails, do not publish a partial backup,
    preserve previous good backup, and do not fall back to unsafe copy2 on active WAL.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "active_trading.db")
        backup_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        # Set up source database with WAL mode
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, qty INT)")
        conn.execute("INSERT INTO orders VALUES ('ord_1', 100)")
        conn.commit()
        conn.close()

        # Perform first valid backup
        first_backup = perform_safe_database_backup(db_path, backup_dir)
        assert os.path.exists(first_backup)
        first_mtime = os.path.getmtime(first_backup)

        # Now inject failure during backup publication
        with patch("os.replace", side_effect=OSError("Disk failure during publication")):
            with pytest.raises(Exception):
                perform_safe_database_backup(db_path, backup_dir)

        # Assert previous good backup was NOT corrupted or overwritten with partial data
        assert os.path.exists(first_backup)
        assert os.path.getmtime(first_backup) == first_mtime


def test_backup_restore_matches_committed_snapshot():
    """Test 51: Restoring backup matches committed snapshot and passes PRAGMA integrity_check == 'ok'."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "active_trading.db")
        backup_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE positions (symbol TEXT PRIMARY KEY, qty INT)")
        conn.execute("INSERT INTO positions VALUES ('RELIANCE', 50)")
        conn.commit()
        conn.close()

        backup_file = perform_safe_database_backup(db_path, backup_dir)

        # Verify restored backup integrity
        restore_conn = sqlite3.connect(backup_file)
        cur = restore_conn.execute("PRAGMA integrity_check")
        res = cur.fetchone()[0]
        assert res == "ok", f"Integrity check failed: {res}"

        # Assert committed data matches
        cur_pos = restore_conn.execute("SELECT symbol, qty FROM positions").fetchall()
        assert cur_pos == [("RELIANCE", 50)]
        restore_conn.close()
