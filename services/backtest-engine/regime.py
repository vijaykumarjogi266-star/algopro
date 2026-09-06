"""Algo Lab Market Regime Detection (Stage 4).

Uses Stage 3 indicators (ADX, SMA, Realized Volatility) to segment market conditions:
- BULLISH_TREND
- BEARISH_TREND
- SIDEWAYS_RANGE
- HIGH_VOLATILITY
- LOW_VOLATILITY
"""

from typing import Dict, Optional
import numpy as np
from data.schemas.contracts import OHLCVBar


class MarketRegimeDetector:
    """Lightweight deterministic regime tagging using foundational indicators."""

    @staticmethod
    def detect_regime(
        current_bar: OHLCVBar,
        indicators: Dict[str, Optional[float]],
    ) -> str:
        """Determines market regime label from available point-in-time indicators."""
        adx = indicators.get("adx")
        sma = indicators.get("sma_20", indicators.get("sma_50"))
        realized_vol = indicators.get("realized_vol_20")

        # 1. Volatility Regime Check
        if realized_vol is not None and realized_vol > 30.0:
            return "HIGH_VOLATILITY"

        # 2. Trend Strength Check (ADX)
        if adx is not None and adx < 20.0:
            return "SIDEWAYS_RANGE"

        # 3. Directional Trend (Price relative to moving average)
        if sma is not None:
            if current_bar.close > sma:
                return "BULLISH_TREND"
            elif current_bar.close < sma:
                return "BEARISH_TREND"

        return "NORMAL"
