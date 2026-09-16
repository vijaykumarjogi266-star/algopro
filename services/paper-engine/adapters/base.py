"""Algo Lab Paper Execution Provider Interface & Simulated Broker Adapter (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 13: Fail closed.
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
- Principle 25: Paper trading must remain completely separate from real-money broker execution.
  LIVE real broker execution is hard-disabled.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import OrderSide, OrderType, CostModelConfig, SlippageModelConfig
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    ExecutionOrder,
    ExecutionFill,
    OrderLifecycleState,
)
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    ExecutionEnvironment,
    LIVE_TRADING_ENABLED,
)
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class PaperExecutionProvider(ABC):
    """Abstract interface for paper execution venue adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Adapter name."""
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Validates adapter connectivity."""
        pass

    @abstractmethod
    def submit_paper_order(
        self,
        order: ExecutionOrder,
        execution_price: float,
    ) -> Tuple[ExecutionOrder, ExecutionFill]:
        """Submits and executes an order in simulated venue."""
        pass

    @abstractmethod
    def cancel_paper_order(self, order_id: str, reason: str = "User cancelled") -> ExecutionOrder:
        """Cancels an existing pending paper order."""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[ExecutionOrder]:
        """Retrieves order by ID."""
        pass


class SimulatedBrokerAdapter(PaperExecutionProvider):
    """Safe, in-memory simulated broker adapter.
    
    Hard Security & Safety Guarantees:
    - Never communicates with real exchange APIs or live trading gateways.
    - If environment is set to LIVE, execution fails closed with a PermissionError.
    - All orders are simulated through the ExecutionLifecycleManager with realistic
      statutory Indian transaction costs and execution slippage.
    """

    def __init__(
        self,
        connection_config: Optional[BrokerConnectionConfig] = None,
        lifecycle_manager: Optional[ExecutionLifecycleManager] = None,
    ):
        self.config = connection_config or BrokerConnectionConfig(
            broker_name="simulated_paper",
            environment=ExecutionEnvironment.PAPER,
        )

        # Fail closed on LIVE
        if self.config.environment == ExecutionEnvironment.LIVE and not LIVE_TRADING_ENABLED:
            raise PermissionError("SimulatedBrokerAdapter cannot be instantiated in LIVE mode.")

        self.lifecycle_manager = lifecycle_manager or ExecutionLifecycleManager()
        self._orders: Dict[str, ExecutionOrder] = {}
        self._fills: Dict[str, ExecutionFill] = {}

    @property
    def provider_name(self) -> str:
        return f"SimulatedBroker({self.config.broker_name})"

    def test_connection(self) -> Dict[str, Any]:
        return {
            "connected": True,
            "status": "OPERATIONAL",
            "provider": self.provider_name,
            "environment": self.config.environment.value,
            "message": "Simulated paper trading broker engine is ready",
        }

    def submit_paper_order(
        self,
        order: ExecutionOrder,
        execution_price: float,
    ) -> Tuple[ExecutionOrder, ExecutionFill]:
        """Executes the paper order through the lifecycle manager."""
        if self.config.environment == ExecutionEnvironment.LIVE:
            raise PermissionError("Live execution is forbidden.")

        # Ensure order is submitted
        if order.state == OrderLifecycleState.ORDER_ACCEPTED:
            order = self.lifecycle_manager.submit_order(order)

        filled_order, fill = self.lifecycle_manager.fill_order(
            order,
            execution_price=execution_price,
        )

        self._orders[filled_order.order_id] = filled_order
        self._fills[fill.fill_id] = fill
        return filled_order, fill

    def cancel_paper_order(self, order_id: str, reason: str = "User cancelled") -> ExecutionOrder:
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Paper order {order_id} not found.")

        cancelled = self.lifecycle_manager.cancel_order(order, reason=reason)
        self._orders[order_id] = cancelled
        return cancelled

    def get_order(self, order_id: str) -> Optional[ExecutionOrder]:
        return self._orders.get(order_id)

    def list_orders(self) -> List[ExecutionOrder]:
        return list(self._orders.values())

    def list_fills(self) -> List[ExecutionFill]:
        return list(self._fills.values())
