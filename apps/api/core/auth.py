"""Algo Lab API Authentication & Scoped Role-Based Access Control (RBAC).

Security Architecture (Workstream C):
- Scoped Roles:
    1. viewer: Read-only access to research, metrics, and data.
    2. researcher: Viewer + ability to create and execute backtest experiments.
    3. operator: Researcher + paper broker session management and live daemon controls.
    4. risk_admin: Hard risk limit configuration, circuit breaker rearm, and emergency cutoff.
    5. system_admin: Full administrative control, credential and key management.
- Backward compatibility: 'reader' aliases 'viewer'; 'administrator' aliases 'system_admin'.
- Constant-time HMAC comparison (hmac.compare_digest) to prevent timing attacks.
- Cryptographic key hashing at rest with expiration metadata, rotation, and revocation state.
- Structured audit event logging for all privileged actions.
- Never logs raw API keys or tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Header, Security, status
from fastapi.security import APIKeyHeader

from apps.api.core.config import settings

logger = logging.getLogger("algo_lab.auth")

_API_KEY_HEADER_NAME = "X-API-Key"
_API_ROLE_HEADER_NAME = "X-API-Role"

_API_KEY_HEADER = APIKeyHeader(name=_API_KEY_HEADER_NAME, auto_error=False)


class Role(str, Enum):
    VIEWER = "viewer"
    READER = "reader"  # Backward-compatible alias to viewer
    RESEARCHER = "researcher"
    OPERATOR = "operator"
    RISK_ADMIN = "risk_admin"
    ADMINISTRATOR = "administrator"  # Backward-compatible alias to system_admin
    SYSTEM_ADMIN = "system_admin"

    @classmethod
    def canonical(cls, role_str: str) -> Role:
        """Resolve string to canonical Role enum with alias mapping."""
        norm = role_str.strip().lower()
        if norm in ("reader", "viewer"):
            return cls.VIEWER
        if norm == "researcher":
            return cls.RESEARCHER
        if norm == "operator":
            return cls.OPERATOR
        if norm == "risk_admin":
            return cls.RISK_ADMIN
        if norm in ("administrator", "system_admin", "admin"):
            return cls.SYSTEM_ADMIN
        raise ValueError(f"Unknown role '{role_str}'")


# Role hierarchy score: higher number = greater privilege
ROLE_HIERARCHY: Dict[Role, int] = {
    Role.VIEWER: 1,
    Role.READER: 1,
    Role.RESEARCHER: 2,
    Role.OPERATOR: 3,
    Role.RISK_ADMIN: 4,
    Role.ADMINISTRATOR: 5,
    Role.SYSTEM_ADMIN: 5,
}


@dataclass
class APIKeyRecord:
    """Cryptographically protected API Key metadata at rest."""
    key_id: str
    hashed_key: str
    role: Role
    scopes: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    revoked: bool = False
    last_used_at: Optional[datetime] = None


class KeyStore:
    """In-memory managed API key store supporting rotation, expiration, and revocation."""

    def __init__(self) -> None:
        self._records: Dict[str, APIKeyRecord] = {}  # key_id -> record
        self._hash_to_id: Dict[str, str] = {}       # sha256_hex -> key_id
        self._audit_log: List[Dict[str, Any]] = []

    def hash_key(self, raw_key: str) -> str:
        """Compute SHA-256 digest of API key."""
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def register_key(
        self,
        raw_key: str,
        role: Role,
        key_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
    ) -> APIKeyRecord:
        """Register an API key with hashed storage at rest."""
        clean_key = raw_key.strip()
        h = self.hash_key(clean_key)
        kid = key_id or f"key_{h[:12]}"
        canonical_role = Role.canonical(role.value)
        record = APIKeyRecord(
            key_id=kid,
            hashed_key=h,
            role=canonical_role,
            scopes=scopes or [canonical_role.value],
            expires_at=expires_at,
        )
        self._records[kid] = record
        self._hash_to_id[h] = kid
        return record

    def rotate_key(self, old_raw_key: str, new_raw_key: str) -> APIKeyRecord:
        """Rotate an active key to a new secret while preserving role and audit trail."""
        old_hash = self.hash_key(old_raw_key)
        old_id = self._hash_to_id.get(old_hash)
        if not old_id or old_id not in self._records:
            raise ValueError("Existing key not found for rotation.")

        old_rec = self._records[old_id]
        old_rec.revoked = True

        new_rec = self.register_key(
            raw_key=new_raw_key,
            role=old_rec.role,
            key_id=f"{old_id}_rotated_{int(datetime.now(timezone.utc).timestamp())}",
            scopes=old_rec.scopes,
        )
        self.record_audit_event(
            event_type="KEY_ROTATED",
            actor_id=old_id,
            role=old_rec.role.value,
            details={"previous_key_id": old_id, "new_key_id": new_rec.key_id},
        )
        return new_rec

    def revoke_key(self, raw_key: str) -> bool:
        """Revoke a key immediately."""
        h = self.hash_key(raw_key)
        kid = self._hash_to_id.get(h)
        if kid and kid in self._records:
            self._records[kid].revoked = True
            self.record_audit_event(
                event_type="KEY_REVOKED",
                actor_id=kid,
                role=self._records[kid].role.value,
                details={"key_id": kid},
            )
            return True
        return False

    def verify_and_resolve(self, raw_key: str) -> Optional[Role]:
        """Verify API key in constant time; check expiration and revocation."""
        provided_digest = hashlib.sha256(raw_key.strip().encode("utf-8")).digest()
        now = datetime.now(timezone.utc)

        matched_record: Optional[APIKeyRecord] = None

        for rec in self._records.values():
            target_digest = bytes.fromhex(rec.hashed_key)
            if hmac.compare_digest(provided_digest, target_digest):
                matched_record = rec

        if matched_record is None:
            return None

        if matched_record.revoked:
            return None

        if matched_record.expires_at and now > matched_record.expires_at:
            return None

        matched_record.last_used_at = now
        return matched_record.role

    def record_audit_event(
        self,
        event_type: str,
        actor_id: str,
        role: str,
        details: Dict[str, Any],
    ) -> None:
        """Record structured security audit event."""
        ev = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor_id": actor_id,
            "role": role,
            "details": details,
        }
        self._audit_log.append(ev)
        logger.info(f"SecurityAuditEvent: {event_type} by {actor_id} ({role})")

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit_log)


_KEY_STORE = KeyStore()


def get_key_store() -> KeyStore:
    return _KEY_STORE


def get_configured_key_roles() -> Dict[str, Role]:
    """Retrieve all configured API keys and their server-bound roles."""
    key_roles: Dict[str, Role] = {}

    # JSON key-to-role map
    if getattr(settings, "ALGO_LAB_API_KEYS_JSON", None):
        try:
            data = json.loads(settings.ALGO_LAB_API_KEYS_JSON)
            if isinstance(data, dict):
                for k, r in data.items():
                    if k and isinstance(k, str) and k.strip():
                        try:
                            key_roles[k.strip()] = Role.canonical(str(r))
                        except ValueError:
                            pass
        except Exception:
            pass

    # Role-specific environment keys
    if getattr(settings, "ALGO_LAB_API_KEY_VIEWER", None) and settings.ALGO_LAB_API_KEY_VIEWER.strip():
        key_roles[settings.ALGO_LAB_API_KEY_VIEWER.strip()] = Role.VIEWER
    if getattr(settings, "ALGO_LAB_API_KEY_READER", None) and settings.ALGO_LAB_API_KEY_READER.strip():
        key_roles[settings.ALGO_LAB_API_KEY_READER.strip()] = Role.VIEWER

    if getattr(settings, "ALGO_LAB_API_KEY_RESEARCHER", None) and settings.ALGO_LAB_API_KEY_RESEARCHER.strip():
        key_roles[settings.ALGO_LAB_API_KEY_RESEARCHER.strip()] = Role.RESEARCHER

    if getattr(settings, "ALGO_LAB_API_KEY_OPERATOR", None) and settings.ALGO_LAB_API_KEY_OPERATOR.strip():
        key_roles[settings.ALGO_LAB_API_KEY_OPERATOR.strip()] = Role.OPERATOR

    if getattr(settings, "ALGO_LAB_API_KEY_RISK_ADMIN", None) and settings.ALGO_LAB_API_KEY_RISK_ADMIN.strip():
        key_roles[settings.ALGO_LAB_API_KEY_RISK_ADMIN.strip()] = Role.RISK_ADMIN

    if getattr(settings, "ALGO_LAB_API_KEY_SYSTEM_ADMIN", None) and settings.ALGO_LAB_API_KEY_SYSTEM_ADMIN.strip():
        key_roles[settings.ALGO_LAB_API_KEY_SYSTEM_ADMIN.strip()] = Role.SYSTEM_ADMIN
    if getattr(settings, "ALGO_LAB_API_KEY_ADMIN", None) and settings.ALGO_LAB_API_KEY_ADMIN.strip():
        key_roles[settings.ALGO_LAB_API_KEY_ADMIN.strip()] = Role.SYSTEM_ADMIN

    # Primary master admin key (backward-compatible)
    if settings.ALGO_LAB_API_KEY and settings.ALGO_LAB_API_KEY.strip():
        key_roles[settings.ALGO_LAB_API_KEY.strip()] = Role.SYSTEM_ADMIN

    return key_roles


def sync_configured_keys_to_store() -> None:
    """Sync static settings keys to the KeyStore for hashed verification."""
    store = get_key_store()
    configured = get_configured_key_roles()
    for raw_k, r in configured.items():
        store.register_key(raw_key=raw_k, role=r)


def has_configured_keys() -> bool:
    """Return True if at least one API key is configured."""
    return bool(get_configured_key_roles())


def resolve_key_role(api_key: Optional[str]) -> Optional[Role]:
    """Constant-time lookup matching api_key against configured keys and returning bound Role."""
    if not api_key:
        return None

    store = get_key_store()
    role_from_store = store.verify_and_resolve(api_key)
    if role_from_store is not None:
        return role_from_store

    configured_map = get_configured_key_roles()
    if not configured_map:
        return None

    provided_hash = hashlib.sha256(api_key.encode("utf-8")).digest()
    matched_role: Optional[Role] = None

    for candidate_key, assigned_role in configured_map.items():
        candidate_hash = hashlib.sha256(candidate_key.encode("utf-8")).digest()
        if hmac.compare_digest(provided_hash, candidate_hash):
            matched_role = assigned_role

    if matched_role:
        store.register_key(api_key, matched_role)

    return matched_role


def validate_api_key_at_startup() -> None:
    """Validate security settings during application lifespan."""
    sync_configured_keys_to_store()
    if settings.ENVIRONMENT == "production":
        admin_key = (
            settings.ALGO_LAB_API_KEY
            or getattr(settings, "ALGO_LAB_API_KEY_SYSTEM_ADMIN", "")
            or getattr(settings, "ALGO_LAB_API_KEY_ADMIN", "")
        )
        if not admin_key or not admin_key.strip():
            raise RuntimeError(
                "ALGO_LAB_API_KEY must be configured in production environments."
            )


def authenticate_request(
    api_key: Optional[str] = Security(_API_KEY_HEADER),
    requested_role_header: Optional[str] = Header(None, alias=_API_ROLE_HEADER_NAME),
) -> Role:
    """Authenticate API key and resolve the authorized Role.

    Raises:
    - 401 Unauthorized if key is missing when required.
    - 403 Forbidden if key is invalid or requested role exceeds permission.
    """
    configured_keys = get_configured_key_roles()

    # Allow local development/testing bypass only if non-production
    if not configured_keys:
        if settings.ENVIRONMENT in ("development", "testing") or (
            settings.ALLOW_LOCAL_AUTH_BYPASS and settings.ENVIRONMENT != "production"
        ):
            if requested_role_header:
                try:
                    return Role.canonical(requested_role_header)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown role '{requested_role_header}'",
                    )
            return Role.SYSTEM_ADMIN
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API authentication not configured on server.",
        )

    if not api_key:
        if settings.ALLOW_LOCAL_AUTH_BYPASS and settings.ENVIRONMENT != "production":
            if requested_role_header:
                try:
                    return Role.canonical(requested_role_header)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown role '{requested_role_header}'",
                    )
            return Role.SYSTEM_ADMIN
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
        )

    assigned_role = resolve_key_role(api_key)
    if assigned_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    # If caller specifies a down-scoped role, check hierarchy
    if requested_role_header:
        try:
            target_role = Role.canonical(requested_role_header)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown role '{requested_role_header}'",
            )
        if ROLE_HIERARCHY[target_role] > ROLE_HIERARCHY[assigned_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{target_role.value}' exceeds key privileges.",
            )
        return target_role

    return assigned_role


def require_role(min_role: Role):
    """Factory creating FastAPI dependencies that enforce a minimum RBAC role."""
    canonical_min = Role.canonical(min_role.value)

    async def _role_checker(current_role: Role = Security(authenticate_request)) -> Role:
        canonical_cur = Role.canonical(current_role.value)
        if ROLE_HIERARCHY[canonical_cur] < ROLE_HIERARCHY[canonical_min]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient role permissions. Requires at least '{canonical_min.value}', "
                    f"got '{canonical_cur.value}'."
                ),
            )
        return canonical_cur

    return _role_checker


# Canonical Scoped Role dependencies (Workstream C)
require_viewer = require_role(Role.VIEWER)
require_researcher = require_role(Role.RESEARCHER)
require_operator = require_role(Role.OPERATOR)
require_risk_admin = require_role(Role.RISK_ADMIN)
require_system_admin = require_role(Role.SYSTEM_ADMIN)

# Backward-compatible aliases
require_reader = require_viewer
require_administrator = require_system_admin
require_api_key = require_viewer
