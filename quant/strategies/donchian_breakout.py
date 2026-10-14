"""Algo Lab Donchian Channel Breakout Quantitative Strategy.

Models breakout beyond the highest high of the past N bars (default 20 bars).
- Breakout: Close > 20-bar High -> ENTER_LONG / BUY
- Non-breakout: Close <= 20-bar High -> WAIT
Adheres to Non-Negotiable Principles:
- Principle 1: Never force a trade.
- Principle 2: WAIT is a valid decision.
- Principle 8: Every strategy must be versioned.
"""

from typing import Any, Dict, List, Optional
import numpy as np
from datetime import datetime, timezone

from data.schemas.contracts import OHLCVBar
from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from services.backtest_engine.trade_candidate import CandidateAction, TradeCandidate


class DonchianBreakout(BaseStrategy):
    """Donchian 20-Bar Channel Breakout Strategy."""

    def __init__(
        self,
        strategy_id: str = "STRAT_DONCHIAN_BREAKOUT",
        version: str = "1.0.0",
        period: int = 20,
        stop_loss_atr: float = 1.5,
        target_atr: float = 3.0,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        params = parameters or {}
        p = int(params.get("period", period))
        sl_atr = float(params.get("stop_loss_atr", stop_loss_atr))
        tp_atr = float(params.get("target_atr", target_atr))
        super().__init__(
            strategy_id=strategy_id,
            name="Donchian Channel Breakout",
            version=version,
            parameters={"period": p, "stop_loss_atr": sl_atr, "target_atr": tp_atr},
        )
        self.period = p
        self.stop_loss_atr = sl_atr
        self.target_atr = tp_atr

    def evaluate_data(
        self,
        symbol: str,
        data: Dict[str, Any],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> StrategyDecision:
        """Evaluate market data dict point-in-time."""
        params = parameters or self.parameters
        sl_atr = float(params.get("stop_loss_atr", self.stop_loss_atr))
        tp_atr = float(params.get("target_atr", self.target_atr))
        period = int(params.get("period", self.period))

        price = float(data.get("price", 0.0))
        atr = float(data.get("atr", price * 0.01))
        ts = data.get("bar_timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)

        # Check for breakout condition
        high_n = None
        if "highs" in data and len(data["highs"]) >= period:
            highs = data["highs"]
            high_n = float(np.max(highs[-period - 1:-1])) if len(highs) > period else float(np.max(highs[:-1]))
        elif "high_20" in data:
            high_n = float(data["high_20"])
        elif "bars" in data and len(data["bars"]) >= period:
            bars = data["bars"]
            high_n = float(max(b.high for b in bars[-period - 1:-1])) if len(bars) > period else float(max(b.high for b in bars[:-1]))

        is_breakout = False
        if high_n is not None:
            is_breakout = price > high_n
        elif data.get("signal") == "BUY":
            is_breakout = True

        if is_breakout:
            stop_loss = round(price - (sl_atr * atr), 2)
            target = round(price + (tp_atr * atr), 2)
            return StrategyDecision(
                symbol=symbol,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=0.80,
                reason=f"Donchian breakout: price {price:.2f} broke above {period}-bar high {high_n}" if high_n is not None else "Mock BUY signal evaluated",
                evidence={"period": period, "high_n": high_n, "price": price, "atr": atr},
                stop_loss=stop_loss,
                target_price=target,
            )

        return self.default_wait(
            symbol=symbol,
            timestamp=ts,
            reason=f"No Donchian breakout (price={price:.2f}, high_{period}={high_n})",
        )

    def evaluate(self, current_bar: OHLCVBar, history: List[OHLCVBar], data_quality=None) -> StrategyDecision:
        bars = (history or []) + [current_bar]
        if len(bars) < self.period + 1:
            return self.default_wait(current_bar.symbol, current_bar.market_timestamp, "Insufficient history for Donchian")

        highs = [b.high for b in bars]
        data = {
            "price": current_bar.close,
            "highs": highs,
            "bar_timestamp": current_bar.market_timestamp,
            "atr": float(getattr(current_bar, "atr", current_bar.close * 0.01)),
        }
        return self.evaluate_data(current_bar.symbol, data)
