"""Exponential Moving Average (EMA) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class EMA(IndicatorContract):
    """Exponential Moving Average (EMA).
    
    Weights recent observations more heavily via smoothing constant alpha = 2 / (period + 1).
    Evidence role: Faster trend reactivity and momentum trailing reference.
    """

    def __init__(self, period: int = 20):
        if period <= 0:
            raise ValueError("EMA period must be positive integer.")
        col_name = f"ema_{period}"
        super().__init__(
            name="EMA",
            version="1.0.0",
            params={"period": period},
            required_columns=["close"],
            output_columns=[col_name],
            warm_up_period=period,
        )
        self.period = period
        self.alpha = 2.0 / (period + 1.0)

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n < self.period:
            return out

        # Seed the first value with arithmetic mean (SMA) of initial period
        out[self.period - 1] = np.mean(closes[: self.period])
        for i in range(self.period, n):
            out[i] = (closes[i] * self.alpha) + (out[i - 1] * (1.0 - self.alpha))
        return out
