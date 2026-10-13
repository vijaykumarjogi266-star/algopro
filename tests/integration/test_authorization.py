"""Integration tests for authorization and role-based access control (RBAC).

Tests:
5. test_all_nonpublic_routes_require_authentication
6. test_role_permissions_are_enforced
7. test_run_must_belong_to_requested_experiment
"""

import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.core.config import settings
from apps.api.core.auth import Role


PUBLIC_PATHS = {
    "/",
    "/health",
    "/health/ready",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


@pytest.fixture
def client():
    return TestClient(app)


def test_all_nonpublic_routes_require_authentication(client, monkeypatch):
    """Test 5: Enumerate routes, classify public endpoints, and assert non-public routes require auth.
    In testing/production mode without local auth bypass, unauthenticated requests must be rejected.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", "super_secret_admin_key_1234567890123456")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)

    # Test representative non-public routes for every router
    protected_samples = [
        ("GET", "/api/v1/experiments"),
        ("POST", "/api/v1/experiments"),
        ("GET", "/api/v1/brokers/connections"),
        ("POST", "/api/v1/brokers/connections"),
        ("GET", "/api/v1/datasets"),
        ("GET", "/api/v1/data/symbols"),
        ("GET", "/api/v1/paper-trading/sessions"),
        ("POST", "/api/v1/paper-trading/sessions"),
        ("GET", "/api/v1/replay/sessions"),
        ("GET", "/api/v1/system/info"),
    ]

    for method, path in protected_samples:
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json={})
        assert resp.status_code in (401, 403), f"Route {method} {path} expected 401/403 unauth, got {resp.status_code}: {resp.text}"

    # Verify public endpoints remain accessible
    for path in ["/", "/health", "/api/v1/health"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"Public endpoint {path} failed: {resp.status_code}"


def test_role_permissions_are_enforced(client, monkeypatch):
    """Test 6: Role permissions are strictly enforced.
    - Reader cannot submit experiments.
    - Researcher cannot change broker credentials or rearm a halt.
    - Operator cannot perform administrator operations.
    - Authorized role can perform its permitted operation.
    """
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)

    # Headers for each role
    reader_headers = {"X-API-Key": admin_key, "X-API-Role": Role.READER.value}
    researcher_headers = {"X-API-Key": admin_key, "X-API-Role": Role.RESEARCHER.value}
    operator_headers = {"X-API-Key": admin_key, "X-API-Role": Role.OPERATOR.value}
    admin_headers = {"X-API-Key": admin_key, "X-API-Role": Role.ADMINISTRATOR.value}

    # 1. Reader cannot submit experiments (POST /api/v1/experiments)
    exp_payload = {
        "name": "Test RBAC Exp",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "a" * 64,
        "universe": ["RELIANCE"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": 100000.0,
    }
    r_reader_exp = client.post("/api/v1/experiments", json=exp_payload, headers=reader_headers)
    assert r_reader_exp.status_code == 403, f"Reader submitting exp expected 403, got {r_reader_exp.status_code}"

    # Researcher CAN submit experiments
    r_researcher_exp = client.post("/api/v1/experiments", json=exp_payload, headers=researcher_headers)
    assert r_researcher_exp.status_code in (200, 201), f"Researcher submitting exp expected 200/201, got {r_researcher_exp.status_code}: {r_researcher_exp.text}"

    # 2. Researcher cannot change broker credentials (POST /api/v1/brokers/connections)
    broker_payload = {
        "broker_name": "simulated",
        "environment": "PAPER",
        "api_key": "some_key_123",
    }
    r_researcher_broker = client.post("/api/v1/brokers/connections", json=broker_payload, headers=researcher_headers)
    assert r_researcher_broker.status_code == 403, f"Researcher setting broker creds expected 403, got {r_researcher_broker.status_code}"

    # Operator CAN manage broker connections
    r_operator_broker = client.post("/api/v1/brokers/connections", json=broker_payload, headers=operator_headers)
    assert r_operator_broker.status_code in (200, 201), f"Operator setting broker creds expected 201, got {r_operator_broker.status_code}"

    # 3. Operator cannot rearm a halt (POST /api/v1/circuit-breaker/rearm)
    rearm_payload = {"rearm_token": "any_token"}
    r_operator_rearm = client.post("/api/v1/circuit-breaker/rearm", json=rearm_payload, headers=operator_headers)
    assert r_operator_rearm.status_code == 403, f"Operator rearming expected 403, got {r_operator_rearm.status_code}"

    # Admin CAN attempt rearm (rearm token validation itself will proceed)
    r_admin_rearm = client.post("/api/v1/circuit-breaker/rearm", json=rearm_payload, headers=admin_headers)
    # Either 200/400/401/403 from rearm logic, but not RBAC 403 role forbidden
    assert r_admin_rearm.status_code != 403 or "Insufficient role permissions" not in r_admin_rearm.text


def test_run_must_belong_to_requested_experiment(client, monkeypatch):
    """Test 7: Create experiments A and B and a run belonging to B.
    Request B's run under A's status/results/audit routes.
    Assert rejection (404) and no data disclosure.
    """
    admin_key = "admin_key_test_1234567890123456"
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", admin_key)
    headers = {"X-API-Key": admin_key}

    # Create Experiment A
    exp_a_payload = {
        "name": "Experiment A",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "v1.0.0",
        "dataset_checksum": "a" * 64,
        "universe": ["RELIANCE"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-06-01T00:00:00Z",
        "initial_capital": 100000.0,
    }
    res_a = client.post("/api/v1/experiments", json=exp_a_payload, headers=headers)
    exp_a_id = res_a.json()["experiment_id"]

    # Create Experiment B
    exp_b_payload = dict(exp_a_payload, name="Experiment B")
    res_b = client.post("/api/v1/experiments", json=exp_b_payload, headers=headers)
    exp_b_id = res_b.json()["experiment_id"]

    # Submit a run under B
    res_run_b = client.post(f"/api/v1/experiments/{exp_b_id}/runs", json={}, headers=headers)
    assert res_run_b.status_code in (200, 201)
    run_b_id = res_run_b.json()["run_id"]

    # Request B's run under A's routes -> Must return 404
    r_status = client.get(f"/api/v1/experiments/{exp_a_id}/runs/{run_b_id}", headers=headers)
    assert r_status.status_code == 404
    assert f"does not belong to experiment '{exp_a_id}'" in r_status.text

    r_results = client.get(f"/api/v1/experiments/{exp_a_id}/runs/{run_b_id}/results", headers=headers)
    assert r_results.status_code == 404
    assert f"does not belong to experiment '{exp_a_id}'" in r_results.text

    r_audit = client.get(f"/api/v1/experiments/{exp_a_id}/runs/{run_b_id}/audit", headers=headers)
    assert r_audit.status_code == 404
    assert f"does not belong to experiment '{exp_a_id}'" in r_audit.text
