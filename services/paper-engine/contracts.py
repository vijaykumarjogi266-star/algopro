"""Algo Lab Paper Trading Engine Contracts.

Adheres to Non-Negotiable Principles:
- Principle 25: No live capital deployment during the initial development stages.
- Architecture: Market Data -> Validation -> Strategy -> Risk -> Paper Order -> Simulated Fill -> Position -> P&L -> Trade Journal.
- Paper trading must never send a real broker order.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import OrderSide, OrderType


class PaperOrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PaperOrder(BaseModel):
    order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(gt=0)
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    status: PaperOrderStatus = PaperOrderStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rejection_reason: Optional[str] = None


class PaperFill(BaseModel):
    fill_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    fill_price: float
    slippage: float
    commission: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperPosition(BaseModel):
    symbol: str
    quantity: int
    side: OrderSide
    average_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    opened_at: datetime


class ISimulatedBroker(ABC):
    """Simulated Broker Interface that NEVER connects to real exchange networks."""

    @abstractmethod
    def submit_order(self, order: PaperOrder) -> PaperOrder:
        """Processes an order in memory with simulated slippage and commission."""
        pass

    @abstractmethod
    def get_positions(self) -> List[PaperPosition]:
        """Returns active paper positions."""
        pass

    @abstractmethod
    def get_account_equity(self) -> float:
        """Returns total simulated portfolio equity (cash + open positions)."""
        pass
