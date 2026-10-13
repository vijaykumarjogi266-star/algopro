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
from enum import Enum
from typing import Optional

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


def validate_api_key_at_startup() -> None:
    """Validate security settings during application lifespan."""
    if settings.ENVIRONMENT == "production":
        if not settings.ALGO_LAB_API_KEY or not settings.ALGO_LAB_API_KEY.strip():
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
    configured_key = settings.ALGO_LAB_API_KEY.strip() if settings.ALGO_LAB_API_KEY else ""

    # Allow local development/testing bypass only if explicitly enabled or key is not configured
    if not configured_key:
        if settings.ENVIRONMENT in ("development", "testing") or settings.ALLOW_LOCAL_AUTH_BYPASS:
            # Grant default role or requested role for local development
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

    # In production or when configured_key is set:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
        )

    provided_hash = hashlib.sha256(api_key.encode()).digest()
    expected_hash = hashlib.sha256(configured_key.encode()).digest()

    if not hmac.compare_digest(provided_hash, expected_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    # Master key grants administrator privileges by default
    assigned_role = Role.ADMINISTRATOR

    # If caller specifies a role (e.g. for least-privilege testing or delegation), down-scope
    if requested_role_header:
        try:
            target_role = Role(requested_role_header.strip().lower())
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
    async def _role_checker(current_role: Role = Security(authenticate_request)) -> Role:
        if ROLE_HIERARCHY[current_role] < ROLE_HIERARCHY[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role permissions. Requires at least '{min_role.value}', got '{current_role.value}'.",
            )
        return current_role
    return _role_checker


# Convenient role dependencies
require_reader = require_role(Role.READER)
require_researcher = require_role(Role.RESEARCHER)
require_operator = require_role(Role.OPERATOR)
require_administrator = require_role(Role.ADMINISTRATOR)
require_api_key = require_reader  # Base requirement for any authenticated endpoint
