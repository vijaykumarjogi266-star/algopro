"""Simple Moving Average (SMA) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class SMA(IndicatorContract):
    """Simple Moving Average (SMA).
    
    Measures the unweighted mean price over the specified lookback period.
    Evidence role: Trend direction and dynamic support/resistance reference.
    """

    def __init__(self, period: int = 20):
        if period <= 0:
            raise ValueError("SMA period must be positive integer.")
        col_name = f"sma_{period}"
        super().__init__(
            name="SMA",
            version="1.0.0",
            params={"period": period},
            required_columns=["close"],
            output_columns=[col_name],
            warm_up_period=period,
        )
        self.period = period

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n < self.period:
            return out

        weights = np.repeat(1.0, self.period) / self.period
        sma_valid = np.convolve(closes, weights, mode="valid")
        out[self.period - 1 :] = sma_valid
        return out
