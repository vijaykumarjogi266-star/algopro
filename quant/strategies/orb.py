"""Opening Range Breakout (ORB) Research Strategy.

Models volatility expansion and breakout beyond the first N-minutes opening range
of the Indian market session (09:15 IST onwards).
Adheres to Principle 1 (Never force a trade) and Principle 2 (WAIT is a valid decision).
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional
from data.schemas.contracts import OHLCVBar
from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from services.backtest_engine.trade_candidate import CandidateAction, TradeCandidate


class OpeningRangeBreakout(BaseStrategy):
    """Opening Range Breakout (ORB) Strategy."""

    def __init__(
        self,
        range_bars: int = 3,  # e.g., 3 bars of 5-minute = 15-minute range
        volume_multiplier: float = 1.2,
        risk_reward_ratio: float = 2.0,
    ):
        super().__init__(
            strategy_id="ORB_STRATEGY",
            name="Opening Range Breakout",
            version="1.0.0",
            parameters={
                "range_bars": range_bars,
                "volume_multiplier": volume_multiplier,
                "risk_reward_ratio": risk_reward_ratio,
            },
        )
        self.range_bars = range_bars
        self.volume_multiplier = volume_multiplier
        self.risk_reward_ratio = risk_reward_ratio

        # Internal state reset per session
        self.opening_high: Optional[float] = None
        self.opening_low: Optional[float] = None
        self.session_bar_count = 0
        self.current_session_date = None
        self.trade_taken_today = False

    def on_bar(
        self,
        current_bar: OHLCVBar,
        history: List[OHLCVBar],
        indicators: Dict[str, Optional[float]],
        has_open_position: bool = False,
    ) -> Optional[TradeCandidate]:
        """Evaluates market state point-in-time and returns TradeCandidate if setup forms."""
        bar_date = current_bar.market_timestamp.date()
        if bar_date != self.current_session_date:
            self.current_session_date = bar_date
            self.session_bar_count = 0
            self.opening_high = None
            self.opening_low = None
            self.trade_taken_today = False

        self.session_bar_count += 1

        # Phase 1: Establish Opening Range
        if self.session_bar_count <= self.range_bars:
            if self.opening_high is None or current_bar.high > self.opening_high:
                self.opening_high = current_bar.high
            if self.opening_low is None or current_bar.low < self.opening_low:
                self.opening_low = current_bar.low
            return None  # In range formation: WAIT (Principle 2)

        # If already in position or already traded today, do not force another trade (Principle 1)
        if has_open_position or self.trade_taken_today:
            return None

        # Intraday square-off check: No new entries after 14:45 IST
        # Convert to local time or check hours
        # Phase 2: Breakout Detection
        rvol = indicators.get("rvol_20", 1.0)
        atr = indicators.get("atr_14", (self.opening_high - self.opening_low))

        # Long Breakout Setup
        if current_bar.close > self.opening_high:
            range_span = self.opening_high - self.opening_low
            stop_loss = max(self.opening_low, self.opening_high - range_span * 0.5)
            risk = current_bar.close - stop_loss
            if risk <= 0:
                return None

            target = current_bar.close + (risk * self.risk_reward_ratio)
            self.trade_taken_today = True

            return TradeCandidate(
                strategy_id=self.strategy_id,
                strategy_version=self.version,
                symbol=current_bar.symbol,
                timestamp=current_bar.market_timestamp,
                action=CandidateAction.ENTER_LONG,
                confidence=0.75,
                reason=f"ORB {self.range_bars}-bar high breakout above {self.opening_high:.2f}",
                evidence={
                    "opening_high": self.opening_high,
                    "opening_low": self.opening_low,
                    "rvol": rvol,
                    "atr": atr,
                },
                suggested_limit_price=current_bar.close,
                suggested_stop_loss=round(stop_loss, 2),
                suggested_target_price=round(target, 2),
                suggested_position_size_pct=0.05,
            )

        return None

    def evaluate(self, current_bar, history, data_quality):
        """Adapter for Stage 1 BaseStrategy interface."""
        return self.default_wait(current_bar.symbol, current_bar.market_timestamp, "ORB in evaluation")
