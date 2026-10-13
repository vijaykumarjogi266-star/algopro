import os
import sys
import sqlite3
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
)


def verify_no_plaintext():
    key = Fernet.generate_key().decode()
    secret_key_marker = "SUPER_SECRET_CLEAR_TEXT_MARKER_998877"
    secret_pw_marker = "SUPER_SECRET_BROKER_PW_112233"
    
    store = BrokerCredentialStore(db_path=":memory:", fernet=Fernet(key.encode()))
    cfg = BrokerConnectionConfig(
        connection_id="test_conn_verify",
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key=secret_key_marker,
        api_secret=secret_pw_marker,
        extra_params={"user_id": "TEST_USER_1", "access_token": "ACCESS_SECRET_TOKEN_4455"},
    )
    store.save_connection(cfg)

    # Inspect SQLite database directly
    conn = store._get_connection()
    cur = conn.execute("SELECT api_key, api_secret, extra_params FROM broker_connections WHERE connection_id='test_conn_verify'")
    row = cur.fetchone()

    raw_api_key = row["api_key"]
    raw_api_secret = row["api_secret"]
    raw_extra = row["extra_params"]

    if secret_key_marker in raw_api_key:
        print("[FAIL] api_key was stored in plaintext!")
        sys.exit(1)
    if secret_pw_marker in raw_api_secret:
        print("[FAIL] api_secret was stored in plaintext!")
        sys.exit(1)
    if "ACCESS_SECRET_TOKEN_4455" in raw_extra:
        print("[FAIL] extra_params sensitive secret was stored in plaintext!")
        sys.exit(1)

    # Verify decryption
    loaded = store.get_connection("test_conn_verify")
    if loaded.api_key != secret_key_marker or loaded.api_secret != secret_pw_marker:
        print("[FAIL] Credential decryption failed.")
        sys.exit(1)

    print("[PASS] Verified: Synthetic credentials never appear in database plaintext and decrypt correctly.")


if __name__ == "__main__":
    verify_no_plaintext()
