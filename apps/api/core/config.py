"""Algo Lab Core Configuration.

Enforces strict environment configuration, database connection parameters,
and non-negotiable safety constraints (e.g. no live trading, mandatory validation).
"""

import json
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.core.project_state import CURRENT_LIFECYCLE_STATE, SEMANTIC_VERSION


PLACEHOLDER_SECRETS = {
    "REQUIRED_IN_PRODUCTION",
    "CHANGE_ME_STRONG_RANDOM_API_KEY",
    "CHANGE_ME_STRONG_RANDOM_PASSWORD",
    "CHANGE_ME_REARM_SECRET",
    "CHANGE_ME_INTEGRITY_KEY",
    "CHANGE_ME_ENCRYPTION_KEY",
    "algo" + "lab_secret",
    "dev_db_password",
    "admin_secret_token",
    "secret",
    "password",
    "default_algo_lab_integrity_key",
    "placeholder",
    "changeme",
    "test",
    "admin",
    "123456",
    "12345678",
}

VALID_ROLES = frozenset([
    "viewer",
    "reader",
    "researcher",
    "operator",
    "risk_admin",
    "administrator",
    "system_admin",
])

VALID_ENVIRONMENTS = {
    "development": "development",
    "dev": "development",
    "testing": "testing",
    "test": "testing",
    "production": "production",
    "prod": "production",
    "staging": "production",
}


def is_known_placeholder(secret: Optional[str]) -> bool:
    """Return True if secret matches known placeholder secrets (case-insensitive)."""
    if not secret:
        return False
    s = str(secret).strip().lower()
    return s in {p.lower() for p in PLACEHOLDER_SECRETS}


def is_invalid_secret(secret: Optional[str]) -> bool:
    """Return True if secret is empty, whitespace-only, or a known placeholder."""
    if secret is None:
        return True
    s = str(secret).strip()
    return not s or is_known_placeholder(s)


def validate_key_strength(key: str) -> None:
    """Validate API key strength without leaking raw key content in exception messages."""
    if not isinstance(key, str) or not key:
        raise ValueError("API key must be a non-empty string.")
    if any(c.isspace() for c in key):
        raise ValueError("API key must not contain whitespace characters.")
    if len(key) < 16:
        raise ValueError("API key does not meet strength requirements: minimum length is 16 characters.")
    if is_known_placeholder(key):
        raise ValueError("API key cannot be a known placeholder secret.")
    if len(set(key)) <= 2:
        raise ValueError("API key does not meet entropy requirements: repetitive pattern detected.")
    if key.isdigit():
        raise ValueError("API key does not meet entropy requirements: purely numeric key is prohibited.")


