"""Average True Range (ATR) Volatility Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class ATR(IndicatorContract):
    """Average True Range (ATR).
    
    Measures market volatility by decomposing the entire range of an asset for that period.
    True Range (TR) is the greatest of:
    - Current High minus Current Low
    - Absolute value of (Current High minus Previous Close)
    - Absolute value of (Current Low minus Previous Close)
    
    Evidence role: Volatility regime classification, dynamic stop-loss calibration, and risk sizing.
    """

    def __init__(self, period: int = 14):
        if period <= 0:
            raise ValueError("ATR period must be a positive integer.")
        col_name = f"atr_{period}"
        super().__init__(
            name="ATR",
            version="1.0.0",
            params={"period": period},
            required_columns=["high", "low", "close"],
            output_columns=[col_name],
            warm_up_period=period,
        )
        self.period = period
        self.output_col = col_name

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        highs = kwargs.get("highs", kwargs.get("high"))
        lows = kwargs.get("lows", kwargs.get("low"))
        if highs is None or lows is None:
            raise ValueError("ATR calculation requires 'highs' and 'lows' arrays.")

        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n < self.period:
            return out

        tr = np.zeros(n, dtype=float)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)

        # Initial seed: simple arithmetic mean of first 'period' TR values
        out[self.period - 1] = np.mean(tr[: self.period])

        # Wilder's Exponential Smoothing
        p = self.period
        for i in range(p, n):
            out[i] = (out[i - 1] * (p - 1) + tr[i]) / p

        return out
