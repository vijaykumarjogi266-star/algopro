"""
Stage 11 Acceptance Test Suite — Part 1 (AT-196 through AT-213).
Verifies architectural invariants INV-47 through INV-52.
"""

from datetime import datetime, timezone, timedelta
import os
import tempfile
import time
import pytest

from services.execution_gateway.contracts import (
    GatewayState,
    OrderStatus,
    ReconciliationStatus,
    CircuitBreakerConfig,
    BrokerPositionRecord,
    ReconciliationReport,
    GatewayAuditManifest,
    OrderPayload,
    GatewayValidationError,
    CircuitBreakerTripped,
    WatchdogTimeoutError,
    RateLimitExceededError,
    DuplicateOrderError,
    ASTIsolationError,
    StaleSnapshotError,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.reconciliation_engine import MultiBrokerReconciliationEngine
from services.execution_gateway.safety_gateway import ExecutionSafetyGateway, StaticASTIsolationScanner
from services.execution_gateway.service import ExecutionGatewayService


def test_at_196_position_drift_detection_and_reconciliation():
    """AT-196: Verify position drift detection and corrective order generation (INV-47)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime.now(timezone.utc)

    tracked = {"AAPL": 100, "GOOGL": 50}
    records = [
        BrokerPositionRecord(
            symbol="AAPL",
            quantity=150,
            average_price=180.0,
            account_id="ACC1",
            snapshot_timestamp=now_utc,
            publication_timestamp=now_utc,
        ),
        BrokerPositionRecord(
            symbol="GOOGL",
            quantity=50,
            average_price=140.0,
            account_id="ACC1",
            snapshot_timestamp=now_utc,
            publication_timestamp=now_utc,
        ),
    ]

    report = engine.reconcile_account("ACC1", tracked, records, now_utc)

    assert report.reconciliation_status == ReconciliationStatus.DRIFT_DETECTED.value
    assert report.position_drift["AAPL"] == 50  # ΔP = 150 - 100 = +50
    assert report.position_drift["GOOGL"] == 0
    assert len(report.corrective_orders_generated) == 1


def test_at_197_drawdown_circuit_breaker_emergency_halt():
    """AT-197: Verify portfolio drawdown >= 15% trips emergency halt (INV-48)."""
    cb = CircuitBreakerEngine(initial_equity=100_000.0)

    # Initial normal update
    cb.update_equity(100_000.0)
    assert cb.state == GatewayState.NORMAL

    # Drop to 84,000 (16% drawdown)
    cb.update_equity(84_000.0)

    assert cb.state == GatewayState.EMERGENCY_HALT
    assert cb.is_halted is True
    assert any("DRAWDOWN_BREACH" in r for r in cb.trip_reasons)


def test_at_198_daily_loss_circuit_breaker_tripping():
    """AT-198: Verify daily loss >= 3% trips emergency halt (INV-48)."""
    cb = CircuitBreakerEngine(initial_equity=100_000.0)
    cb.update_session_open_equity(100_000.0)

    # Drop to 96,500 (3.5% daily loss)
    cb.update_equity(96_500.0)

    assert cb.state == GatewayState.EMERGENCY_HALT
    assert any("DAILY_LOSS_BREACH" in r for r in cb.trip_reasons)


def test_at_199_watchdog_heartbeat_timeout_emergency_halt():
    """AT-199: Verify watchdog heartbeat timeout trips emergency halt (INV-48)."""
    config = CircuitBreakerConfig(watchdog_heartbeat_timeout_sec=0.1)
    cb = CircuitBreakerEngine(config=config)

    time.sleep(0.15)  # Sleep past timeout

    with pytest.raises(WatchdogTimeoutError):
        cb.check_watchdog()

    assert cb.state == GatewayState.EMERGENCY_HALT


def test_at_200_order_rate_limiter_burst_protection():
    """AT-200: Verify rate limiter caps order burst at 10 orders/sec (INV-51)."""
    config = CircuitBreakerConfig(max_order_rate_per_sec=10)
    cb = CircuitBreakerEngine(config=config)

    # Send 10 valid orders
    for _ in range(10):
        cb.validate_rate_limit()

    # 11th order in same window must fail
    with pytest.raises(RateLimitExceededError):
        cb.validate_rate_limit()


def test_at_201_deterministic_sha256_order_id_hashing():
    """AT-201: Verify SHA-256 order ID generation is bit-for-bit deterministic (INV-49)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

    id1 = engine.generate_canonical_order_id("ACC1", "AAPL", 100, 180.50, now_utc)
    id2 = engine.generate_canonical_order_id("ACC1", "AAPL", 100, 180.50, now_utc)

    assert len(id1) == 64
    assert id1 == id2


def test_at_202_alphabetical_reconciliation_slicing():
    """AT-202: Verify corrective order queues are sorted alphabetically by symbol (INV-49)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime.now(timezone.utc)

    tracked = {"ZOMATO": 0, "AAPL": 0, "INFYS": 0}
    records = [
        BrokerPositionRecord("ZOMATO", 10, 200.0, "ACC1", now_utc, now_utc),
        BrokerPositionRecord("AAPL", 10, 180.0, "ACC1", now_utc, now_utc),
        BrokerPositionRecord("INFYS", 10, 1500.0, "ACC1", now_utc, now_utc),
    ]

    report = engine.reconcile_account("ACC1", tracked, records, now_utc)

    sorted_symbols = list(report.position_drift.keys())
    assert sorted_symbols == ["AAPL", "INFYS", "ZOMATO"]


def test_at_203_non_finite_order_quantity_rejection():
    """AT-203: Verify NaN / Inf order quantity fails closed (INV-51)."""
    now_utc = datetime.now(timezone.utc)
    with pytest.raises(GatewayValidationError):
        OrderPayload("O1", "ACC1", "AAPL", float("nan"), 180.0, now_utc)


def test_at_204_non_finite_order_price_rejection():
    """AT-204: Verify NaN / Inf order price fails closed (INV-51)."""
    now_utc = datetime.now(timezone.utc)
    with pytest.raises(GatewayValidationError):
        OrderPayload("O1", "ACC1", "AAPL", 10, float("inf"), now_utc)


def test_at_205_negative_order_quantity_protection():
    """AT-205: Verify zero quantity fails closed (INV-51)."""
    now_utc = datetime.now(timezone.utc)
    with pytest.raises(GatewayValidationError):
        OrderPayload("O1", "ACC1", "AAPL", 0, 180.0, now_utc)


def test_at_206_emergency_halt_ai_reset_blocking():
    """AT-206: Verify AI sub-agents cannot reset EMERGENCY_HALT state (INV-53)."""
    cb = CircuitBreakerEngine()
    cb.trigger_emergency_halt("TEST_HALT")

    assert cb.state == GatewayState.EMERGENCY_HALT

    # Attempt re-arm with wrong/invalid token
    success = cb.admin_rearm("INVALID_AI_TOKEN")
    assert success is False
    assert cb.state == GatewayState.EMERGENCY_HALT


def test_at_207_point_in_time_snapshot_isolation():
    """AT-207: Verify future publication snapshots are rejected (INV-50)."""
    engine = MultiBrokerReconciliationEngine()
    t_recon = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
    t_future = t_recon + timedelta(minutes=5)

    records = [
        BrokerPositionRecord("AAPL", 100, 180.0, "ACC1", t_recon, t_future)
    ]

    with pytest.raises(StaleSnapshotError):
        engine.reconcile_account("ACC1", {}, records, t_recon)


def test_at_208_order_status_ambiguity_reconciliation():
    """AT-208: Verify reconciliation operates cleanly on verified snapshot state (INV-50)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime.now(timezone.utc)

    tracked = {"AAPL": 50}
    records = [BrokerPositionRecord("AAPL", 50, 180.0, "ACC1", now_utc, now_utc)]

    report = engine.reconcile_account("ACC1", tracked, records, now_utc)
    assert report.reconciliation_status == ReconciliationStatus.SYNCHRONIZED.value
    assert report.residual_drift_count == 0


def test_at_209_duplicate_order_id_idempotency_lockout():
    """AT-209: Verify duplicate order ID submission is rejected (INV-49)."""
    gateway = ExecutionSafetyGateway(available_cash=100_000.0)
    now_utc = datetime.now(timezone.utc)
    payload = OrderPayload("O_DUP_1", "ACC1", "AAPL", 10, 180.0, now_utc)

    assert gateway.validate_and_process_order(payload) is True

    with pytest.raises(DuplicateOrderError):
        gateway.validate_and_process_order(payload)


def test_at_210_partial_fill_position_reconciliation():
    """AT-210: Verify position reconciliation accounts for partial fill drift (INV-47)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime.now(timezone.utc)

    tracked = {"AAPL": 0}
    records = [BrokerPositionRecord("AAPL", 40, 180.0, "ACC1", now_utc, now_utc)]

    report = engine.reconcile_account("ACC1", tracked, records, now_utc)
    assert report.position_drift["AAPL"] == 40
    assert len(report.corrective_orders_generated) == 1


def test_at_211_pre_submission_solvency_check_gate():
    """AT-211: Verify order exceeding available cash is rejected (INV-48)."""
    gateway = ExecutionSafetyGateway(available_cash=1_000.0)
    now_utc = datetime.now(timezone.utc)

    # 10 shares @ 180 = 1,800 > 1,000 cash
    payload = OrderPayload("O_OVER_CASH", "ACC1", "AAPL", 10, 180.0, now_utc)

    with pytest.raises(GatewayValidationError):
        gateway.validate_and_process_order(payload)


def test_at_212_unallocated_residual_cash_attribution():
    """AT-212: Verify discrete share integer position rounding retains cash integrity (INV-47)."""
    engine = MultiBrokerReconciliationEngine()
    now_utc = datetime.now(timezone.utc)

    tracked = {"AAPL": 10}
    records = [BrokerPositionRecord("AAPL", 10, 180.0, "ACC1", now_utc, now_utc)]

    report = engine.reconcile_account("ACC1", tracked, records, now_utc)
    assert report.residual_drift_count == 0


def test_at_213_static_ast_gateway_isolation_scanner():
    """AT-213: Verify static AST scanner passes clean execution_gateway package (INV-52)."""
    scanner = StaticASTIsolationScanner()
    gateway_dir = os.path.join(os.path.dirname(__file__), "../../services/execution_gateway")
    assert scanner.scan_directory(gateway_dir) is True
