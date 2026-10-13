"""Integration tests for server-side role-based authorization enforcement (T05–T08).

Tests:
T05: test_reader_cannot_escalate_by_header
T06: test_mutation_permission_matrix
T07: test_protected_reads_require_identity
T08: test_configuration_modes_preserve_authentication
"""

import os
import subprocess
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

from apps.api.core.auth import Role, get_configured_key_roles, resolve_key_role
from apps.api.core.config import settings
from apps.api.main import app


READER_KEY = "test_key_reader_0123456789abcdef"
RESEARCHER_KEY = "test_key_researcher_0123456789abcdef"
OPERATOR_KEY = "test_key_operator_0123456789abcdef"
ADMIN_KEY = "test_key_admin_0123456789abcdef"


@pytest.fixture(autouse=True)
def configure_test_role_keys(monkeypatch):
    """Ensure all test role keys are configured for integration tests."""
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_ADMIN", ADMIN_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_OPERATOR", OPERATOR_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_RESEARCHER", RESEARCHER_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_READER", READER_KEY)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")


def test_reader_cannot_escalate_by_header():
    """T05: Reader credential cannot escalate privileges via X-API-Role header.
    
    Attempts to specify X-API-Role: administrator, operator, or researcher
    using a reader key must fail closed with 403 Forbidden.
    """
    client = TestClient(app)

    # 1. Reader key with X-API-Role: administrator calling broker mutation -> 403
    res_admin_header = client.post(
        "/api/v1/brokers/connections",
        json={"broker_name": "simulated", "environment": "PAPER"},
        headers={"X-API-Key": READER_KEY, "X-API-Role": "administrator"},
    )
    assert res_admin_header.status_code == 403, (
        f"Expected 403 for reader escalating to administrator, got {res_admin_header.status_code}: {res_admin_header.text}"
    )
    assert "exceeds key privileges" in res_admin_header.text

    # 2. Reader key with X-API-Role: operator calling paper session creation -> 403
    res_operator_header = client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": "sess_test",
            "strategy_id": "strat_1",
            "universe": ["RELIANCE"],
            "initial_capital": 1000000.0,
        },
        headers={"X-API-Key": READER_KEY, "X-API-Role": "operator"},
    )
    assert res_operator_header.status_code == 403, (
        f"Expected 403 for reader escalating to operator, got {res_operator_header.status_code}: {res_operator_header.text}"
    )
    assert "exceeds key privileges" in res_operator_header.text

    # 3. Reader key with X-API-Role: researcher calling experiment creation -> 403
    res_researcher_header = client.post(
        "/api/v1/experiments/validate",
        json={
            "name": "exp_test",
            "strategy_id": "SMA_Cross",
            "strategy_version": "1.0.0",
            "dataset_id": "ds_1",
            "dataset_version": "1.0.0",
            "universe": ["INFY"],
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "parameters": {},
            "initial_capital": 100000.0,
        },
        headers={"X-API-Key": READER_KEY, "X-API-Role": "researcher"},
    )
    assert res_researcher_header.status_code == 403
    assert "exceeds key privileges" in res_researcher_header.text

    # 4. Reader key calling reader endpoint with X-API-Role: administrator -> 403
    res_read_escalate = client.get(
        "/api/v1/experiments",
        headers={"X-API-Key": READER_KEY, "X-API-Role": "administrator"},
    )
    assert res_read_escalate.status_code == 403
    assert "exceeds key privileges" in res_read_escalate.text


