"""Integration tests for authoritative execution control wiring (T09–T12).

Tests:
T09: test_shared_breaker_blocks_paper_orders
T10: test_api_rearm_restores_paper_trading
T11: test_simulated_broker_uses_gateway_controls
T12: test_watchdog_and_rate_limit_integration
"""

import time
import pytest
from fastapi.testclient import TestClient

from apps.api.core.config import settings
from apps.api.main import app
from apps.api.routes.circuit_breaker import get_circuit_breaker, set_circuit_breaker
from apps.api.routes.paper_trading import get_paper_engine
from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    ExecutionOrder,
    OrderLifecycleState,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState
from services.execution_gateway.contracts import (
    CircuitBreakerConfig,
    CircuitBreakerTripped,
    RateLimitExceededError,
    WatchdogTimeoutError,
)
from services.paper_engine.adapters.base import SimulatedBrokerAdapter
from services.paper_engine.session import PaperTradingEngine, SessionStatus


ADMIN_KEY = "test_key_admin_0123456789abcdef"
OPERATOR_KEY = "test_key_operator_0123456789abcdef"
REARM_SECRET = "valid_test_rearm_secret_token_123"


@pytest.fixture(autouse=True)
def setup_security_and_shared_breaker(monkeypatch, tmp_path):
    """Configure security and wire fresh shared circuit breaker with temp state file."""
    state_file = str(tmp_path / "cb_state.json")
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_ADMIN", ADMIN_KEY)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_OPERATOR", OPERATOR_KEY)
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_REARM_SECRET", REARM_SECRET)
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_STATE_KEY", "test_integrity_key_12345678901234")
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_STATE_PATH", state_file)
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    config = CircuitBreakerConfig(
        rearm_secret=REARM_SECRET,
        state_integrity_key="test_integrity_key_12345678901234",
        max_order_rate_per_sec=10,
        watchdog_heartbeat_timeout_sec=0.1,
    )
    cb = CircuitBreakerEngine(config=config, state_file_path=state_file, initial_equity=100000.0)
    set_circuit_breaker(cb)

    paper = get_paper_engine()
    paper.circuit_breaker = cb
    yield cb
    # Teardown: reset clean circuit breaker to avoid test pollution
    clean_cb = CircuitBreakerEngine(initial_equity=100000.0)
    set_circuit_breaker(clean_cb)
    paper.circuit_breaker = clean_cb


def test_shared_breaker_blocks_paper_orders():
    """T09: Halted circuit breaker strictly blocks paper order submissions with 403."""
    client = TestClient(app)
    headers = {"X-API-Key": OPERATOR_KEY}

    # 1. Create and start a paper session
    res_sess = client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": "sess_halt_test",
            "strategy_id": "SMA_Cross",
            "universe": ["TCS"],
            "initial_capital": 500000.0,
        },
        headers=headers,
    )
    assert res_sess.status_code == 201
    sess_id = res_sess.json()["session_id"]

    res_start = client.post(f"/api/v1/paper-trading/sessions/{sess_id}/start", headers=headers)
    assert res_start.status_code == 200

    # 2. Trigger emergency halt on circuit breaker
    cb = get_circuit_breaker()
    cb.trigger_emergency_halt("MANUAL_TEST_KILLSWITCH")
    assert cb.is_halted is True

    # 3. Attempt to submit paper order
    res_order = client.post(
        f"/api/v1/paper-trading/sessions/{sess_id}/orders",
        json={
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 10,
            "price": 3500.0,
            "stop_loss": 3400.0,
        },
        headers=headers,
    )
    # Must fail with 403 Forbidden due to circuit breaker halt
    assert res_order.status_code == 403
    assert "Circuit breaker halt" in res_order.text

    # 4. Verify portfolio state was NOT mutated
    res_get = client.get(f"/api/v1/paper-trading/sessions/{sess_id}", headers=headers)
    assert res_get.status_code == 200
    portfolio = res_get.json()["portfolio"]
    assert portfolio["cash"] == 500000.0
    assert len(portfolio["positions"]) == 0


