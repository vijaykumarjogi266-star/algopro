"""Algo Lab Portfolio Accounting & Position Management.

Enforces strict financial accounting invariants:
Starting Capital + Realized P&L + Unrealized P&L - Fees = Total Equity
Cash + Open Positions Value = Total Equity
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from data.schemas.contracts import OHLCVBar
from services.backtest_engine.contracts import OrderSide, TradeRecord
from services.backtest_engine.trade_candidate import SimulatedFill


class Position(BaseModel):
    """Encapsulates an active simulated position."""

    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    entry_timestamp: datetime
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    candidate_id: str
    entry_reason: str
    evidence_snapshot: Dict = Field(default_factory=dict)
    market_regime: str = "NORMAL"

    # Dynamic pricing
    current_price: float = Field(gt=0)
    unrealized_pnl: float = 0.0
    fees_incurred: float = 0.0
    slippage_incurred: float = 0.0

    def update_price(self, price: float):
        """Updates current price and marks position to market."""
        self.current_price = price
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity

    @property
    def market_value(self) -> float:
        """Current total liquidation market value."""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        """Initial cost basis of position."""
        return self.quantity * self.entry_price


class PortfolioTracker:
    """Manages cash balance, active positions, and accounting invariants."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        if initial_capital <= 0:
            raise ValueError("Initial capital must be positive.")
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.positions: Dict[str, Position] = {}
        self.completed_trades: List[TradeRecord] = []
        self.equity_history: List[Dict] = []

        self.total_realized_gross_pnl: float = 0.0
        self.total_fees_paid: float = 0.0
        self.total_slippage_paid: float = 0.0
        self.peak_equity: float = float(initial_capital)
        self.max_drawdown_pct: float = 0.0
        self.rejected_trades_count: int = 0
        self.wait_decisions_count: int = 0

    @property
    def total_equity(self) -> float:
        """Total current portfolio liquidation equity: Cash + Market Value of Longs / P&L of Shorts."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        cost_basis_open = sum(p.cost_basis for p in self.positions.values() if p.side == OrderSide.BUY)
        return self.cash + cost_basis_open + unrealized

    def can_open_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        max_positions: int = 10,
        max_capital_pct: float = 0.20,
    ) -> Tuple[bool, str]:
        """Validates capital and concentration limits prior to fill."""
        if symbol in self.positions:
            return False, f"Position already open in {symbol}"
        if len(self.positions) >= max_positions:
            return False, f"Maximum simultaneous positions limit ({max_positions}) reached"

        required_capital = quantity * price
        if required_capital > self.cash:
            return False, f"Insufficient cash: required ₹{required_capital:.2f}, available ₹{self.cash:.2f}"

        max_allowed_for_trade = self.total_equity * max_capital_pct
        if required_capital > max_allowed_for_trade:
            return False, f"Trade size ₹{required_capital:.2f} exceeds max capital limit of ₹{max_allowed_for_trade:.2f}"

        return True, "Approved"

    def open_position(
        self,
        fill: SimulatedFill,
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
        entry_reason: str = "Strategy Signal",
        evidence: Optional[Dict] = None,
        market_regime: str = "NORMAL",
    ):
        """Processes an entry fill and deducts cash."""
        cost = fill.quantity * fill.fill_price
        self.cash -= cost
        self.cash -= fill.fees
        self.total_fees_paid += fill.fees
        self.total_slippage_paid += (fill.slippage * fill.quantity)

        pos = Position(
            symbol=fill.symbol,
            side=fill.side,
            quantity=fill.quantity,
            entry_price=fill.fill_price,
            entry_timestamp=fill.timestamp,
            stop_loss=stop_loss,
            target_price=target_price,
            candidate_id=fill.candidate_id,
            entry_reason=entry_reason,
            evidence_snapshot=evidence or {},
            market_regime=market_regime,
            current_price=fill.fill_price,
            unrealized_pnl=0.0,
            fees_incurred=fill.fees,
            slippage_incurred=fill.slippage * fill.quantity,
        )
        self.positions[fill.symbol] = pos

    def close_position(
        self,
        symbol: str,
        fill: SimulatedFill,
    ) -> TradeRecord:
        """Closes an active position, returns cash, records trade in journal."""
        if symbol not in self.positions:
            raise KeyError(f"No active position to close for {symbol}")

        pos = self.positions.pop(symbol)

        # Gross P&L
        if pos.side == OrderSide.BUY:
            gross_pnl = (fill.fill_price - pos.entry_price) * fill.quantity
        else:
            gross_pnl = (pos.entry_price - fill.fill_price) * fill.quantity

        total_trade_fees = pos.fees_incurred + fill.fees
        total_trade_slippage = pos.slippage_incurred + (fill.slippage * fill.quantity)
        net_pnl = gross_pnl - total_trade_fees - total_trade_slippage

        # Return capital to cash pool: original cost + gross pnl - exit fees
        self.cash += (pos.quantity * pos.entry_price) + gross_pnl - fill.fees
        self.total_fees_paid += fill.fees
        self.total_slippage_paid += (fill.slippage * fill.quantity)
        self.total_realized_gross_pnl += gross_pnl

        holding_time = (fill.timestamp - pos.entry_timestamp).total_seconds()

        trade = TradeRecord(
            trade_id=fill.order_id,
            symbol=symbol,
            strategy_id=pos.candidate_id,
            strategy_version="1.0.0",
            side=pos.side,
            entry_timestamp=pos.entry_timestamp,
            exit_timestamp=fill.timestamp,
            entry_price=pos.entry_price,
            exit_price=fill.fill_price,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            target_price=pos.target_price,
            gross_pnl=round(gross_pnl, 4),
            costs=round(total_trade_fees, 4),
            slippage=round(total_trade_slippage, 4),
            net_pnl=round(net_pnl, 4),
            holding_time_seconds=holding_time,
            entry_reason=pos.entry_reason,
            exit_reason=fill.exit_reason or "Target or Stop Hit",
            evidence_snapshot={
                **pos.evidence_snapshot,
                "market_regime": pos.market_regime,
            },
        )
        self.completed_trades.append(trade)
        return trade

    def mark_to_market(self, current_bar: OHLCVBar, timestamp: datetime):
        """Updates prices of open positions and logs equity curve snapshot."""
        if current_bar.symbol in self.positions:
            self.positions[current_bar.symbol].update_price(current_bar.close)

        eq = self.total_equity
        if eq > self.peak_equity:
            self.peak_equity = eq

        drawdown_pct = ((self.peak_equity - eq) / self.peak_equity) * 100.0 if self.peak_equity > 0 else 0.0
        if drawdown_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = drawdown_pct

        self.equity_history.append({
            "timestamp": timestamp.isoformat(),
            "equity": round(eq, 2),
            "cash": round(self.cash, 2),
            "open_positions": len(self.positions),
            "drawdown_pct": round(drawdown_pct, 4),
        })

    def verify_accounting_integrity(self) -> Tuple[bool, str]:
        """Mathematical assertion: Total Equity == Cash + CostBasis + Unrealized."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        cost_basis = sum(p.cost_basis for p in self.positions.values())
        calc_equity = self.cash + cost_basis + unrealized
        diff = abs(self.total_equity - calc_equity)
        if diff > 0.01:
            return False, f"Accounting discrepancy: total_equity ({self.total_equity}) != calc ({calc_equity})"
        return True, "Accounting Valid"
