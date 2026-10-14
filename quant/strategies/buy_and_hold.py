"""Algo Lab Buy and Hold Strategy (Benchmark).

Enters on bar 0 (first available bar) and holds through end date.
Adheres to Non-Negotiable Principles:
- Principle 8: Every strategy must be versioned.
- Principle 7: Every backtest must be reproducible.
"""

from typing import Any, Dict, List, Optional
from data.schemas.contracts import OHLCVBar
from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from services.backtest_engine.trade_candidate import CandidateAction, TradeCandidate


class BuyAndHold(BaseStrategy):
    """Buy and Hold Strategy.
    
    Enters a long position on bar 0 (first available bar) and holds through end date.
    Independent of SMA crossovers or other indicators.
    """

    def __init__(
        self,
        strategy_id: str = "BuyAndHold",
        version: str = "1.0.0",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            strategy_id=strategy_id,
            name="Buy and Hold",
            version=version,
            parameters=parameters or {},
        )
        self.allocation_pct: float = float(self.parameters.get("allocation_pct", 1.0))
        self.weights: Dict[str, float] = self.parameters.get("weights", {})
        self.universe: List[str] = self.parameters.get("universe", [])
        self.has_entered: Dict[str, bool] = {}

    def get_allocation_weight(self, symbol: str) -> float:
        """Determines explicit allocation weight for a symbol, conserving cash."""
        if symbol in self.weights:
            return float(self.weights[symbol])
        if self.universe:
            return float(self.allocation_pct / len(self.universe))
        return float(self.allocation_pct)

    def on_bar(
        self,
        current_bar: OHLCVBar,
        history: List[OHLCVBar],
        indicators: Optional[Dict[str, Optional[float]]] = None,
        has_open_position: bool = False,
    ) -> Optional[TradeCandidate]:
        sym = current_bar.symbol
        if has_open_position or self.has_entered.get(sym, False):
            return None

        self.has_entered[sym] = True
        weight = self.get_allocation_weight(sym)
        stop_loss = round(current_bar.close * 0.90, 2)
        ts = getattr(current_bar, "market_timestamp", getattr(current_bar, "timestamp", None))
        return TradeCandidate(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            symbol=sym,
            timestamp=ts,
            action=CandidateAction.ENTER_LONG,
            confidence=1.0,
            reason="Buy and Hold: initial entry on bar 0",
            evidence={
                "bar_index": len(history) if history else 0,
                "allocation_pct": self.allocation_pct,
                "weight": weight,
            },
            suggested_limit_price=current_bar.close,
            suggested_stop_loss=stop_loss,
            suggested_target_price=None,
            suggested_position_size_pct=weight,
        )

    def evaluate(self, current_bar, history, data_quality=None):
        sym = current_bar.symbol
        ts = getattr(current_bar, "market_timestamp", getattr(current_bar, "timestamp", None))
        if not self.has_entered.get(sym, False) and (history is None or len(history) == 0):
            self.has_entered[sym] = True
            weight = self.get_allocation_weight(sym)
            return StrategyDecision(
                symbol=sym,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=1.0,
                reason="Buy and Hold entry on bar 0",
                evidence={"bar_index": 0, "weight": weight, "allocation_pct": self.allocation_pct},
                stop_loss=round(current_bar.close * 0.90, 2),
            )
    def evaluate_data(
        self,
        symbol: str,
        data: Dict[str, Any],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> StrategyDecision:
        from datetime import datetime, timezone
        ts = data.get("bar_timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)
        price = float(data.get("price", 0.0))
        if not self.has_entered.get(symbol, False):
            self.has_entered[symbol] = True
            weight = self.get_allocation_weight(symbol)
            return StrategyDecision(
                symbol=symbol,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=1.0,
                reason="Buy and Hold entry",
                evidence={"weight": weight, "allocation_pct": self.allocation_pct},
                stop_loss=round(price * 0.90, 2),
                position_sizing_ratio=weight,
            )
        return self.default_wait(symbol, ts, "Buy and Hold in hold state")


    def execute_allocation_with_risk_policy(
        self,
        symbol: str,
        price: float,
        portfolio_value: float,
        risk_engine,
        available_cash: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Calculates proposed quantity and evaluates against risk policy.
        
        Preserves hard risk constraints: if proposed size violates risk policy,
        respects Risk Engine approved quantity or rejects.
        """
        weight = self.get_allocation_weight(symbol)
        allocated_capital = portfolio_value * weight
        if price <= 0.0:
            return {"approved": False, "quantity": 0, "reason": "Invalid price"}

        proposed_qty = max(1, int(allocated_capital / price))
        stop_loss = round(price * 0.90, 2)

        risk_eval = risk_engine.evaluate(
            symbol=symbol,
            price=price,
            proposed_quantity=proposed_qty,
            stop_loss=stop_loss,
            current_portfolio_value=portfolio_value,
            current_daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            current_open_positions_count=0,
        )

        if not risk_eval.is_approved:
            return {
                "approved": False,
                "quantity": 0,
                "proposed_quantity": proposed_qty,
                "rejection_code": risk_eval.rejection_code,
                "reason": risk_eval.rejection_reason,
            }

        approved_qty = risk_eval.approved_quantity if risk_eval.approved_quantity is not None else proposed_qty
        return {
            "approved": True,
            "quantity": approved_qty,
            "proposed_quantity": proposed_qty,
            "stop_loss": stop_loss,
            "allocated_capital": allocated_capital,
        }
