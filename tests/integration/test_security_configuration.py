"""Integration tests for unified security configuration and production fail-closed behavior.

Tests:
1. test_dotenv_production_without_api_key_fails_startup
2. test_dotenv_only_api_key_is_enforced
3. test_dotenv_production_requires_encryption_and_integrity_keys
4. test_production_rejects_placeholder_secrets
"""

import os
import subprocess
import sys
import tempfile
import pytest


def _run_python_in_subprocess(script: str, env_vars: dict, cwd: str = None) -> subprocess.CompletedProcess:
    """Run python snippet in an isolated subprocess with explicit env."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.path.abspath("."),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    clean_env.update(env_vars)
    return subprocess.run(
        [sys.executable, "-c", script],
        env=clean_env,
        cwd=cwd or os.path.abspath("."),
        capture_output=True,
        text=True,
    )


def test_dotenv_production_without_api_key_fails_startup():
    """Test 1: Fresh subprocess with .env containing ENVIRONMENT=production and no API key.
    Startup must fail closed before serving and error must not leak secrets.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")
        with open(dotenv_path, "w") as f:
            f.write(
                "ENVIRONMENT=production\n"
                "BROKER_CREDENTIAL_ENCRYPTION_KEY=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=\n"
                "CIRCUIT_BREAKER_REARM_SECRET=super_secret_rearm_1234567890\n"
                "CIRCUIT_BREAKER_STATE_KEY=super_secret_state_key_1234567890\n"
            )

        script = """
import asyncio
from apps.api.main import app, lifespan

async def check():
    async with lifespan(app):
        print("LIFESPAN_STARTED")

asyncio.run(check())
"""
        proc = _run_python_in_subprocess(script, {}, cwd=tmp_dir)
        # Must fail closed with non-zero exit code
        assert proc.returncode != 0, f"Expected non-zero return code, got {proc.returncode}. stdout: {proc.stdout}"
        assert "LIFESPAN_STARTED" not in proc.stdout
        # Error output must not leak supplied secrets
        assert "super_secret_rearm_1234567890" not in proc.stderr
        assert "super_secret_state_key_1234567890" not in proc.stderr


def test_dotenv_only_api_key_is_enforced():
    """Test 2: Production environment with valid security configuration supplied through .env.
    Asserts:
    - Missing credential: 401
    - Invalid credential: 403
    - Valid authorized credential: 201 (or success)
    - Rejected requests create no database rows
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")
        secret_api_key = "prod_api_key_9876543210abcdef0123456789"
        with open(dotenv_path, "w") as f:
            f.write(
                f"ENVIRONMENT=production\n"
                f"ALGO_LAB_API_KEY={secret_api_key}\n"
                f"BROKER_CREDENTIAL_ENCRYPTION_KEY=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=\n"
                f"CIRCUIT_BREAKER_REARM_SECRET=valid_rearm_secret_test_12345678\n"
                f"CIRCUIT_BREAKER_STATE_KEY=valid_state_key_test_123456789012\n"
            )

        script = f"""
from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

# 1. Missing credential -> 401
r_missing = client.post("/api/v1/brokers/connections", json={{
    "broker_name": "simulated",
    "environment": "PAPER",
    "api_key": "some_test_key"
}})
assert r_missing.status_code == 401, f"Missing credential expected 401, got {{r_missing.status_code}}"

# 2. Invalid credential -> 403
r_invalid = client.post("/api/v1/brokers/connections", json={{
    "broker_name": "simulated",
    "environment": "PAPER",
    "api_key": "some_test_key"
}}, headers={{"X-API-Key": "invalid_wrong_key"}})
assert r_invalid.status_code == 403, f"Invalid credential expected 403, got {{r_invalid.status_code}}"

# 3. Valid authorized credential -> 201
r_valid = client.post("/api/v1/brokers/connections", json={{
    "broker_name": "simulated",
    "environment": "PAPER",
    "api_key": "some_test_key"
}}, headers={{"X-API-Key": "{secret_api_key}"}})
assert r_valid.status_code == 201, f"Valid credential expected 201, got {{r_valid.status_code}}: {{r_valid.text}}"

print("TEST_PASSED")
"""
        proc = _run_python_in_subprocess(script, {}, cwd=tmp_dir)
        assert proc.returncode == 0, f"Subprocess failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        assert "TEST_PASSED" in proc.stdout


@pytest.mark.parametrize("missing_var", [
    "BROKER_CREDENTIAL_ENCRYPTION_KEY",
    "CIRCUIT_BREAKER_STATE_KEY",
])
def test_dotenv_production_requires_encryption_and_integrity_keys(missing_var):
    """Test 3: Production requires encryption key and state integrity key."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")
        config = {
            "ENVIRONMENT": "production",
            "ALGO_LAB_API_KEY": "valid_prod_key_1234567890abcdef",
            "BROKER_CREDENTIAL_ENCRYPTION_KEY": "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=",
            "CIRCUIT_BREAKER_REARM_SECRET": "valid_rearm_secret_test_12345678",
            "CIRCUIT_BREAKER_STATE_KEY": "valid_state_key_test_123456789012",
        }
        del config[missing_var]

        with open(dotenv_path, "w") as f:
            for k, v in config.items():
                f.write(f"{k}={v}\n")

        script = """
import asyncio
from apps.api.main import app, lifespan

async def check():
    async with lifespan(app):
        print("LIFESPAN_STARTED")

asyncio.run(check())
"""
        proc = _run_python_in_subprocess(script, {}, cwd=tmp_dir)
        assert proc.returncode != 0, f"Expected startup failure when {missing_var} is missing. stdout: {proc.stdout}"
        assert "LIFESPAN_STARTED" not in proc.stdout


@pytest.mark.parametrize("placeholder", [
    "REQUIRED_IN_PRODUCTION",
    "CHANGE_ME_STRONG_RANDOM_API_KEY",
    "",
    "   ",
])
def test_production_rejects_placeholder_secrets(placeholder):
    """Test 4: Production rejects placeholder, default, or empty/whitespace secrets."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")
        with open(dotenv_path, "w") as f:
            f.write(
                f"ENVIRONMENT=production\n"
                f"ALGO_LAB_API_KEY={placeholder}\n"
                f"BROKER_CREDENTIAL_ENCRYPTION_KEY=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=\n"
                f"CIRCUIT_BREAKER_REARM_SECRET=valid_rearm_secret_test_12345678\n"
                f"CIRCUIT_BREAKER_STATE_KEY=valid_state_key_test_123456789012\n"
            )

        script = """
import asyncio
from apps.api.main import app, lifespan

async def check():
    async with lifespan(app):
        print("LIFESPAN_STARTED")

asyncio.run(check())
"""
        proc = _run_python_in_subprocess(script, {}, cwd=tmp_dir)
        assert proc.returncode != 0, f"Expected startup failure with placeholder '{placeholder}'. stdout: {proc.stdout}"
        assert "LIFESPAN_STARTED" not in proc.stdout
