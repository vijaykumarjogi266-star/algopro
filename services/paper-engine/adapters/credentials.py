"""Algo Lab Broker Connection & Credential Store with Fernet Encryption (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 13: Fail closed.
- Principle 25: No live capital deployment (LIVE execution strictly prohibited).
- Security: Secrets (API keys, secrets, tokens) are NEVER stored in plain text.
  They are encrypted at rest using Fernet symmetric encryption with a key
  injected via BROKER_CREDENTIAL_ENCRYPTION_KEY environment variable.
  Secrets are never printed in repr/str, never fingerprinted, and never
  returned via GET APIs.
"""

import json
import logging
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field
from cryptography.fernet import Fernet, InvalidToken

from apps.api.core.logging import get_logger

logger = get_logger(__name__)

# Hard architectural flags
LIVE_TRADING_ENABLED: bool = False
REAL_BROKER_EXECUTION_ENABLED: bool = False

# Strict allowlist of non-sensitive extra_params keys.
# Any key not in this list will be rejected at save time.
ALLOWED_EXTRA_PARAM_KEYS = frozenset([
    "exchange", "segment", "account_id", "product_type",
    "user_id", "client_id", "totp_token", "access_token",
])

_SENSITIVE_EXTRA_KEYS = frozenset(["secret", "token", "password", "key"])


