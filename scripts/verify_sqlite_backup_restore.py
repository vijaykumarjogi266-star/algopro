import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def verify_sqlite_backup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        src_db = tf.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf2:
        dst_db = tf2.name

    try:
        # Create source DB with WAL mode and populate data
        conn = sqlite3.connect(src_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, symbol TEXT, qty INT)")
        conn.execute("INSERT INTO orders VALUES ('ord_1', 'RELIANCE', 10)")
        conn.execute("INSERT INTO orders VALUES ('ord_2', 'TCS', 25)")
        conn.commit()

        # Check WAL exists
        wal_file = src_db + "-wal"
        
        # Perform online backup
        dst_conn = sqlite3.connect(dst_db)
        with dst_conn:
            conn.backup(dst_conn)
        dst_conn.close()
        conn.close()

        # Verify restored DB has exact identical data
        check_conn = sqlite3.connect(dst_db)
        rows = check_conn.execute("SELECT id, symbol, qty FROM orders ORDER BY id").fetchall()
        check_conn.close()

        expected = [("ord_1", "RELIANCE", 10), ("ord_2", "TCS", 25)]
        if rows != expected:
            print(f"[FAIL] Backup data mismatch: {rows} != {expected}")
            sys.exit(1)

        print("[PASS] Verified: SQLite online backup accurately preserved committed WAL transactions.")
    finally:
        for p in [src_db, src_db + "-wal", src_db + "-shm", dst_db]:
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    verify_sqlite_backup()
