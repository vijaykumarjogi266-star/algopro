"""
Data contracts, schemas, exceptions, and validation logic for Stage 11 Execution Gateway.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import math
import unicodedata


class GatewayState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    EMERGENCY_HALT = "EMERGENCY_HALT"


class OrderStatus(str, Enum):
    PENDING_NEW = "PENDING_NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class ReconciliationStatus(str, Enum):
    SYNCHRONIZED = "SYNCHRONIZED"
    DRIFT_DETECTED = "DRIFT_DETECTED"


class ExecutionGatewayError(Exception):
    """Base exception for all Stage 11 Execution Gateway failures."""
    pass


class GatewayValidationError(ExecutionGatewayError):
    """Raised when an order payload or contract schema validation fails."""
    pass


class CircuitBreakerTripped(ExecutionGatewayError):
    """Raised when an order submission is attempted during EMERGENCY_HALT."""
    pass


class WatchdogTimeoutError(ExecutionGatewayError):
    """Raised when watchdog heartbeat timeout is exceeded."""
    pass


class RateLimitExceededError(ExecutionGatewayError):
    """Raised when order submission burst rate is exceeded."""
    pass


class DuplicateOrderError(ExecutionGatewayError):
    """Raised when duplicate order ID is submitted."""
    pass


class ASTIsolationError(ExecutionGatewayError):
    """Raised when static AST code isolation scanner detects prohibited imports or dynamic calls."""
    pass


class StaleSnapshotError(ExecutionGatewayError):
    """Raised when stale broker snapshot is ingested."""
    pass


@dataclass(frozen=True)
class CircuitBreakerConfig:
    max_portfolio_drawdown_pct: float = 0.15   # Max allowed peak-to-trough drawdown (15%, inclusive >=)
    max_daily_loss_pct: float = 0.03            # Max allowed daily loss (3%, inclusive >=)
    max_order_rate_per_sec: int = 10           # Rate limit cap (1.0s monotonic sliding window)
    watchdog_heartbeat_timeout_sec: float = 5.0 # Heartbeat watchdog timeout (5.0s monotonic)
    max_single_order_qty: int = 1_000_000       # Max shares per single order (1,000,000)

    def __post_init__(self):
        for name, val in [
            ("max_portfolio_drawdown_pct", self.max_portfolio_drawdown_pct),
            ("max_daily_loss_pct", self.max_daily_loss_pct),
            ("watchdog_heartbeat_timeout_sec", self.watchdog_heartbeat_timeout_sec),
        ]:
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val) or val <= 0.0:
                raise ValueError(f"Invalid non-finite or non-positive value in CircuitBreakerConfig for {name}: {val}")
        if not isinstance(self.max_order_rate_per_sec, int) or self.max_order_rate_per_sec <= 0:
            raise ValueError(f"max_order_rate_per_sec must be positive integer: {self.max_order_rate_per_sec}")
        if not isinstance(self.max_single_order_qty, int) or self.max_single_order_qty <= 0:
            raise ValueError(f"max_single_order_qty must be positive integer: {self.max_single_order_qty}")


@dataclass(frozen=True)
class OrderPayload:
    order_id: str
    account_id: str
    symbol: str
    quantity: int
    price: float
    timestamp: datetime
    strategy_id: str = "default_strategy"

    def __post_init__(self):
        if not self.order_id or not isinstance(self.order_id, str):
            raise GatewayValidationError("order_id must be a non-empty string")
        if not self.account_id or not isinstance(self.account_id, str):
            raise GatewayValidationError("account_id must be a non-empty string")
        if not self.symbol or not isinstance(self.symbol, str):
            raise GatewayValidationError("symbol must be a non-empty string")
        if not isinstance(self.quantity, int) or self.quantity == 0:
            raise GatewayValidationError(f"quantity must be a non-zero integer: {self.quantity}")
        if abs(self.quantity) > 1_000_000:
            raise GatewayValidationError(f"quantity exceeds MAX_SINGLE_ORDER_QTY (1,000,000): {self.quantity}")
        if not isinstance(self.price, (int, float)) or math.isnan(self.price) or math.isinf(self.price) or self.price <= 0.0:
            raise GatewayValidationError(f"price must be a positive finite float: {self.price}")
        if not isinstance(self.timestamp, datetime):
            raise GatewayValidationError("timestamp must be a datetime object")


@dataclass(frozen=True)
class BrokerPositionRecord:
    symbol: str
    quantity: int
    average_price: float
    account_id: str
    snapshot_timestamp: datetime
    publication_timestamp: datetime

    def __post_init__(self):
        if not self.symbol or not isinstance(self.symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(self.quantity, int):
            raise ValueError(f"quantity must be an integer: {self.quantity}")
        if not isinstance(self.average_price, (int, float)) or math.isnan(self.average_price) or math.isinf(self.average_price) or self.average_price < 0.0:
            raise ValueError(f"average_price must be non-negative finite float: {self.average_price}")
        if not self.account_id or not isinstance(self.account_id, str):
            raise ValueError("account_id must be a non-empty string")
        if not isinstance(self.snapshot_timestamp, datetime) or not isinstance(self.publication_timestamp, datetime):
            raise ValueError("timestamps must be datetime objects")


@dataclass(frozen=True)
class ReconciliationReport:
    timestamp: datetime
    account_id: str
    tracked_positions: Dict[str, int]
    broker_positions: Dict[str, int]
    position_drift: Dict[str, int]
    corrective_orders_generated: List[str]
    reconciliation_status: str
    residual_drift_count: int


@dataclass(frozen=True)
class GatewayAuditManifest:
    manifest_id: str
    timestamp: datetime
    gateway_state: GatewayState
    circuit_breaker_active: bool
    manifest_hash: str
    reconciliation_summary_hash: str
