"""Relative Strength Index (RSI) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class RSI(IndicatorContract):
    """Relative Strength Index (RSI).
    
    Measures the speed and change of price movements on a normalized 0 to 100 scale.
    
    CRITICAL ARCHITECTURAL CONSTRAINTS:
    - Principle 11: Indicators are evidence, not automatic trading decisions.
    - Principle 12: RSI must NEVER independently generate BUY/SELL decisions.
    - Principle 13: Multiple correlated indicators must not be treated as independent evidence.
    
    Evidence role: Momentum exhaustion, divergence research, and mean-reversion context.
    """

    def __init__(self, period: int = 14):
        if period <= 1:
            raise ValueError("RSI period must be greater than 1.")
        col_name = f"rsi_{period}"
        super().__init__(
            name="RSI",
            version="1.0.0",
            params={"period": period},
            required_columns=["close"],
            output_columns=[col_name],
            warm_up_period=period + 1,
        )
        self.period = period
        self.output_col = col_name

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n <= self.period:
            return out

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # First average is standard SMA of gains and losses
        avg_gain = np.mean(gains[: self.period])
        avg_loss = np.mean(losses[: self.period])

        if avg_loss == 0.0:
            out[self.period] = 100.0
        elif avg_gain == 0.0:
            out[self.period] = 0.0
        else:
            rs = avg_gain / avg_loss
            out[self.period] = 100.0 - (100.0 / (1.0 + rs))

        # Wilder's Smoothing for subsequent observations
        p = self.period
        for i in range(p + 1, n):
            gain = gains[i - 1]
            loss = losses[i - 1]
            avg_gain = (avg_gain * (p - 1) + gain) / p
            avg_loss = (avg_loss * (p - 1) + loss) / p

            if avg_loss == 0.0:
                out[i] = 100.0
            elif avg_gain == 0.0:
                out[i] = 0.0
            else:
                rs = avg_gain / avg_loss
                out[i] = 100.0 - (100.0 / (1.0 + rs))

        return out
