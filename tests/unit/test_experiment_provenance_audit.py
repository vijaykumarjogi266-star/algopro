"""Tests verifying Experiment Provenance & Audit Integration (Phase G).

Adheres to Non-Negotiable Invariants:
- Principle 7: Every backtest must be reproducible.
- Principle 8: Every strategy must be versioned.
- Principle 9: Every dataset must be versioned.
- Principle 10: Every experiment must be auditable.
- Complete lifecycle audit sequence: Signal -> Proposal -> Risk -> Fill -> State.
- Risk rejections must be auditable with explicit reasons.
- Strict Read-Only: Audit trails are strictly append-only; no modification or deletion.
"""

import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from services.backtest_engine.contracts import (
    ExperimentDefinition,
    ExperimentStatus,
    CostModelConfig,
    SlippageModelConfig,
)
from services.backtest_engine.service import BacktestService
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from services.risk_engine.engine import RiskEngine
from apps.api.main import app
from apps.api.routes.experiments import set_service


def make_experiment(
    experiment_id: str = "exp_audit_001",
    name: str = "Audit Trail Verification",
    strategy_id: str = "Canonical_SMA",
    strategy_version: str = "1.0.0",
    dataset_id: str = "NSE_NIFTY50_DAILY",
    dataset_version: str = "2026.09.14",
    dataset_checksum: str = "a" * 64,
    initial_capital: float = 500_000.0,
) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id=experiment_id,
        name=name,
        description="Testing complete provenance and audit chain",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_checksum=dataset_checksum,
        universe=["NIFTY50", "RELIANCE"],
        timeframe="1d",
        start_date=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        end_date=datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc),
        parameters={"fast_period": 10, "slow_period": 30},
        risk_policy_version="1.0.0",
        cost_model=CostModelConfig(),
        slippage_model=SlippageModelConfig(),
        initial_capital=initial_capital,
        seed=42,
        code_revision="main",
    )


def test_lifecycle_audit_event_sequence():
    """Verifies complete chronological event sequence: Signal -> Proposal -> Risk -> Fill -> State."""
    service = BacktestService()
    exp = make_experiment(experiment_id="exp_seq_001")
    service.store.save_experiment(exp)

    res = service.submit_experiment(exp, idempotent=False)
    run_id = res["run_id"]

    # Wait for async execution
    for _ in range(50):
        status = service.get_run_status(run_id)
        if status and status["status"] in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.05)

    assert service.get_run_status(run_id)["status"] == "COMPLETED"

    events = service.get_audit_trail(run_id)
    event_types = [e["event_type"] for e in events]

    expected_sequence = [
        "JOB_STARTED",
        "SIGNAL_GENERATED",
        "ORDER_PROPOSED",
        "RISK_CHECK_EVALUATED",
        "ORDER_FILLED",
        "PORTFOLIO_STATE_UPDATED",
        "JOB_COMPLETED",
    ]

    for expected_type in expected_sequence:
        assert expected_type in event_types, f"Expected audit event '{expected_type}' not found in trail: {event_types}"

    # Verify chronological ordering
    indices = [event_types.index(t) for t in expected_sequence]
    assert indices == sorted(indices), f"Audit events are not in strictly monotonic chronological order: {event_types}"


