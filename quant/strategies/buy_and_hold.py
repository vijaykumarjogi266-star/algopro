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
        self.has_entered = False

    def on_bar(
        self,
        current_bar: OHLCVBar,
        history: List[OHLCVBar],
        indicators: Optional[Dict[str, Optional[float]]] = None,
        has_open_position: bool = False,
    ) -> Optional[TradeCandidate]:
        if has_open_position or self.has_entered:
            return None

        self.has_entered = True
        stop_loss = round(current_bar.close * 0.90, 2)
        ts = getattr(current_bar, "market_timestamp", getattr(current_bar, "timestamp", None))
        return TradeCandidate(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            symbol=current_bar.symbol,
            timestamp=ts,
            action=CandidateAction.ENTER_LONG,
            confidence=1.0,
            reason="Buy and Hold: initial entry on bar 0",
            evidence={"bar_index": len(history) if history else 0},
            suggested_limit_price=current_bar.close,
            suggested_stop_loss=stop_loss,
            suggested_target_price=None,
            suggested_position_size_pct=1.0,
        )

    def evaluate(self, current_bar, history, data_quality=None):
        ts = getattr(current_bar, "market_timestamp", getattr(current_bar, "timestamp", None))
        if not self.has_entered and (history is None or len(history) == 0):
            self.has_entered = True
            return StrategyDecision(
                symbol=current_bar.symbol,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=1.0,
                reason="Buy and Hold entry on bar 0",
                evidence={"bar_index": 0},
                stop_loss=round(current_bar.close * 0.90, 2),
            )
        return self.default_wait(current_bar.symbol, ts, "Buy and Hold in hold state")
