"""Algo Lab Stage 5 Phase C: Experiment API Integration Tests.

Verifies:
1. Valid creation.
2. Invalid creation.
3. Missing / unknown dataset detection.
4. Invalid strategy detection.
5. Invalid parameters detection.
6. Validation failure handling.
7. Successful submission.
8. Duplicate submission (idempotency).
9. Status retrieval.
10. Completed result retrieval.
11. Failed execution visibility & risk reject audit.
12. Audit retrieval.
13. Concurrent requests handling.
14. Malformed requests handling.
15. Persistence failure handling.
16. Service restart / recovery persistence.
"""

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from apps.api.main import app
from apps.api.routes.experiments import set_service, get_service
from services.backtest_engine.service import BacktestService
from services.backtest_engine.persistence import BacktestRunStore
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits


@pytest.fixture
def fresh_service():
    """Provides a fresh isolated in-memory BacktestService for each test."""
    store = BacktestRunStore(":memory:")
    svc = BacktestService(store=store, max_workers=2)
    set_service(svc)
    yield svc


@pytest.fixture
async def client(fresh_service):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def make_valid_payload(name="API Test Experiment"):
    start = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    end = datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc)
    return {
        "name": name,
        "description": "Integration test payload",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "2026.09.14",
        "dataset_checksum": "f" * 64,
        "universe": ["NIFTY50", "RELIANCE"],
        "timeframe": "1d",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "parameters": {"fast_period": 10, "slow_period": 30},
        "risk_policy_version": "1.0.0",
        "initial_capital": 500000.0,
        "seed": 42,
        "code_revision": "main",
    }


