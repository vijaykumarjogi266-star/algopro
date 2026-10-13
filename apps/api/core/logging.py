"""Algo Lab Structured Logging Module.

Provides JSON/structured logging with standard contextual fields:
timestamp, level, component, request_id, experiment_id, message.
"""

import logging
import os
import sys
from typing import Any, Dict
from pythonjsonlogger import json
from apps.api.core.config import settings


def redact_sensitive_secrets(text: str) -> str:
    """Redact sensitive configuration secrets and environment credentials from text."""
    if not text or not isinstance(text, str):
        return text

    secrets: set[str] = set()

    for attr in [
        "ALGO_LAB_API_KEY",
        "ALGO_LAB_API_KEY_ADMIN",
        "ALGO_LAB_API_KEY_OPERATOR",
        "ALGO_LAB_API_KEY_RESEARCHER",
        "ALGO_LAB_API_KEY_READER",
        "CIRCUIT_BREAKER_REARM_SECRET",
        "CIRCUIT_BREAKER_STATE_KEY",
        "BROKER_CREDENTIAL_ENCRYPTION_KEY",
    ]:
        val = getattr(settings, attr, None)
        if val and isinstance(val, str) and len(val.strip()) >= 4:
            secrets.add(val.strip())

    for env_name, env_val in os.environ.items():
        name_upper = env_name.upper()
        if any(term in name_upper for term in ("SECRET", "KEY", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")):
            if env_val and isinstance(env_val, str) and len(env_val.strip()) >= 4:
                v_clean = env_val.strip()
                if v_clean.lower() not in ("true", "false", "none", "null", "production", "development", "testing", "sandbox", "paper", "live"):
                    secrets.add(v_clean)

    redacted = text
    for s in sorted(secrets, key=len, reverse=True):
        if s in redacted:
            redacted = redacted.replace(s, "[REDACTED]")

    return redacted


class SecretRedactionFilter(logging.Filter):
    """Logging filter that ensures secrets are never logged in plain text."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and not record.args:
            record.msg = redact_sensitive_secrets(record.msg)
        if getattr(record, "exc_text", None):
            record.exc_text = redact_sensitive_secrets(record.exc_text)
        return True


class CustomJsonFormatter(json.JsonFormatter):
    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["environment"] = settings.ENVIRONMENT
        log_record["service"] = "algo-lab"

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact_sensitive_secrets(formatted)


class RedactingStandardFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact_sensitive_secrets(formatted)


_orig_excepthook = sys.excepthook


def _redacting_excepthook(exc_type, exc_value, exc_traceback):
    import traceback
    formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys.stderr.write(redact_sensitive_secrets(formatted))


sys.excepthook = _redacting_excepthook


def setup_logging() -> None:
    """Configures root logger according to settings."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(SecretRedactionFilter())

    if settings.LOG_FORMAT.lower() == "json":
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s"
        )
    else:
        formatter = RedactingStandardFormatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Silence excessively verbose external loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)



def get_logger(name: str) -> logging.Logger:
    """Convenience getter for namespaced loggers."""
    return logging.getLogger(name)