def parse_and_validate_api_keys_json(raw_json: Optional[str]) -> Dict[str, str]:
    """Parse and validate ALGO_LAB_API_KEYS_JSON.

    Enforces:
    - Valid JSON object
    - String keys to string roles
    - Role is one of VALID_ROLES
    - Key strength (len >= 16, no whitespace, non-placeholder)
    - No duplicate keys within JSON

    Never prints or leaks key values in error messages.
    """
    if not raw_json or not str(raw_json).strip():
        return {}

    def _pairs_hook(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                raise ValueError("Conflicting duplicate credential detected in ALGO_LAB_API_KEYS_JSON.")
            seen[k] = v
        return seen

    try:
        data = json.loads(str(raw_json).strip(), object_pairs_hook=_pairs_hook)
    except ValueError as e:
        if "duplicate credential" in str(e).lower():
            raise
        raise ValueError(f"ALGO_LAB_API_KEYS_JSON is malformed JSON: {e}") from None

    if not isinstance(data, dict):
        raise ValueError("ALGO_LAB_API_KEYS_JSON must be a JSON object mapping keys to roles.")

    validated: Dict[str, str] = {}
    for k, r in data.items():
        if not isinstance(k, str) or not isinstance(r, str):
            raise ValueError("ALGO_LAB_API_KEYS_JSON must map string keys to string roles.")

        validate_key_strength(k)

        clean_role = r.strip().lower()
        if clean_role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{r}' in ALGO_LAB_API_KEYS_JSON. Permitted roles: {sorted(VALID_ROLES)}"
            )
        validated[k] = clean_role

    return validated


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Core metadata
    PROJECT_NAME: str = "Algo Lab Quantitative Research OS"
    PROJECT_VERSION: str = SEMANTIC_VERSION
    LIFECYCLE_STATE: str = CURRENT_LIFECYCLE_STATE.value
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Server binding
    API_HOST: str = "0.0.0.0"  # nosec B104
    API_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Security Configuration & Scoped RBAC Keys
    ALGO_LAB_API_KEY: str = ""
    ALGO_LAB_API_KEY_SYSTEM_ADMIN: str = ""
    ALGO_LAB_API_KEY_ADMIN: str = ""
    ALGO_LAB_API_KEY_RISK_ADMIN: str = ""
    ALGO_LAB_API_KEY_OPERATOR: str = ""
    ALGO_LAB_API_KEY_RESEARCHER: str = ""
    ALGO_LAB_API_KEY_VIEWER: str = ""
    ALGO_LAB_API_KEY_READER: str = ""
    ALGO_LAB_API_KEYS_JSON: str = ""
    CIRCUIT_BREAKER_REARM_SECRET: str = ""
    CIRCUIT_BREAKER_STATE_KEY: str = ""
    CIRCUIT_BREAKER_STATE_PATH: str = "data/circuit_breaker_state.json"
    BROKER_CREDENTIAL_ENCRYPTION_KEY: str = ""
    ALLOW_LOCAL_AUTH_BYPASS: bool = False

    # Request Protections & Rate Limiting
    REQUEST_BODY_MAX_BYTES: int = 2 * 1024 * 1024  # 2MB max request body
    REQUEST_TIMEOUT_SECONDS: float = 30.0           # 30s request execution timeout
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120       # 120 requests/minute default rate limit

    # Database
    POSTGRES_USER: str = "algolab"
    POSTGRES_PASSWORD: str = "dev_db_password"
    POSTGRES_DB: str = "algolab"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://algolab:dev_db_password@localhost:5432/algolab"
    DATABASE_URL_SYNC: str = "postgresql://algolab:dev_db_password@localhost:5432/algolab"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "text"

    # NON-NEGOTIABLE SAFETY CONSTRAINTS
    ALLOW_LIVE_TRADING: bool = Field(
        default=False,
        description="Strictly disallow live trading execution during research & development.",
    )
    ALLOW_REAL_BROKER_EXECUTION: bool = Field(
        default=False,
        description="Never allow connection to real broker accounts for automated execution.",
    )
    REQUIRE_DATA_VALIDATION: bool = Field(
        default=True,
        description="Mandate that corrupted or unvalidated data rejects strategy calculations.",
    )
    ENFORCE_STRICT_LOOKAHEAD_PROTECTION: bool = Field(
        default=True,
        description="Mandate that all backtests only use data available strictly at or before decision time.",
    )

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_and_normalize_environment(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"Unknown environment '{v}'. Permitted modes: {sorted(set(VALID_ENVIRONMENTS.values()))}"
            )
        return VALID_ENVIRONMENTS[clean]

    @field_validator("ALLOW_LIVE_TRADING", "ALLOW_REAL_BROKER_EXECUTION")
    @classmethod
    def validate_safety_lock(cls, v: bool) -> bool:
        if v is True:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: Algo Lab Stage 1 prohibits enabling live trading or real broker execution."
            )
        return False

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        """Validate all security credentials, JSON role map, and production requirements."""
        # 1. Reject placeholder secrets in individual configuration fields if non-empty
        for field_name in (
            "CIRCUIT_BREAKER_REARM_SECRET",
            "CIRCUIT_BREAKER_STATE_KEY",
            "BROKER_CREDENTIAL_ENCRYPTION_KEY",
            "ALGO_LAB_API_KEY",
            "ALGO_LAB_API_KEY_ADMIN",
            "ALGO_LAB_API_KEY_OPERATOR",
            "ALGO_LAB_API_KEY_RESEARCHER",
            "ALGO_LAB_API_KEY_READER",
        ):
            val = getattr(self, field_name, None)
            if val and str(val).strip():
                if is_known_placeholder(val):
                    raise ValueError(f"{field_name} contains a known placeholder secret.")

        # 2. Parse and validate ALGO_LAB_API_KEYS_JSON
        json_keys = parse_and_validate_api_keys_json(self.ALGO_LAB_API_KEYS_JSON)

        # 3. Check for conflicting roles across credentials
        key_to_role: Dict[str, str] = dict(json_keys)
        env_role_assignments = [
            ("ALGO_LAB_API_KEY_READER", "reader"),
            ("ALGO_LAB_API_KEY_RESEARCHER", "researcher"),
            ("ALGO_LAB_API_KEY_OPERATOR", "operator"),
            ("ALGO_LAB_API_KEY_ADMIN", "administrator"),
            ("ALGO_LAB_API_KEY", "administrator"),
        ]
        for field_name, role_name in env_role_assignments:
            val = getattr(self, field_name, None)
            if val and str(val).strip():
                clean_key = str(val).strip()
                if clean_key in key_to_role and key_to_role[clean_key] != role_name:
                    raise ValueError("Conflicting roles configured for the same API key.")
                key_to_role[clean_key] = role_name

        # 4. Fail closed in production if required security credentials are missing or placeholders
        if self.ENVIRONMENT == "production":
            if self.ALLOW_LOCAL_AUTH_BYPASS:
                raise ValueError(
                    "CRITICAL SECURITY VIOLATION: Local authentication bypass (ALLOW_LOCAL_AUTH_BYPASS=True) "
                    "cannot be enabled in production environment."
                )

            # CORS validation: explicit authorized origins, no wildcards (F01)
            if not self.CORS_ORIGINS:
                raise ValueError(
                    "Production startup failed: CORS_ORIGINS must contain explicit authorized origins."
                )
            if any(str(origin).strip() == "*" for origin in self.CORS_ORIGINS):
                raise ValueError(
                    "Production startup failed: CORS_ORIGINS cannot allow wildcard '*' in production."
                )

            admin_keys = [k for k, r in key_to_role.items() if r == "administrator"]
            admin_key = self.ALGO_LAB_API_KEY or self.ALGO_LAB_API_KEY_ADMIN
            if not admin_keys:
                if is_invalid_secret(admin_key):
                    raise ValueError(
                        "Production startup failed: ALGO_LAB_API_KEY must be a strong, non-placeholder secret."
                    )
                validate_key_strength(admin_key)
            for k in key_to_role:
                validate_key_strength(k)

            if is_invalid_secret(self.CIRCUIT_BREAKER_REARM_SECRET):
                raise ValueError(
                    "Production startup failed: CIRCUIT_BREAKER_REARM_SECRET must be configured."
                )
            validate_key_strength(self.CIRCUIT_BREAKER_REARM_SECRET)

            if is_invalid_secret(self.CIRCUIT_BREAKER_STATE_KEY):
                raise ValueError(
                    "Production startup failed: CIRCUIT_BREAKER_STATE_KEY must be configured."
                )
            validate_key_strength(self.CIRCUIT_BREAKER_STATE_KEY)

            if is_invalid_secret(self.BROKER_CREDENTIAL_ENCRYPTION_KEY):
                raise ValueError(
                    "Production startup failed: BROKER_CREDENTIAL_ENCRYPTION_KEY must be configured."
                )
            validate_key_strength(self.BROKER_CREDENTIAL_ENCRYPTION_KEY)

        return self

    def export_security_settings(self) -> Dict[str, Any]:
        """Export dictionary of validated security credentials and parameters."""
        return {
            "environment": self.ENVIRONMENT,
            "rearm_secret": self.CIRCUIT_BREAKER_REARM_SECRET,
            "state_integrity_key": self.CIRCUIT_BREAKER_STATE_KEY,
            "broker_credential_encryption_key": self.BROKER_CREDENTIAL_ENCRYPTION_KEY,
            "allow_local_auth_bypass": self.ALLOW_LOCAL_AUTH_BYPASS,
            "api_keys_json": self.ALGO_LAB_API_KEYS_JSON,
            "api_key": self.ALGO_LAB_API_KEY,
            "api_key_admin": self.ALGO_LAB_API_KEY_ADMIN,
            "api_key_operator": self.ALGO_LAB_API_KEY_OPERATOR,
            "api_key_researcher": self.ALGO_LAB_API_KEY_RESEARCHER,
            "api_key_reader": self.ALGO_LAB_API_KEY_READER,
        }


def export_security_settings(s: Optional[Settings] = None) -> Dict[str, Any]:
    """Helper to export validated security settings from settings instance or singleton."""
    target = s or settings
    return target.export_security_settings()


def get_security_settings(s: Optional[Settings] = None) -> Dict[str, Any]:
    """Alias for export_security_settings."""
    return export_security_settings(s)


settings = Settings()
