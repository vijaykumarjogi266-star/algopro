"""Algo Lab Core Configuration.

Enforces strict environment configuration, database connection parameters,
and non-negotiable safety constraints (e.g. no live trading, mandatory validation).
"""

from typing import List, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
}

VALID_ENVIRONMENTS = {
    "development": "development",
    "dev": "development",
    "testing": "testing",
    "test": "testing",
    "production": "production",
    "prod": "production",
    "staging": "production",
}


def is_invalid_secret(secret: Optional[str]) -> bool:
    """Return True if secret is empty, whitespace-only, or a known placeholder."""
    if secret is None:
        return True
    s = str(secret).strip()
    return not s or s in PLACEHOLDER_SECRETS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core metadata
    PROJECT_NAME: str = "Algo Lab Quantitative Research OS"
    PROJECT_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Server binding
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Security Configuration
    ALGO_LAB_API_KEY: str = ""
    ALGO_LAB_API_KEY_ADMIN: str = ""
    ALGO_LAB_API_KEY_OPERATOR: str = ""
    ALGO_LAB_API_KEY_RESEARCHER: str = ""
    ALGO_LAB_API_KEY_READER: str = ""
    ALGO_LAB_API_KEYS_JSON: str = ""
    CIRCUIT_BREAKER_REARM_SECRET: str = ""
    CIRCUIT_BREAKER_STATE_KEY: str = ""
    CIRCUIT_BREAKER_STATE_PATH: str = "data/circuit_breaker_state.json"
    BROKER_CREDENTIAL_ENCRYPTION_KEY: str = ""
    ALLOW_LOCAL_AUTH_BYPASS: bool = False

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
    def validate_production_security(self) -> "Settings":
        """Fail closed in production if required security credentials are missing or placeholders."""
        if self.ENVIRONMENT == "production":
            if self.ALLOW_LOCAL_AUTH_BYPASS:
                raise ValueError(
                    "CRITICAL SECURITY VIOLATION: Local authentication bypass (ALLOW_LOCAL_AUTH_BYPASS=True) "
                    "cannot be enabled in production environment."
                )

            admin_key = self.ALGO_LAB_API_KEY or self.ALGO_LAB_API_KEY_ADMIN
            if is_invalid_secret(admin_key):
                raise ValueError(
                    "Production startup failed: ALGO_LAB_API_KEY must be a strong, non-placeholder secret."
                )

            for role_key_name in (
                "ALGO_LAB_API_KEY_ADMIN",
                "ALGO_LAB_API_KEY_OPERATOR",
                "ALGO_LAB_API_KEY_RESEARCHER",
                "ALGO_LAB_API_KEY_READER",
            ):
                val = getattr(self, role_key_name, None)
                if val and str(val).strip() in PLACEHOLDER_SECRETS:
                    raise ValueError(
                        f"Production startup failed: {role_key_name} contains a known placeholder secret."
                    )

            if is_invalid_secret(self.CIRCUIT_BREAKER_REARM_SECRET):
                raise ValueError(
                    "Production startup failed: CIRCUIT_BREAKER_REARM_SECRET must be configured."
                )

            if is_invalid_secret(self.CIRCUIT_BREAKER_STATE_KEY):
                raise ValueError(
                    "Production startup failed: CIRCUIT_BREAKER_STATE_KEY must be configured."
                )

            if is_invalid_secret(self.BROKER_CREDENTIAL_ENCRYPTION_KEY):
                raise ValueError(
                    "Production startup failed: BROKER_CREDENTIAL_ENCRYPTION_KEY must be configured."
                )
        return self


settings = Settings()
