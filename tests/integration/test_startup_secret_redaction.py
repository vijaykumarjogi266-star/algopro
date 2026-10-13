"""Integration test for secret redaction upon production startup failure.

Tests:
T29: test_startup_failure_redacts_credentials_from_output
"""

import os
import subprocess
import sys
import tempfile
import pytest


def _run_subprocess(script: str, env_vars: dict, cwd: str = None) -> subprocess.CompletedProcess:
    """Run python script in an isolated subprocess with explicit env."""
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


CANARY_API_KEY = "CANARY_SECRET_API_KEY_abcdef1234567890"
CANARY_REARM_SECRET = "CANARY_SECRET_REARM_uvwxyz1234567890"
CANARY_STATE_KEY = "CANARY_SECRET_STATE_KEY_9876543210zyx"
CANARY_ENCRYPTION_KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="


@pytest.mark.parametrize("failure_trigger", [
    "invalid_config",
    "port_error",
    "lifespan_error",
])
def test_startup_failure_redacts_credentials_from_output(failure_trigger):
    """T29: Trigger production startup failure while secrets are set in env.
    Verify stdout/stderr contains NO supplied secret values.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")

        if failure_trigger == "invalid_config":
            # Invalid placeholder encryption key triggers fail-closed in production
            env_vars = {
                "ENVIRONMENT": "production",
                "ALGO_LAB_API_KEY": CANARY_API_KEY,
                "CIRCUIT_BREAKER_REARM_SECRET": CANARY_REARM_SECRET,
                "CIRCUIT_BREAKER_STATE_KEY": CANARY_STATE_KEY,
                "BROKER_CREDENTIAL_ENCRYPTION_KEY": "CHANGE_ME_ENCRYPTION_KEY",
            }
            script = """
import asyncio
from apps.api.main import app, lifespan

async def run():
    async with lifespan(app):
        print("STARTED")

asyncio.run(run())
"""

        elif failure_trigger == "port_error":
            # Socket bind error / port collision simulation
            env_vars = {
                "ENVIRONMENT": "production",
                "ALGO_LAB_API_KEY": CANARY_API_KEY,
                "CIRCUIT_BREAKER_REARM_SECRET": CANARY_REARM_SECRET,
                "CIRCUIT_BREAKER_STATE_KEY": CANARY_STATE_KEY,
                "BROKER_CREDENTIAL_ENCRYPTION_KEY": CANARY_ENCRYPTION_KEY,
            }
            script = f"""
import socket
import uvicorn
from apps.api.main import app

# Bind a port to create an intentional port conflict error
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('127.0.0.1', 0))
port = s.getsockname()[1]

# Attempting to bind to the same port must raise an error containing potential config context
config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error')
server = uvicorn.Server(config)
try:
    server.run()
finally:
    s.close()
"""

        elif failure_trigger == "lifespan_error":
            # Direct runtime error inside startup hook that echoes environment
            env_vars = {
                "ENVIRONMENT": "production",
                "ALGO_LAB_API_KEY": CANARY_API_KEY,
                "CIRCUIT_BREAKER_REARM_SECRET": CANARY_REARM_SECRET,
                "CIRCUIT_BREAKER_STATE_KEY": CANARY_STATE_KEY,
                "BROKER_CREDENTIAL_ENCRYPTION_KEY": CANARY_ENCRYPTION_KEY,
            }
            script = f"""
import asyncio
from apps.api.main import app, lifespan

# Simulate an internal service error that might include config strings
raise RuntimeError("Fatal database connection failed with secret {CANARY_API_KEY} and {CANARY_REARM_SECRET}")
"""

        proc = _run_subprocess(script, env_vars, cwd=tmp_dir)

        # Startup must have failed (non-zero return code)
        assert proc.returncode != 0, f"Expected non-zero exit code, got {proc.returncode}. stdout: {proc.stdout}"

        combined_output = proc.stdout + "\n" + proc.stderr

        # Assert NO canary secrets appear in stdout or stderr
        assert CANARY_API_KEY not in combined_output, (
            f"ALGO_LAB_API_KEY leaked in output for trigger '{failure_trigger}':\n{combined_output}"
        )
        assert CANARY_REARM_SECRET not in combined_output, (
            f"CIRCUIT_BREAKER_REARM_SECRET leaked in output for trigger '{failure_trigger}':\n{combined_output}"
        )
        assert CANARY_STATE_KEY not in combined_output, (
            f"CIRCUIT_BREAKER_STATE_KEY leaked in output for trigger '{failure_trigger}':\n{combined_output}"
        )
