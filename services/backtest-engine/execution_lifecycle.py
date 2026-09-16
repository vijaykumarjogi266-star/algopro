"""Algo Lab Execution Lifecycle & Deterministic Slippage Manager (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 15: AI must never override hard risk controls.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
- Full Order Lifecycle:
  ORDER_PROPOSED -> RISK_CHECK_EVALUATED -> ORDER_ACCEPTED / ORDER_REJECTED -> ORDER_SUBMITTED -> ORDER_FILLED / ORDER_CANCELLED / ORDER_FAILED
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid
from pydantic import BaseModel, Field

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.contracts import OrderSide, OrderType, CostModelConfig, SlippageModelConfig
from services.backtest_engine.cost_models import IndianCostCalculator, SlippageCalculator
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskEvaluationResult, RiskRejectionCode
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class OrderLifecycleState(str, Enum):
    ORDER_PROPOSED = "ORDER_PROPOSED"
    RISK_CHECK_EVALUATED = "RISK_CHECK_EVALUATED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_FAILED = "ORDER_FAILED"


class ExecutionOrder(BaseModel):
    """Lifecycle-managed order tracked across all state transitions."""

    order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: int = Field(gt=0)
    proposed_price: float = Field(gt=0.0)
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None

    state: OrderLifecycleState = OrderLifecycleState.ORDER_PROPOSED
    rejection_code: Optional[str] = None
    rejection_reason: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_history: List[Dict[str, Any]] = Field(default_factory=list)

    def transition_to(self, new_state: OrderLifecycleState, reason: Optional[str] = None, **kwargs):
        """Records an immutable lifecycle transition in audit history."""
        now = datetime.now(timezone.utc)
        record = {
            "from_state": self.state.value,
            "to_state": new_state.value,
            "timestamp": now.isoformat(),
            "reason": reason,
            **kwargs,
        }
        self.state_history.append(record)
        self.state = new_state
        self.updated_at = now


class ExecutionFill(BaseModel):
    """Detailed attribution of execution fill with deterministic costs and slippage."""

    fill_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    base_price: float
    fill_price: float
    slippage_pts: float
    slippage_cost: float
    transaction_costs: float
    net_traded_value: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fee_breakdown: Dict[str, float] = Field(default_factory=dict)


class ExecutionLifecycleManager:
    """Manages order creation, independent risk gating, submission, and realistic fill simulation."""

    def __init__(
        self,
        risk_engine: Optional[RiskEngine] = None,
        cost_calculator: Optional[IndianCostCalculator] = None,
        slippage_calculator: Optional[SlippageCalculator] = None,
    ):
        self.risk_engine = risk_engine or RiskEngine()
        self.cost_calculator = cost_calculator or IndianCostCalculator()
        self.slippage_calculator = slippage_calculator or SlippageCalculator()

    def propose_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType = OrderType.MARKET,
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        candidate_id: Optional[str] = None,
    ) -> ExecutionOrder:
        """Step 1: Creates an initial order in ORDER_PROPOSED state."""
        order = ExecutionOrder(
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=quantity,
            proposed_price=price,
            limit_price=limit_price,
            stop_loss=stop_loss,
            target_price=target_price,
            candidate_id=candidate_id or str(uuid.uuid4()),
        )
        order.state_history.append({
            "from_state": None,
            "to_state": OrderLifecycleState.ORDER_PROPOSED.value,
            "timestamp": order.created_at.isoformat(),
            "reason": "Initial order proposal",
        })
        return order

    def calculate_order_outflow(
        self,
        side: OrderSide,
        quantity: int,
        price: float,
        is_intraday: bool = True,
    ) -> float:
        """Calculates expected total cash outflow (net traded value + slippage + costs) for an order."""
        if side != OrderSide.BUY:
            return 0.0

        fill_price, _ = self.slippage_calculator.calculate_fill_price(
            side=side,
            base_price=price,
        )
        costs = self.cost_calculator.calculate_transaction_costs(
            side=side,
            quantity=quantity,
            price=fill_price,
            is_intraday=is_intraday,
        )
        net_traded_value = round(quantity * fill_price, 4)
        return round(net_traded_value + costs, 4)

    def evaluate_risk(
        self,
        order: ExecutionOrder,
        current_portfolio_value: float,
        current_daily_loss_pct: float = 0.0,
        current_drawdown_pct: float = 0.0,
        current_open_positions_count: int = 0,
        available_cash: Optional[float] = None,
    ) -> ExecutionOrder:
        """Step 2 & 3: Evaluates proposal via independent RiskEngine and cash solvency checks.
        
        Transitions:
        ORDER_PROPOSED -> RISK_CHECK_EVALUATED -> ORDER_ACCEPTED (if approved)
                                                -> ORDER_REJECTED (if denied)
        """
        if order.state != OrderLifecycleState.ORDER_PROPOSED:
            raise ValueError(f"Cannot evaluate risk on order in state {order.state}")

        order.transition_to(OrderLifecycleState.RISK_CHECK_EVALUATED, reason="Submitting to Risk Engine")

        # 1. Independent Risk Engine evaluation (portfolio-level risk caps)
        risk_result: RiskEvaluationResult = self.risk_engine.evaluate(
            symbol=order.symbol,
            price=order.proposed_price,
            proposed_quantity=order.quantity,
            stop_loss=order.stop_loss,
            current_portfolio_value=current_portfolio_value,
            current_daily_loss_pct=current_daily_loss_pct,
            current_drawdown_pct=current_drawdown_pct,
            current_open_positions_count=current_open_positions_count,
        )

        if not risk_result.is_approved:
            order.rejection_code = (
                risk_result.rejection_code.value
                if hasattr(risk_result.rejection_code, "value")
                else str(risk_result.rejection_code)
            )
            order.rejection_reason = risk_result.rejection_reason
            order.transition_to(
                OrderLifecycleState.ORDER_REJECTED,
                reason=risk_result.rejection_reason,
                rejection_code=order.rejection_code,
            )
            return order

        # 2. Cash Solvency Pre-Trade Evaluation (BUY orders)
        if available_cash is not None and order.side == OrderSide.BUY:
            required_outflow = self.calculate_order_outflow(
                side=order.side,
                quantity=order.quantity,
                price=order.proposed_price,
            )
            if available_cash < required_outflow:
                order.rejection_code = RiskRejectionCode.INSUFFICIENT_CASH.value
                order.rejection_reason = (
                    f"Insufficient available cash: required INR {required_outflow:.2f} "
                    f"(trade + slippage + costs) exceeds available cash INR {available_cash:.2f}"
                )
                order.transition_to(
                    OrderLifecycleState.ORDER_REJECTED,
                    reason=order.rejection_reason,
                    rejection_code=order.rejection_code,
                    required_outflow=required_outflow,
                    available_cash=available_cash,
                )
                return order

        order.transition_to(
            OrderLifecycleState.ORDER_ACCEPTED,
            reason="Risk Engine approved order",
            approved_quantity=risk_result.approved_quantity,
        )

        return order

    def submit_order(self, order: ExecutionOrder) -> ExecutionOrder:
        """Step 4: Submits an approved order for execution."""
        if order.state != OrderLifecycleState.ORDER_ACCEPTED:
            raise ValueError(f"Only ORDER_ACCEPTED orders can be submitted. Current state: {order.state}")

        order.transition_to(OrderLifecycleState.ORDER_SUBMITTED, reason="Routing to paper execution venue")
        return order

    def fill_order(
        self,
        order: ExecutionOrder,
        current_bar: Optional[CanonicalMarketDataBar] = None,
        execution_price: Optional[float] = None,
        is_intraday: bool = True,
    ) -> Tuple[ExecutionOrder, ExecutionFill]:
        """Step 5: Simulates execution fill with deterministic slippage and statutory costs."""
        if order.state != OrderLifecycleState.ORDER_SUBMITTED:
            raise ValueError(f"Only ORDER_SUBMITTED orders can be filled. Current state: {order.state}")

        base_price = execution_price if execution_price is not None else order.proposed_price

        # 1. Slippage calculation
        fill_price, slippage_pts = self.slippage_calculator.calculate_fill_price(
            side=order.side,
            base_price=base_price,
        )
        slippage_cost = slippage_pts * order.quantity

        # 2. Transaction cost calculation
        costs = self.cost_calculator.calculate_transaction_costs(
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            is_intraday=is_intraday,
        )

        net_traded_value = round(order.quantity * fill_price, 4)

        fill = ExecutionFill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            base_price=base_price,
            fill_price=fill_price,
            slippage_pts=slippage_pts,
            slippage_cost=slippage_cost,
            transaction_costs=costs,
            net_traded_value=net_traded_value,
            fee_breakdown={"total_costs": costs},
        )

        order.transition_to(
            OrderLifecycleState.ORDER_FILLED,
            reason=f"Filled at {fill_price:.4f} (slippage: {slippage_pts:.4f}, costs: {costs:.2f})",
            fill_id=fill.fill_id,
            fill_price=fill_price,
        )

        return order, fill

    def cancel_order(self, order: ExecutionOrder, reason: str = "User cancelled") -> ExecutionOrder:
        """Transitions order to ORDER_CANCELLED."""
        if order.state in (OrderLifecycleState.ORDER_FILLED, OrderLifecycleState.ORDER_REJECTED):
            raise ValueError(f"Cannot cancel order in terminal state {order.state}")

        order.transition_to(OrderLifecycleState.ORDER_CANCELLED, reason=reason)
        return order

    def fail_order(self, order: ExecutionOrder, reason: str) -> ExecutionOrder:
        """Transitions order to ORDER_FAILED."""
        order.transition_to(OrderLifecycleState.ORDER_FAILED, reason=reason)
        return order