def test_api_rearm_restores_paper_trading():
    """T10: Administrative rearm restores circuit breaker to NORMAL and unblocks paper trading."""
    client = TestClient(app)
    op_headers = {"X-API-Key": OPERATOR_KEY}
    admin_headers = {"X-API-Key": ADMIN_KEY}

    # 1. Create and start paper session
    res_sess = client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": "sess_rearm_test",
            "strategy_id": "SMA_Cross",
            "universe": ["INFY"],
            "initial_capital": 500000.0,
        },
        headers=op_headers,
    )
    assert res_sess.status_code == 201
    sess_id = res_sess.json()["session_id"]

    client.post(f"/api/v1/paper-trading/sessions/{sess_id}/start", headers=op_headers)

    # 2. Halt circuit breaker
    cb = get_circuit_breaker()
    cb.trigger_emergency_halt("TEST_EMERGENCY_HALT")
    assert cb.is_halted is True

    # 3. Verify order blocked
    res_blocked = client.post(
        f"/api/v1/paper-trading/sessions/{sess_id}/orders",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1500.0, "stop_loss": 1450.0},
        headers=op_headers,
    )
    assert res_blocked.status_code == 403

    # 4. Rearm via administrative API endpoint
    res_rearm = client.post(
        "/api/v1/circuit-breaker/rearm",
        json={"rearm_token": REARM_SECRET},
        headers=admin_headers,
    )
    assert res_rearm.status_code == 200
    assert res_rearm.json()["status"] == "NORMAL"
    assert cb.is_halted is False

    # 5. Verify order now succeeds
    res_ok = client.post(
        f"/api/v1/paper-trading/sessions/{sess_id}/orders",
        json={"symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1500.0, "stop_loss": 1450.0},
        headers=op_headers,
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["status"] == "ORDER_FILLED"
    assert data["fill"] is not None


def test_simulated_broker_uses_gateway_controls():
    """T11: SimulatedBrokerAdapter validates circuit breaker state directly."""
    cb = get_circuit_breaker()
    adapter = SimulatedBrokerAdapter(circuit_breaker=cb)

    lifecycle = ExecutionLifecycleManager()
    order = lifecycle.propose_order(symbol="TCS", side=OrderSide.BUY, quantity=10, price=3000.0, stop_loss=2900.0)

    # When breaker is NORMAL -> order fills
    filled, fill = adapter.submit_paper_order(order, execution_price=3000.0)
    assert filled.state == OrderLifecycleState.ORDER_FILLED
    assert fill is not None

    # Trip breaker
    cb.trigger_emergency_halt("SIMULATED_BROKER_HALT_TEST")
    order2 = lifecycle.propose_order(symbol="INFY", side=OrderSide.BUY, quantity=5, price=1500.0, stop_loss=1450.0)

    # When breaker is halted -> raises CircuitBreakerTripped
    with pytest.raises(CircuitBreakerTripped) as exc_info:
        adapter.submit_paper_order(order2, execution_price=1500.0)
    assert "Execution gateway halted by circuit breaker" in str(exc_info.value)


def test_watchdog_and_rate_limit_integration():
    """T12: Monotonic watchdog timeout and 10 orders/sec rate limit trip controls."""
    cb = get_circuit_breaker()
    adapter = SimulatedBrokerAdapter(circuit_breaker=cb)
    lifecycle = ExecutionLifecycleManager()

    # 1. Rate Limit Test: Submit 10 orders within 1.0s window -> ok
    for i in range(10):
        cb.validate_rate_limit()

    # 11th order exceeds 10 orders/sec burst limit
    with pytest.raises(RateLimitExceededError):
        cb.validate_rate_limit()

    # 2. Watchdog Heartbeat Test: Heartbeat timeout trips halt
    time.sleep(0.15)  # watchdog timeout is set to 0.1s
    with pytest.raises(WatchdogTimeoutError):
        cb.check_watchdog()
    assert cb.is_halted is True