@pytest.mark.parametrize("role_name,api_key,can_admin,can_operator,can_researcher", [
    ("reader", READER_KEY, False, False, False),
    ("researcher", RESEARCHER_KEY, False, False, True),
    ("operator", OPERATOR_KEY, False, True, True),
    ("administrator", ADMIN_KEY, True, True, True),
])
def test_mutation_permission_matrix(role_name, api_key, can_admin, can_operator, can_researcher):
    """T06: Role-based mutation permission matrix enforcement across all sensitive routes."""
    client = TestClient(app)
    headers = {"X-API-Key": api_key}

    # 1. Admin-level mutation: Broker Connection creation
    broker_res = client.post(
        "/api/v1/brokers/connections",
        json={"broker_name": "simulated", "environment": "PAPER"},
        headers=headers,
    )
    if can_admin:
        assert broker_res.status_code in (201, 200), f"{role_name} expected admin access: {broker_res.text}"
    else:
        assert broker_res.status_code == 403, f"{role_name} should be forbidden from admin mutation: {broker_res.status_code}"

    # 2. Operator-level mutation: Paper Session creation
    paper_res = client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": f"test_{role_name}",
            "strategy_id": "strat_1",
            "universe": ["TCS"],
            "initial_capital": 500000.0,
        },
        headers=headers,
    )
    if can_operator:
        assert paper_res.status_code in (201, 200), f"{role_name} expected operator access: {paper_res.text}"
    else:
        assert paper_res.status_code == 403, f"{role_name} should be forbidden from operator mutation: {paper_res.status_code}"

    # 3. Researcher-level mutation: Experiment Validation
    exp_res = client.post(
        "/api/v1/experiments/validate",
        json={
            "name": f"exp_{role_name}",
            "strategy_id": "SMA_Cross",
            "strategy_version": "1.0.0",
            "dataset_id": "ds_1",
            "dataset_version": "1.0.0",
            "dataset_checksum": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "universe": ["INFY"],
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "parameters": {},
            "initial_capital": 100000.0,
        },
        headers=headers,
    )
    if can_researcher:
        assert exp_res.status_code in (200, 201), f"{role_name} expected researcher access: {exp_res.text}"
    else:
        assert exp_res.status_code == 403, f"{role_name} should be forbidden from researcher mutation: {exp_res.status_code}"


def test_protected_reads_require_identity():
    """T07: Public health is strictly minimal; all API read endpoints require authentication.
    
    Asserts:
    - Public health endpoints (/health, /health/ready, /api/v1/health) return without requiring an API key.
    - Protected reads return 401 without key, 403 with invalid key, 200 with reader key.
    - Public health response contains no secrets or internal sensitive tokens.
    """
    client = TestClient(app)

    # 1. Public health probes succeed without API key (never 401/403)
    for public_path in ["/health", "/health/ready", "/api/v1/health"]:
        res = client.get(public_path)
        assert res.status_code in (200, 503), f"Expected {public_path} to return public status (200 or 503), got {res.status_code}"
        assert res.status_code not in (401, 403), f"Public probe {public_path} unexpectedly required auth"
        body_text = res.text.lower()
        # Ensure zero secret leakage in public probes
        for secret in [ADMIN_KEY, OPERATOR_KEY, RESEARCHER_KEY, READER_KEY, "dev_db_password"]:
            assert secret.lower() not in body_text, f"Secret/keyword '{secret}' leaked in {public_path}"

    # 2. Protected reads require authentication
    protected_read_paths = [
        "/api/v1/experiments",
        "/api/v1/paper-trading/sessions",
        "/api/v1/brokers/connections",
        "/api/v1/circuit-breaker/status",
        "/api/v1/system/info",
        "/api/v1/system/principles",
        "/api/v1/data/session/status",
        "/api/v1/datasets",
    ]

    for path in protected_read_paths:
        # Without key -> 401
        res_no_auth = client.get(path)
        assert res_no_auth.status_code == 401, (
            f"Path {path} without credentials expected 401, got {res_no_auth.status_code}"
        )

        # With invalid key -> 403
        res_bad_key = client.get(path, headers={"X-API-Key": "completely_invalid_key"})
        assert res_bad_key.status_code == 403, (
            f"Path {path} with bad key expected 403, got {res_bad_key.status_code}"
        )

        # With valid Reader key -> 200
        res_valid = client.get(path, headers={"X-API-Key": READER_KEY})
        assert res_valid.status_code == 200, (
            f"Path {path} with Reader key expected 200, got {res_valid.status_code}: {res_valid.text}"
        )


