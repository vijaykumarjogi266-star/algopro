"""VWAP Mean Reversion Research Strategy.

Captures intraday price over-extensions away from the institutional volume-weighted average price.
Target is reversion back to VWAP benchmark.
Adheres to Principle 11 (Indicators are evidence) and Principle 12 (RSI never auto-triggers orders).
"""

from typing import Dict, List, Optional
from data.schemas.contracts import OHLCVBar
from quant.strategies.base import BaseStrategy
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

    def evaluate(self, current_bar, history, data_quality):
        return self.default_wait(current_bar.symbol, current_bar.market_timestamp, "VWAP in evaluation")
