"""Algo Lab Bollinger Bands Mean Reversion Strategy.

Trades mean-reversion when price stretches below the lower Bollinger Band.
- Entry: Close < Lower Band -> ENTER_LONG / BUY
- Non-entry: Close >= Lower Band -> WAIT
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


class BollingerReversion(BaseStrategy):
    """Bollinger Bands 2.0 Std Dev Mean Reversion Strategy."""

    def __init__(
        self,
        strategy_id: str = "STRAT_BOLLINGER_REVERSION",
        version: str = "1.0.0",
        period: int = 20,
        num_std: float = 2.0,
        stop_loss_atr: float = 1.5,
        target_atr: float = 3.0,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        params = parameters or {}
        p = int(params.get("period", period))
        std = float(params.get("num_std", num_std))
        sl_atr = float(params.get("stop_loss_atr", stop_loss_atr))
        tp_atr = float(params.get("target_atr", target_atr))
        super().__init__(
            strategy_id=strategy_id,
            name="Bollinger Mean Reversion",
            version=version,
            parameters={
                "period": p,
                "num_std": std,
                "stop_loss_atr": sl_atr,
                "target_atr": tp_atr,
            },
        )
        self.period = p
        self.num_std = std
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
        num_std = float(params.get("num_std", self.num_std))

        price = float(data.get("price", 0.0))
        atr = float(data.get("atr", price * 0.01))
        ts = data.get("bar_timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)

        # Check for Bollinger band condition
        lower_bb = None
        sma = None
        if "lower_bb" in data:
            lower_bb = float(data["lower_bb"])
            sma = float(data.get("sma20", price))
        elif "closes" in data and len(data["closes"]) >= period:
            closes = np.array(data["closes"][-period:], dtype=float)
            sma = float(np.mean(closes))
            std = float(np.std(closes))
            lower_bb = sma - (num_std * std)
        elif "bars" in data and len(data["bars"]) >= period:
            closes = np.array([b.close for b in data["bars"][-period:]], dtype=float)
            sma = float(np.mean(closes))
            std = float(np.std(closes))
            lower_bb = sma - (num_std * std)

        if lower_bb is not None and price < lower_bb:
            stop_loss = round(price - (sl_atr * atr), 2)
            target = round(sma if sma is not None else price + (tp_atr * atr), 2)
            return StrategyDecision(
                symbol=symbol,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=0.75,
                reason=f"Bollinger oversold: price {price:.2f} stretched below lower BB {lower_bb:.2f}",
                evidence={"period": period, "lower_bb": lower_bb, "sma": sma, "price": price, "atr": atr},
                stop_loss=stop_loss,
                target_price=target,
            )

        return self.default_wait(
            symbol=symbol,
            timestamp=ts,
            reason=f"No Bollinger mean-reversion setup (price={price:.2f}, lower_bb={lower_bb})",
        )

    def evaluate(self, current_bar: OHLCVBar, history: List[OHLCVBar], data_quality=None) -> StrategyDecision:
        bars = (history or []) + [current_bar]
        if len(bars) < self.period:
            return self.default_wait(current_bar.symbol, current_bar.market_timestamp, "Insufficient history for Bollinger")

        closes = [b.close for b in bars]
        data = {
            "price": current_bar.close,
            "closes": closes,
            "bar_timestamp": current_bar.market_timestamp,
            "atr": float(getattr(current_bar, "atr", current_bar.close * 0.01)),
        }
        return self.evaluate_data(current_bar.symbol, data)
