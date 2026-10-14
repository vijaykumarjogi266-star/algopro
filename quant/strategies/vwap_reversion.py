"""VWAP Mean Reversion Research Strategy.

Captures intraday price over-extensions away from the institutional volume-weighted average price.
Target is reversion back to VWAP benchmark.
Adheres to Principle 11 (Indicators are evidence) and Principle 12 (RSI never auto-triggers orders).
"""

from typing import Any, Dict, List, Optional
from data.schemas.contracts import OHLCVBar
from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from services.backtest_engine.trade_candidate import CandidateAction, TradeCandidate


class VWAPReversion(BaseStrategy):
    """VWAP Mean Reversion Strategy."""

    def __init__(
        self,
        std_dev_threshold: float = 2.0,
        stop_loss_atr_mult: float = 1.5,
    ):
        super().__init__(
            strategy_id="VWAP_REVERSION",
            name="VWAP Mean Reversion",
            version="1.0.0",
            parameters={
                "std_dev_threshold": std_dev_threshold,
                "stop_loss_atr_mult": stop_loss_atr_mult,
            },
        )
        self.std_dev_threshold = std_dev_threshold
        self.stop_loss_atr_mult = stop_loss_atr_mult

    def on_bar(
        self,
        current_bar: OHLCVBar,
        history: List[OHLCVBar],
        indicators: Dict[str, Optional[float]],
        has_open_position: bool = False,
    ) -> Optional[TradeCandidate]:
        if has_open_position:
            return None

        vwap = indicators.get("vwap")
        vwap_lower = indicators.get("vwap_lower")
        atr = indicators.get("atr_14", 5.0) or 5.0
        rsi = indicators.get("rsi_14")

        if vwap is None or vwap_lower is None:
            return None

        # Long Mean-Reversion Setup: Price stretched below lower VWAP band
        if current_bar.close <= vwap_lower and current_bar.low < vwap_lower:
            stop_dist = atr * self.stop_loss_atr_mult
            stop_loss = current_bar.close - stop_dist
            target = vwap  # Target is reversion to VWAP

            if target <= current_bar.close:
                return None

            return TradeCandidate(
                strategy_id=self.strategy_id,
                strategy_version=self.version,
                symbol=current_bar.symbol,
                timestamp=current_bar.market_timestamp,
                action=CandidateAction.ENTER_LONG,
                confidence=0.70,
                reason=f"Price ({current_bar.close:.2f}) stretched below lower VWAP band ({vwap_lower:.2f})",
                evidence={
                    "vwap": vwap,
                    "vwap_lower": vwap_lower,
                    "atr": atr,
                    "rsi": rsi,  # Principle 11: Included as context evidence
                },
                suggested_limit_price=current_bar.close,
                suggested_stop_loss=round(stop_loss, 2),
                suggested_target_price=round(target, 2),
                suggested_position_size_pct=0.05,
            )

        return None

    def evaluate(self, current_bar: OHLCVBar, history: List[OHLCVBar], data_quality=None) -> StrategyDecision:
        data = {
            "price": current_bar.close,
            "bar_timestamp": current_bar.market_timestamp,
            "atr": float(getattr(current_bar, "atr", current_bar.close * 0.01)),
        }
        return self.evaluate_data(current_bar.symbol, data)

    def evaluate_data(
        self,
        symbol: str,
        data: Dict[str, Any],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> StrategyDecision:
        """Evaluate market data dict point-in-time."""
        from datetime import datetime, timezone
        from quant.strategies.base import SignalType, StrategyDecision
        params = parameters or self.parameters
        sl_atr = float(params.get("stop_loss_atr", self.stop_loss_atr_mult))
        tp_atr = float(params.get("target_atr", 3.0))
        std_threshold = float(params.get("std_dev_threshold", self.std_dev_threshold))

        price = float(data.get("price", 0.0))
        atr = float(data.get("atr", price * 0.01))
        ts = data.get("bar_timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)

        vwap = data.get("vwap")
        vwap_lower = data.get("vwap_lower")
        std = data.get("std20") or data.get("std")

        if vwap_lower is None and vwap is not None and std is not None:
            vwap_lower = float(vwap) - (std_threshold * float(std))

        if vwap_lower is not None and price < float(vwap_lower):
            stop_loss = round(price - (sl_atr * atr), 2)
            target = round(float(vwap) if vwap is not None else price + (tp_atr * atr), 2)
            return StrategyDecision(
                symbol=symbol,
                decision_timestamp=ts,
                signal=SignalType.BUY,
                confidence=0.75,
                reason=f"VWAP oversold: price {price:.2f} < lower VWAP band {float(vwap_lower):.2f}",
                evidence={"vwap": vwap, "vwap_lower": vwap_lower, "price": price, "atr": atr},
                stop_loss=stop_loss,
                target_price=target,
            )

        return self.default_wait(
            symbol=symbol,
            timestamp=ts,
            reason=f"No VWAP reversion setup (price={price:.2f}, vwap_lower={vwap_lower})",
        )