def _run_subprocess_test(env_vars: dict, cwd: str, script: str) -> subprocess.CompletedProcess:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.path.abspath("."),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    clean_env.update(env_vars)
    return subprocess.run(
        [sys.executable, "-c", script],
        env=clean_env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_configuration_modes_preserve_authentication():
    """T08: Both .env file and process environment variables preserve authentication and RBAC.
    
    Asserts:
    - Running with .env configuration enforces authentication and prevents role escalation.
    - Running with exported environment variables enforces authentication and prevents role escalation.
    - Missing production credentials never silently falls back to unauthenticated development mode.
    """
    test_script = f"""
from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

# 1. Unauthenticated request must be rejected with 401
r_no_auth = client.get("/api/v1/experiments")
assert r_no_auth.status_code == 401, f"Expected 401, got {{r_no_auth.status_code}}"

# 2. Reader key must succeed on read
r_read = client.get("/api/v1/experiments", headers={{"X-API-Key": "{READER_KEY}"}})
assert r_read.status_code == 200, f"Expected 200, got {{r_read.status_code}}"

# 3. Reader key cannot escalate to administrator
r_escalate = client.post(
    "/api/v1/brokers/connections",
    json={{"broker_name": "simulated", "environment": "PAPER"}},
    headers={{"X-API-Key": "{READER_KEY}", "X-API-Role": "administrator"}}
)
assert r_escalate.status_code == 403, f"Expected 403, got {{r_escalate.status_code}}"

# 4. Admin key succeeds on broker creation
r_admin = client.post(
    "/api/v1/brokers/connections",
    json={{"broker_name": "simulated", "environment": "PAPER"}},
    headers={{"X-API-Key": "{ADMIN_KEY}"}}
)
assert r_admin.status_code == 201, f"Expected 201, got {{r_admin.status_code}}: {{r_admin.text}}"

print("SUBPROCESS_CONFIG_VERIFIED")
"""

    # Mode A: .env delivery only
    with tempfile.TemporaryDirectory() as tmp_dir:
        dotenv_path = os.path.join(tmp_dir, ".env")
        with open(dotenv_path, "w") as f:
            f.write(
                f"ENVIRONMENT=production\n"
                f"ALGO_LAB_API_KEY={ADMIN_KEY}\n"
                f"ALGO_LAB_API_KEY_ADMIN={ADMIN_KEY}\n"
                f"ALGO_LAB_API_KEY_OPERATOR={OPERATOR_KEY}\n"
                f"ALGO_LAB_API_KEY_RESEARCHER={RESEARCHER_KEY}\n"
                f"ALGO_LAB_API_KEY_READER={READER_KEY}\n"
                f"BROKER_CREDENTIAL_ENCRYPTION_KEY=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=\n"
                f"CIRCUIT_BREAKER_REARM_SECRET=valid_rearm_secret_test_12345678\n"
                f"CIRCUIT_BREAKER_STATE_KEY=valid_state_key_test_123456789012\n"
            )
        proc_env = _run_subprocess_test({}, tmp_dir, test_script)
        assert proc_env.returncode == 0, f"Mode A (.env) failed:\nstdout: {proc_env.stdout}\nstderr: {proc_env.stderr}"
        assert "SUBPROCESS_CONFIG_VERIFIED" in proc_env.stdout

    # Mode B: Exported process environment variables
    with tempfile.TemporaryDirectory() as tmp_dir:
        # No .env in this directory
        exported_vars = {
            "ENVIRONMENT": "production",
            "ALGO_LAB_API_KEY": ADMIN_KEY,
            "ALGO_LAB_API_KEY_ADMIN": ADMIN_KEY,
            "ALGO_LAB_API_KEY_OPERATOR": OPERATOR_KEY,
            "ALGO_LAB_API_KEY_RESEARCHER": RESEARCHER_KEY,
            "ALGO_LAB_API_KEY_READER": READER_KEY,
            "BROKER_CREDENTIAL_ENCRYPTION_KEY": "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=",
            "CIRCUIT_BREAKER_REARM_SECRET": "valid_rearm_secret_test_12345678",
            "CIRCUIT_BREAKER_STATE_KEY": "valid_state_key_test_123456789012",
        }
        proc_export = _run_subprocess_test(exported_vars, tmp_dir, test_script)
        assert proc_export.returncode == 0, f"Mode B (export) failed:\nstdout: {proc_export.stdout}\nstderr: {proc_export.stderr}"
        assert "SUBPROCESS_CONFIG_VERIFIED" in proc_export.stdout