class ExecutionEnvironment(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


def mask_secret(secret: Optional[str]) -> str:
    """Masks secrets to prevent accidental leakage in logs, UI, or serialized payloads."""
    if not secret:
        return ""
    s = str(secret).strip()
    if len(s) <= 6:
        return "******"
    return f"{s[:2]}****{s[-4:]}"


class BrokerConnectionConfig(BaseModel):
    """Configuration for broker adapter with masked representations."""

    connection_id: str = Field(default_factory=lambda: f"conn_{uuid.uuid4().hex[:8]}")
    broker_name: str = Field(description="Broker name, e.g., 'zerodha', 'upstox', 'simulated'")
    environment: ExecutionEnvironment = Field(default=ExecutionEnvironment.PAPER)
    api_key: Optional[str] = Field(default=None)
    api_secret: Optional[str] = Field(default=None)
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns safe dictionary with all sensitive credentials strictly masked."""
        return {
            "connection_id": self.connection_id,
            "broker_name": self.broker_name,
            "environment": self.environment.value,
            "api_key_masked": mask_secret(self.api_key),
            "api_key_configured": bool(self.api_key),
            "api_secret_configured": bool(self.api_secret),
            "extra_params": {
                k: mask_secret(str(v)) if any(sec in k.lower() for sec in _SENSITIVE_EXTRA_KEYS) else v
                for k, v in self.extra_params.items()
            },
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<BrokerConnectionConfig connection_id={self.connection_id} broker={self.broker_name} "
            f"env={self.environment} api_key={mask_secret(self.api_key)}>"
        )

    def __str__(self) -> str:
        return self.__repr__()


def _resolve_fernet_key(key: Optional[str] = None, env: Optional[str] = None) -> Fernet:
    """Resolve Fernet encryption key from explicit key or environment.

    - Production/staging: requires BROKER_CREDENTIAL_ENCRYPTION_KEY; fails closed if absent.
    - Development: generates an ephemeral key (data won't survive restart) and logs a warning.
    """
    raw_key = (key if key is not None else os.environ.get("BROKER_CREDENTIAL_ENCRYPTION_KEY", "")).strip()
    target_env = (env if env is not None else os.environ.get("ENVIRONMENT", "development")).lower()
    if not raw_key:
        if target_env in ("production", "prod", "staging"):
            raise RuntimeError(
                "Production credential store requires BROKER_CREDENTIAL_ENCRYPTION_KEY "
                "environment variable to be set. Startup aborted (fail-closed)."
            )
        # Development: generate ephemeral key
        ephemeral_key = Fernet.generate_key()
        logger.warning(
            "BROKER_CREDENTIAL_ENCRYPTION_KEY not set. Using ephemeral Fernet key — "
            "credentials will NOT survive process restart. Set the env var for persistence."
        )
        return Fernet(ephemeral_key)
    try:
        return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)
    except Exception as exc:
        raise RuntimeError(
            f"BROKER_CREDENTIAL_ENCRYPTION_KEY is invalid (must be a Fernet URL-safe base64 key): {exc}"
        ) from exc


class DecryptionError(RuntimeError):
    """Raised when authenticated credential decryption fails or legacy plaintext is detected."""
    pass


class BrokerCredentialStore:
    """Thread-safe SQLite store for broker configurations with Fernet encryption at rest."""

    def __init__(
        self,
        db_path: str = ":memory:",
        fernet: Optional[Fernet] = None,
        encryption_key: Optional[str] = None,
        env: Optional[str] = None,
    ):
        self.db_path = db_path
        self._lock = threading.RLock()
        # Resolve Fernet cipher — allows injection in tests
        if fernet is not None:
            self._fernet = fernet
        else:
            self._fernet = _resolve_fernet_key(key=encryption_key, env=env)
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")
        else:
            self._persistent_conn = None
        self._init_db()

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """Encrypt a plaintext string; returns None for None input."""
        if plaintext is None:
            return None
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """Decrypt an authenticated ciphertext string.

        Fail-closed rules:
        - If ciphertext is None, returns None.
        - If ciphertext is not a Fernet token (e.g. legacy plaintext), raises DecryptionError.
        - If decryption fails (wrong key, tampering, or corruption), raises DecryptionError.
        - NEVER returns raw ciphertext or plaintext fallback.
        """
        if ciphertext is None:
            return None
        if not ciphertext:
            return ""

        if not ciphertext.startswith("gAAAAA"):
            raise DecryptionError(
                "Legacy plaintext credential detected; explicit migration required before access."
            )

        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except Exception as exc:
            raise DecryptionError(
                "Authenticated credential decryption failed: invalid token, wrong key, or tampered record."
            ) from exc

    def _encrypt_extra_params(self, extra_params: Dict[str, Any]) -> str:
        """Encrypt sensitive extra_params values and serialize to JSON."""
        encrypted = {}
        for k, v in extra_params.items():
            if any(s in k.lower() for s in _SENSITIVE_EXTRA_KEYS):
                encrypted[k] = self._encrypt(str(v))
            else:
                encrypted[k] = v
        return json.dumps(encrypted)

    def _decrypt_extra_params(self, raw_json: str) -> Dict[str, Any]:
        """Deserialize and decrypt extra_params from stored JSON."""
        data = json.loads(raw_json)
        result = {}
        for k, v in data.items():
            if any(s in k.lower() for s in _SENSITIVE_EXTRA_KEYS) and isinstance(v, str):
                result[k] = self._decrypt(v)
            else:
                result[k] = v
        return result

    def _get_connection(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS broker_connections (
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

    def save_connection(self, config: BrokerConnectionConfig) -> BrokerConnectionConfig:
        """Saves or updates connection configuration with credentials encrypted at rest.

        Fail closed:
        - Rejects LIVE environment if LIVE_TRADING_ENABLED is False.
        - Rejects extra_params keys not in ALLOWED_EXTRA_PARAM_KEYS.
        - Encrypts api_key, api_secret, and sensitive extra_params before storage.
        """
        if config.environment == ExecutionEnvironment.LIVE and not LIVE_TRADING_ENABLED:
            raise PermissionError(
                "LIVE trading execution is strictly prohibited by safety policy (LIVE_TRADING_ENABLED = False)."
            )

        # Enforce strict extra_params allowlist
        disallowed = set(config.extra_params.keys()) - ALLOWED_EXTRA_PARAM_KEYS
        if disallowed:
            raise ValueError(
                f"Disallowed extra_param key(s): {sorted(disallowed)}. "
                f"Only these keys are permitted: {sorted(ALLOWED_EXTRA_PARAM_KEYS)}"
            )

        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                INSERT INTO broker_connections (
                    connection_id, broker_name, environment, api_key, api_secret,
                    extra_params, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    broker_name = excluded.broker_name,
                    environment = excluded.environment,
                    api_key = excluded.api_key,
                    api_secret = excluded.api_secret,
                    extra_params = excluded.extra_params,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """, (
                    config.connection_id,
                    config.broker_name,
                    config.environment.value,
                    self._encrypt(config.api_key),        # encrypted at rest
                    self._encrypt(config.api_secret),     # encrypted at rest
                    self._encrypt_extra_params(config.extra_params),  # sensitive values encrypted
                    1 if config.is_active else 0,
                    config.created_at.isoformat(),
                    config.updated_at.isoformat(),
                ))
            return config

    def get_connection(self, connection_id: str) -> Optional[BrokerConnectionConfig]:
        """Retrieves raw connection (internal use only — decrypts credentials)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT * FROM broker_connections WHERE connection_id = ?",
                (connection_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_config(row)

    def list_connections(self, masked: bool = True) -> List[Dict[str, Any]]:
        """Lists connections. If masked is True, never exposes raw credentials."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM broker_connections ORDER BY created_at DESC")
            rows = cursor.fetchall()
            configs = [self._row_to_config(r) for r in rows]
            if masked:
                return [c.to_safe_dict() for c in configs]
            return [c.model_dump() for c in configs]

    def delete_connection(self, connection_id: str) -> bool:
        """Deletes a broker connection."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM broker_connections WHERE connection_id = ?",
                    (connection_id,),
                )
                return cursor.rowcount > 0

    def test_connection(self, connection_id: str) -> Dict[str, Any]:
        """Tests connectivity with the broker credentials."""
        try:
            config = self.get_connection(connection_id)
        except DecryptionError as exc:
            return {
                "connected": False,
                "status": "DECRYPTION_FAILED",
                "verification_level": "FAILED",
                "message": f"Credential decryption failed: {exc}",
            }
        if not config:
            return {"connected": False, "status": "NOT_FOUND", "message": "Connection ID not found"}

        if config.broker_name.lower() in ("simulated", "mock", "paper"):
            return {
                "connected": True,
                "status": "SIMULATED_HEALTHY",
                "verification_level": "VERIFIED_SIMULATED",
                "message": f"Simulated paper broker adapter '{config.broker_name}' is operational.",
                "latency_ms": 0.5,
                "environment": config.environment.value,
            }

        # For external brokers, never claim connected=True merely because an API key is present
        return {
            "connected": False,
            "status": "UNVERIFIED_SANDBOX",
            "verification_level": "UNVERIFIED_SANDBOX",
            "message": f"Credentials configured for {config.broker_name} ({config.environment.value}). Real broker execution is locked.",
            "latency_ms": 42.0,
            "environment": config.environment.value,
        }

    def _row_to_config(self, row: sqlite3.Row) -> BrokerConnectionConfig:
        """Load and decrypt a credential row from SQLite."""
        return BrokerConnectionConfig(
            connection_id=row["connection_id"],
            broker_name=row["broker_name"],
            environment=ExecutionEnvironment(row["environment"]),
            api_key=self._decrypt(row["api_key"]),        # decrypt from storage
            api_secret=self._decrypt(row["api_secret"]),  # decrypt from storage
            extra_params=self._decrypt_extra_params(row["extra_params"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


def migrate_plaintext_credentials(db_path: str, fernet: Optional[Fernet] = None) -> int:
    """Migrates legacy plaintext broker credentials to Fernet-encrypted format.

    Procedure:
    1. Validates database exists.
    2. Performs backup-first safety copy and validates with PRAGMA integrity_check.
       Also copies -wal and -shm files if they exist.
    3. Runs atomic transaction encrypting plaintext values (api_key, api_secret, sensitive extra_params).
    4. If any step fails, rolls back and restores backup (cleaning any stale WAL/SHM).
    5. Security notice: Historical backups and SQLite WAL may retain plaintext copies;
       rotate credentials with the broker provider after migration.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    cipher = fernet or _resolve_fernet_key()

    # Backup-first: create verified backup copy before any mutation
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"

    shutil.copy2(db_path, backup_path)
    # Also copy -wal and -shm files if they exist
    for ext in ("-wal", "-shm"):
        aux_file = f"{db_path}{ext}"
        if os.path.exists(aux_file):
            shutil.copy2(aux_file, f"{backup_path}{ext}")

    # Verify backup integrity (use mode=ro so SQLite does not checkpoint/unlink WAL files on close)
    verify_uri = f"file:{os.path.abspath(backup_path)}?mode=ro"
    verify_conn = sqlite3.connect(verify_uri, uri=True)
    try:
        cur = verify_conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError("Backup integrity check failed before migration.")
    finally:
        verify_conn.close()

    # Atomic migration in transaction
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrated_count = 0
    try:
        with conn:
            rows = conn.execute("SELECT * FROM broker_connections").fetchall()
            for row in rows:
                api_key = row["api_key"]
                api_secret = row["api_secret"]
                raw_extra = row["extra_params"]

                needs_update = False
                enc_key = api_key
                enc_secret = api_secret

                if api_key and not api_key.startswith("gAAAAA"):
                    enc_key = cipher.encrypt(api_key.encode()).decode()
                    needs_update = True
                if api_secret and not api_secret.startswith("gAAAAA"):
                    enc_secret = cipher.encrypt(api_secret.encode()).decode()
                    needs_update = True

                # Encrypt sensitive fields inside extra_params JSON
                # (keys containing 'token', 'secret', 'password', 'key') if not already starting with gAAAAA
                extra_params_dict = {}
                if raw_extra:
                    if isinstance(raw_extra, str):
                        try:
                            extra_params_dict = json.loads(raw_extra)
                        except Exception:
                            extra_params_dict = {}
                    elif isinstance(raw_extra, dict):
                        extra_params_dict = raw_extra

                updated_extra = dict(extra_params_dict)
                extra_updated = False
                for k, v in extra_params_dict.items():
                    if any(s in k.lower() for s in ("token", "secret", "password", "key")):
                        if v is not None:
                            str_v = str(v)
                            if not str_v.startswith("gAAAAA"):
                                updated_extra[k] = cipher.encrypt(str_v.encode()).decode()
                                extra_updated = True
                                needs_update = True

                enc_extra = json.dumps(updated_extra) if extra_updated else raw_extra

                if needs_update:
                    conn.execute("""
                    UPDATE broker_connections
                    SET api_key = ?, api_secret = ?, extra_params = ?, updated_at = ?
                    WHERE connection_id = ?
                    """, (enc_key, enc_secret, enc_extra, datetime.now(timezone.utc).isoformat(), row["connection_id"]))
                    migrated_count += 1
    except Exception as exc:
        conn.close()
        # Roll back: close connection, restore database from backup copy
        shutil.copy2(backup_path, db_path)
        # If {db_path}-wal and {db_path}-shm exist, remove them so stale WAL doesn't overwrite restored database
        for ext in ("-wal", "-shm"):
            aux_file = f"{db_path}{ext}"
            if os.path.exists(aux_file):
                try:
                    os.remove(aux_file)
                except OSError:
                    pass
        raise RuntimeError(f"Migration failed and was rolled back to backup: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info(
        f"Successfully migrated {migrated_count} broker connections to encrypted storage. "
        f"Backup preserved at {backup_path}. Rotate broker keys to invalidate old plaintext records."
    )
    return migrated_count
