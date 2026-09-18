"""
Stage 11 Execution Gateway Package.

Provides real-time execution safety, circuit breakers, multi-broker position reconciliation,
and static security isolation.
"""

from services.execution_gateway.contracts import (
    GatewayState,
    OrderStatus,
    ReconciliationStatus,
    CircuitBreakerConfig,
    BrokerPositionRecord,
    ReconciliationReport,
    GatewayAuditManifest,
    OrderPayload,
    ExecutionGatewayError,
    GatewayValidationError,
    CircuitBreakerTripped,
    WatchdogTimeoutError,
    RateLimitExceededError,
    DuplicateOrderError,
    ASTIsolationError,
    StaleSnapshotError,
)

__all__ = [
    "GatewayState",
    "OrderStatus",
    "ReconciliationStatus",
    "CircuitBreakerConfig",
    "BrokerPositionRecord",
    "ReconciliationReport",
    "GatewayAuditManifest",
    "OrderPayload",
    "ExecutionGatewayError",
    "GatewayValidationError",
    "CircuitBreakerTripped",
    "WatchdogTimeoutError",
    "RateLimitExceededError",
    "DuplicateOrderError",
    "ASTIsolationError",
    "StaleSnapshotError",
]
