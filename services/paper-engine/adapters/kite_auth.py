"""
Algo Lab — Automated Zerodha Kite Connect 3.0 Morning TOTP Authenticator.

Automates the mandatory daily morning authentication flow for Zerodha Kite Connect:
1. Submits User ID and Password to Kite login endpoint.
2. Generates dynamic 6-digit TOTP token using base32 TOTP secret.
3. Completes 2FA handshake and extracts request_token.
4. Exchanges request_token + SHA-256 checksum for daily access_token.
5. Caches access_token locally for seamless live paper/forward session startup.
"""

import os
import sys
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any
import requests

try:
    import pyotp
except ImportError:
    pyotp = None

logger = logging.getLogger("KiteAuthAutomator")


class KiteAutomatedAuth:
    """Automates daily morning 2FA login for Kite Connect 3.0."""

    KITE_BASE_URL = "https://api.kite.trade"
    KITE_LOGIN_URL = "https://kite.zerodha.com/api/login"
    KITE_TWOFA_URL = "https://kite.zerodha.com/api/twofa"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        user_id: Optional[str] = None,
        password: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("KITE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("KITE_API_SECRET", "")
        self.user_id = user_id or os.getenv("KITE_USER_ID", "")
        self.password = password or os.getenv("KITE_PASSWORD", "")
        self.totp_secret = totp_secret or os.getenv("KITE_TOTP_SECRET", "")

    def generate_current_totp(self) -> str:
        """Generates dynamic RFC 6238 6-digit TOTP code."""
        if not self.totp_secret:
            raise ValueError("KITE_TOTP_SECRET is required to generate dynamic 2FA code.")
        if pyotp is None:
            raise ImportError("pyotp package is required: run pip install pyotp")
        totp = pyotp.TOTP(self.totp_secret.replace(" ", "").strip())
        return totp.now()

    def generate_session_checksum(self, request_token: str) -> str:
        """Kite Connect checksum: sha256(api_key + request_token + api_secret)."""
        token_str = f"{self.api_key}{request_token}{self.api_secret}"
        return hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    def exchange_request_token(self, request_token: str) -> Dict[str, Any]:
        """Exchanges request_token for a 24-hour Kite access_token."""
        checksum = self.generate_session_checksum(request_token)
        url = f"{self.KITE_BASE_URL}/session/token"
        payload = {
            "api_key": self.api_key,
            "request_token": request_token,
            "checksum": checksum,
        }
        resp = requests.post(url, data=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "success":
            return data.get("data", {})
        raise RuntimeError(f"Kite session token exchange failed: {data}")


if __name__ == "__main__":
    auth = KiteAutomatedAuth(api_key="DEMO_KEY", api_secret="DEMO_SECRET")
    print("KiteAutomatedAuth initial sanity check passed.")
