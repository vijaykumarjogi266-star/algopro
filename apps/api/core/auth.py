"""Algo Lab API Authentication & Role-Based Access Control (RBAC).

Security model:
- Single validated configuration source: apps.api.core.config.settings.
- Constant-time HMAC comparison (hmac.compare_digest) to prevent timing attacks.
- Never logs raw API keys or tokens.
- Granular Role-Based Access Control:
    1. reader: Read-only access to research, metrics, and data.
    2. researcher: Reader + ability to create and execute backtest experiments.
    3. operator: Researcher + paper broker session management and live daemon controls.
    4. administrator: Operator + circuit breaker rearm and sensitive credentials management.
"""

import hashlib
import hmac
import json
from enum import Enum
from typing import Dict, Optional

from fastapi import HTTPException, Header, Security, status
from fastapi.security import APIKeyHeader

from apps.api.core.config import settings

_API_KEY_HEADER_NAME = "X-API-Key"
_API_ROLE_HEADER_NAME = "X-API-Role"

_API_KEY_HEADER = APIKeyHeader(name=_API_KEY_HEADER_NAME, auto_error=False)


class Role(str, Enum):
    READER = "reader"
    RESEARCHER = "researcher"
    OPERATOR = "operator"
    ADMINISTRATOR = "administrator"


ROLE_HIERARCHY = {
    Role.READER: 1,
    Role.RESEARCHER: 2,
    Role.OPERATOR: 3,
    Role.ADMINISTRATOR: 4,
}


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
                            key_roles[k.strip()] = Role(str(r).strip().lower())
                        except ValueError:
                            pass
        except Exception:
            pass

    # Role-specific environment keys
    if getattr(settings, "ALGO_LAB_API_KEY_READER", None) and settings.ALGO_LAB_API_KEY_READER.strip():
        key_roles[settings.ALGO_LAB_API_KEY_READER.strip()] = Role.READER

    if getattr(settings, "ALGO_LAB_API_KEY_RESEARCHER", None) and settings.ALGO_LAB_API_KEY_RESEARCHER.strip():
        key_roles[settings.ALGO_LAB_API_KEY_RESEARCHER.strip()] = Role.RESEARCHER

    if getattr(settings, "ALGO_LAB_API_KEY_OPERATOR", None) and settings.ALGO_LAB_API_KEY_OPERATOR.strip():
        key_roles[settings.ALGO_LAB_API_KEY_OPERATOR.strip()] = Role.OPERATOR

    if getattr(settings, "ALGO_LAB_API_KEY_ADMIN", None) and settings.ALGO_LAB_API_KEY_ADMIN.strip():
        key_roles[settings.ALGO_LAB_API_KEY_ADMIN.strip()] = Role.ADMINISTRATOR

    # Primary master admin key (backward-compatible)
    if settings.ALGO_LAB_API_KEY and settings.ALGO_LAB_API_KEY.strip():
        key_roles[settings.ALGO_LAB_API_KEY.strip()] = Role.ADMINISTRATOR

    return key_roles


def has_configured_keys() -> bool:
    """Return True if at least one API key is configured."""
    return bool(get_configured_key_roles())


def resolve_key_role(api_key: Optional[str]) -> Optional[Role]:
    """Constant-time lookup matching api_key against configured keys and returning bound Role."""
    if not api_key:
        return None

    configured_map = get_configured_key_roles()
    if not configured_map:
        return None

    provided_hash = hashlib.sha256(api_key.encode("utf-8")).digest()
    matched_role: Optional[Role] = None

    for candidate_key, assigned_role in configured_map.items():
        candidate_hash = hashlib.sha256(candidate_key.encode("utf-8")).digest()
        if hmac.compare_digest(provided_hash, candidate_hash):
            matched_role = assigned_role

    return matched_role


def validate_api_key_at_startup() -> None:
    """Validate security settings during application lifespan."""
    if settings.ENVIRONMENT == "production":
        admin_key = settings.ALGO_LAB_API_KEY or getattr(settings, "ALGO_LAB_API_KEY_ADMIN", "")
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
                    return Role(requested_role_header.strip().lower())
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown role '{requested_role_header}'",
                    )
            return Role.ADMINISTRATOR
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API authentication not configured on server.",
        )

    # In production or when keys are configured:
    if not api_key:
        if settings.ALLOW_LOCAL_AUTH_BYPASS and settings.ENVIRONMENT != "production":
            if requested_role_header:
                try:
                    return Role(requested_role_header.strip().lower())
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown role '{requested_role_header}'",
                    )
            return Role.ADMINISTRATOR
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

    # If caller specifies a role (e.g. down-scoping for least privilege), check hierarchy
    if requested_role_header:
        try:
            target_role = Role(requested_role_header.strip().lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown role '{requested_role_header}'",
            )
        # Rejection: caller cannot escalate to a role higher than the server-bound assigned role
        if ROLE_HIERARCHY[target_role] > ROLE_HIERARCHY[assigned_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{target_role.value}' exceeds key privileges.",
            )
        return target_role

    return assigned_role


def require_role(min_role: Role):
    """Factory creating FastAPI dependencies that enforce a minimum RBAC role."""
    async def _role_checker(current_role: Role = Security(authenticate_request)) -> Role:
        if ROLE_HIERARCHY[current_role] < ROLE_HIERARCHY[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role permissions. Requires at least '{min_role.value}', got '{current_role.value}'.",
            )
        return current_role
    return _role_checker


# Role dependencies
require_reader = require_role(Role.READER)
require_researcher = require_role(Role.RESEARCHER)
require_operator = require_role(Role.OPERATOR)
require_administrator = require_role(Role.ADMINISTRATOR)
require_api_key = require_reader  # Base requirement for any authenticated endpoint