@pytest.mark.asyncio
async def test_valid_creation(client: AsyncClient):
    payload = make_valid_payload()
    res = await client.post("/api/v1/experiments", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == payload["name"]
    assert "experiment_id" in data
    assert len(data["fingerprint"]) == 64
    assert data["status"] == "CREATED"


@pytest.mark.asyncio
async def test_invalid_creation_dates(client: AsyncClient):
    payload = make_valid_payload()
    payload["start_date"] = payload["end_date"]  # Invalid dates
    res = await client.post("/api/v1/experiments", json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_missing_dataset(client: AsyncClient):
    payload = make_valid_payload()
    payload["dataset_id"] = "NON_EXISTENT_DATASET"
    res = await client.post("/api/v1/experiments/validate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert any("Unknown or missing dataset" in e for e in data["errors"])


@pytest.mark.asyncio
async def test_invalid_strategy(client: AsyncClient):
    payload = make_valid_payload()
    payload["strategy_id"] = "UNKNOWN_STRAT"
    res = await client.post("/api/v1/experiments/validate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert any("Invalid strategy" in e for e in data["errors"])


@pytest.mark.asyncio
async def test_invalid_parameters(client: AsyncClient):
    payload = make_valid_payload()
    payload["parameters"] = {"fast_period": 50, "slow_period": 20}  # fast >= slow
    res = await client.post("/api/v1/experiments/validate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert any("fast_period" in e for e in data["errors"])


@pytest.mark.asyncio
async def test_validation_failure_blocks_creation(client: AsyncClient):
    payload = make_valid_payload()
    payload["strategy_id"] = "INVALID_ALPHA"
    res = await client.post("/api/v1/experiments", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "errors" in data["detail"]


@pytest.mark.asyncio
async def test_successful_submission_and_lifecycle(client: AsyncClient):
    # 1. Create
    payload = make_valid_payload("Async Lifecycle Test")
    c_res = await client.post("/api/v1/experiments", json=payload)
    assert c_res.status_code == 201
    exp_id = c_res.json()["experiment_id"]

    # 2. Submit
    s_res = await client.post(f"/api/v1/experiments/{exp_id}/submit")
    assert s_res.status_code == 200
    s_data = s_res.json()
    assert s_data["status"] == "submitted"
    assert s_data["is_idempotent_duplicate"] is False
    run_id = s_data["run_id"]

    # 3. Poll for completion
    completed = False
    for _ in range(30):
        st_res = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}")
        assert st_res.status_code == 200
        if st_res.json()["status"] in ("COMPLETED", "FAILED"):
            completed = True
            break
        await asyncio.sleep(0.05)

    assert completed is True


@pytest.mark.asyncio
async def test_duplicate_submission_idempotency(client: AsyncClient):
    payload = make_valid_payload("Idempotency Test")
    c_res = await client.post("/api/v1/experiments", json=payload)
    exp_id = c_res.json()["experiment_id"]

    # First submit
    sub1 = await client.post(f"/api/v1/experiments/{exp_id}/submit")
    assert sub1.status_code == 200
    assert sub1.json()["status"] == "submitted"

    # Second submit with idempotent=True
    sub2 = await client.post(f"/api/v1/experiments/{exp_id}/submit?idempotent=true")
    assert sub2.status_code == 200
    data2 = sub2.json()
    assert data2["status"] == "already_submitted"
    assert data2["is_idempotent_duplicate"] is True


@pytest.mark.asyncio
async def test_status_and_result_retrieval(client: AsyncClient):
    payload = make_valid_payload("Results Test")
    c_res = await client.post("/api/v1/experiments", json=payload)
    exp_id = c_res.json()["experiment_id"]

    sub = await client.post(f"/api/v1/experiments/{exp_id}/submit")
    run_id = sub.json()["run_id"]

    # Wait for completion
    for _ in range(30):
        st = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}")
        if st.json()["status"] == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    # Get results
    res = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}/results")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert data["metrics"] is not None
    assert "sharpe_ratio" in data["metrics"]
    assert "total_return_pct" in data["metrics"]


@pytest.mark.asyncio
async def test_failed_execution_visibility_and_audit(client: AsyncClient, fresh_service: BacktestService):
    # Configure RiskEngine with 1% max capital to guarantee rejection
    fresh_service.risk_engine = RiskEngine(HardRiskLimits(max_capital_per_trade_pct=0.01))

    payload = make_valid_payload("Risk Rejection Test")
    payload["initial_capital"] = 100000.0  # 1% is 1,000 INR; order is 10 * 2500 = 25,000 INR
    c_res = await client.post("/api/v1/experiments", json=payload)
    exp_id = c_res.json()["experiment_id"]

    sub = await client.post(f"/api/v1/experiments/{exp_id}/submit")
    run_id = sub.json()["run_id"]

    # Wait for completion
    for _ in range(30):
        st = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}")
        if st.json()["status"] == "FAILED":
            break
        await asyncio.sleep(0.05)

    final_st = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}")
    assert final_st.json()["status"] == "FAILED"

    # Verify audit contains RISK_REJECT / RISK_REJECTED
    audit_res = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()
    assert any(e["event_type"] in ("RISK_REJECT", "RISK_REJECTED") for e in events)


@pytest.mark.asyncio
async def test_audit_retrieval_ordering(client: AsyncClient):
    payload = make_valid_payload("Audit Order Test")
    c_res = await client.post("/api/v1/experiments", json=payload)
    exp_id = c_res.json()["experiment_id"]

    sub = await client.post(f"/api/v1/experiments/{exp_id}/submit")
    run_id = sub.json()["run_id"]

    # Wait for completion
    for _ in range(30):
        st = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}")
        if st.json()["status"] == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    audit_res = await client.get(f"/api/v1/experiments/{exp_id}/runs/{run_id}/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()
    assert len(events) >= 2
    assert events[0]["event_type"] == "JOB_STARTED"


@pytest.mark.asyncio
async def test_concurrent_requests(client: AsyncClient):
    async def create_and_submit(idx):
        payload = make_valid_payload(f"Concurrent Test {idx}")
        c = await client.post("/api/v1/experiments", json=payload)
        exp_id = c.json()["experiment_id"]
        s = await client.post(f"/api/v1/experiments/{exp_id}/submit")
        return s.json()["experiment_id"]

    results = await asyncio.gather(*(create_and_submit(i) for i in range(5)))
    assert len(results) == 5
    assert len(set(results)) == 5  # All unique


@pytest.mark.asyncio
async def test_malformed_requests(client: AsyncClient):
    # Empty body
    res1 = await client.post("/api/v1/experiments", content="not json", headers={"Content-Type": "application/json"})
    assert res1.status_code == 422

    # Missing required name
    bad_payload = make_valid_payload()
    del bad_payload["name"]
    res2 = await client.post("/api/v1/experiments", json=bad_payload)
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_persistence_failure_handling(client: AsyncClient, fresh_service: BacktestService):
    with patch.object(fresh_service.store, "save_experiment", side_effect=Exception("Disk full")):
        payload = make_valid_payload("Failure Test")
        res = await client.post("/api/v1/experiments", json=payload)
        assert res.status_code == 500
        assert "Persistence failure" in res.json()["detail"]


@pytest.mark.asyncio
async def test_service_restart_recovery(client: AsyncClient, tmp_path):
    # Use persistent SQLite file
    db_file = str(tmp_path / "test_persist.db")
    store1 = BacktestRunStore(db_file)
    svc1 = BacktestService(store=store1)
    set_service(svc1)

    payload = make_valid_payload("Restart Test")
    c_res = await client.post("/api/v1/experiments", json=payload)
    exp_id = c_res.json()["experiment_id"]

    # Simulate service restart: instantiate fresh service with same db_file
    store2 = BacktestRunStore(db_file)
    svc2 = BacktestService(store=store2)
    set_service(svc2)

    # Verify experiment is still retrieved
    get_res = await client.get(f"/api/v1/experiments/{exp_id}")
    assert get_res.status_code == 200
    assert get_res.json()["experiment_id"] == exp_id
