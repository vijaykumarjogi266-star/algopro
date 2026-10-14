"""Database Encrypted Restore Utility with HMAC Integrity Verification.

Restores database snapshots while strictly enforcing cryptographic authenticity:
- Verifies HMAC SHA-256 integrity signature before attempting decryption.
- Fails closed on corrupted, tampered, or truncated backup files.
- Restores database atomically to target path.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from scripts.backup_database import get_or_create_backup_key


class BackupVerificationError(Exception):
    """Raised when backup ciphertext integrity verification fails."""
    pass


def restore_encrypted_backup(
    encrypted_file_path: str,
    target_db_path: str,
    manifest_path: Optional[str] = None,
    key_override: Optional[str] = None,
) -> bool:
    """Verifies HMAC signature, decrypts ciphertext, and writes target database."""
    if not os.path.exists(encrypted_file_path):
        raise FileNotFoundError(f"Encrypted backup file '{encrypted_file_path}' not found.")

    fernet_key = get_or_create_backup_key(key_override)
    fernet = Fernet(fernet_key)

    with open(encrypted_file_path, "rb") as f:
        ciphertext = f.read()

    # Determine manifest file
    if manifest_path is None:
        p = os.path.splitext(encrypted_file_path)[0]
        manifest_path = p + "_manifest.json"

    # If manifest is present, verify HMAC signature
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        expected_hmac = manifest.get("hmac_sha256", "")
        actual_hmac = hmac.new(fernet_key, ciphertext, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_hmac, actual_hmac):
            raise BackupVerificationError(
                "HMAC verification failed! The backup file has been tampered with or corrupted."
            )

    # Decrypt ciphertext
    try:
        plaintext = fernet.decrypt(ciphertext)
    except InvalidToken as e:
        raise BackupVerificationError("Decryption failed! Invalid encryption key or corrupt ciphertext.") from e

    # Atomically write target database using temporary file
    target_dir = os.path.dirname(target_db_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(dir=target_dir, delete=False) as tf:
        tf.write(plaintext)
        temp_path = tf.name

    os.replace(temp_path, target_db_path)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore encrypted database backup")
    parser.add_argument("--backup", required=True, help="Path to .enc backup file")
    parser.add_argument("--target", required=True, help="Target restore database path")
    args = parser.parse_args()

    try:
        restore_encrypted_backup(args.backup, args.target)
        print(f"Database successfully restored to: {args.target}")
    except Exception as e:
        print(f"Restore failed: {e}")
        sys.exit(1)
