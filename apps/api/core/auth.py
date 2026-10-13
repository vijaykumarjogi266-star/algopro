"""Algo Lab API Authentication — X-API-Key header enforcement.

Security model:
- Development (ENVIRONMENT=development): pass-through if ALGO_LAB_API_KEY not set.
- Non-development: REQUIRES ALGO_LAB_API_KEY env var; fail-closed at startup if absent.
- Uses constant-time HMAC comparison to prevent timing attacks.
- Never logs the raw API key — only its presence/absence.
"""

import hashlib
import hmac
import os
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_API_KEY_HEADER_NAME = "X-API-Key"
_API_KEY_HEADER = APIKeyHeader(name=_API_KEY_HEADER_NAME, auto_error=False)


def _get_configured_key() -> Optional[str]:
    """Return the configured ALGO_LAB_API_KEY from environment, or None."""
    return os.environ.get("ALGO_LAB_API_KEY", "").strip() or None


def _is_dev_environment() -> bool:
    env = os.environ.get("ENVIRONMENT", "development").lower()
    return env in ("development", "dev", "test", "testing")


def validate_api_key_at_startup() -> None:
    """Call at application startup to fail-closed in non-development environments.

    Raises RuntimeError if ALGO_LAB_API_KEY is not configured in production.
    """
    if not _is_dev_environment() and not _get_configured_key():
        raise RuntimeError(
            "ALGO_LAB_API_KEY environment variable must be set in non-development environments. "
            "Generate a strong key with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )


async def require_api_key(api_key: Optional[str] = Security(_API_KEY_HEADER)) -> None:
    """FastAPI dependency: validates X-API-Key header.

    - In development with no key configured: pass-through (allows easy local dev).
    - Otherwise: requires correct X-API-Key; rejects with 401/403.
    """
    expected_key = _get_configured_key()

    if not expected_key:
        if _is_dev_environment():
            return  # Development bypass — no key configured
        # Should not reach here if validate_api_key_at_startup() was called
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured on server.",
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time comparison to prevent timing attacks
    provided_hash = hashlib.sha256(api_key.encode()).digest()
    expected_hash = hashlib.sha256(expected_key.encode()).digest()
    if not hmac.compare_digest(provided_hash, expected_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