def test_risk_rejection_audit_visibility():
    """Verifies that risk rejection records explicit failure code and reason without corrupting state."""
    # Configured with strict max capital limit (0.01 = 1.0% of 500k = 5,000 INR max capital)
    # The simulated trade of 10 shares * 2500 INR = 25,000 INR will trigger EXCEEDS_MAX_CAPITAL
    strict_risk = RiskEngine(HardRiskLimits(max_capital_per_trade_pct=0.01))
    service = BacktestService(risk_engine=strict_risk)

    exp = make_experiment(experiment_id="exp_risk_rej_001")
    service.store.save_experiment(exp)

    res = service.submit_experiment(exp, idempotent=False)
    run_id = res["run_id"]

    # Wait for execution
    for _ in range(50):
        status = service.get_run_status(run_id)
        if status and status["status"] in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.05)

    assert service.get_run_status(run_id)["status"] == "FAILED"

    events = service.get_audit_trail(run_id)
    event_types = [e["event_type"] for e in events]

    assert "RISK_REJECTED" in event_types
    reject_event = next(e for e in events if e["event_type"] == "RISK_REJECTED")
    assert reject_event["payload"]["code"] == RiskRejectionCode.EXCEEDS_MAX_CAPITAL.value
    assert "exceeds max trade limit" in reject_event["payload"]["reason"]

    # Assert no order fill occurred
    assert "ORDER_FILLED" not in event_types
    assert "PORTFOLIO_STATE_UPDATED" not in event_types


def test_api_provenance_endpoint():
    """Verifies GET /api/v1/experiments/{experiment_id}/provenance endpoint."""
    service = BacktestService()
    set_service(service)
    client = TestClient(app)

    exp = make_experiment(experiment_id="exp_prov_001")
    service.store.save_experiment(exp)

    # 1. Successful provenance retrieval
    res = client.get(f"/api/v1/experiments/{exp.experiment_id}/provenance")
    assert res.status_code == 200
    data = res.json()

    assert data["experiment_id"] == exp.experiment_id
    assert data["name"] == exp.name
    assert data["strategy_id"] == exp.strategy_id
    assert data["strategy_version"] == exp.strategy_version
    assert data["dataset_id"] == exp.dataset_id
    assert data["dataset_version"] == exp.dataset_version
    assert data["dataset_checksum"] == exp.dataset_checksum
    assert data["fingerprint"] == exp.fingerprint
    assert data["is_read_only"] is True
    assert "reproducibility_hash" in data
    assert "indicator_versions" in data

    # 2. Non-existent experiment 404
    err_res = client.get("/api/v1/experiments/nonexistent_experiment/provenance")
    assert err_res.status_code == 404


def test_api_audit_trail_endpoint():
    """Verifies GET /api/v1/experiments/{experiment_id}/runs/{run_id}/audit endpoint."""
    service = BacktestService()
    set_service(service)
    client = TestClient(app)

    exp = make_experiment(experiment_id="exp_audit_api_001")
    service.store.save_experiment(exp)

    submit_res = client.post(f"/api/v1/experiments/{exp.experiment_id}/submit")
    assert submit_res.status_code == 200
    run_id = submit_res.json()["run_id"]

    # Wait for completion
    for _ in range(50):
        st = client.get(f"/api/v1/experiments/{exp.experiment_id}/runs/{run_id}").json()
        if st["status"] in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.05)

    res = client.get(f"/api/v1/experiments/{exp.experiment_id}/runs/{run_id}/audit")
    assert res.status_code == 200
    events = res.json()
    assert len(events) >= 5

    # Check structure
    for ev in events:
        assert "timestamp" in ev
        assert "event_type" in ev
        assert "payload" in ev
        assert isinstance(ev["payload"], dict)

    # 404 on invalid run ID
    err_res = client.get(f"/api/v1/experiments/{exp.experiment_id}/runs/invalid_run_id/audit")
    assert err_res.status_code == 404


def test_audit_ledger_read_only_invariants():
    """Verifies that no endpoints exist allowing modification, deletion, or tampering with audit events."""
    client = TestClient(app)

    # Attempt PUT, PATCH, DELETE on audit trail
    put_res = client.put("/api/v1/experiments/exp_01/runs/exp_01/audit")
    assert put_res.status_code in (404, 405)

    patch_res = client.patch("/api/v1/experiments/exp_01/runs/exp_01/audit")
    assert patch_res.status_code in (404, 405)

    del_res = client.delete("/api/v1/experiments/exp_01/runs/exp_01/audit")
    assert del_res.status_code in (404, 405)
