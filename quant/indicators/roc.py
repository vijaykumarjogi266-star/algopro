"""Rate of Change (ROC) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class ROC(IndicatorContract):
    """Rate of Change (ROC).
    
    Pure momentum oscillator measuring the percentage change between the current price
    and the price n periods ago: ((Close_t - Close_t-n) / Close_t-n) * 100.
    Evidence role: Velocity, acceleration, and momentum thrust analysis.
    """

    def __init__(self, period: int = 12):
        if period <= 0:
            raise ValueError("ROC period must be a positive integer.")
        col_name = f"roc_{period}"
        super().__init__(
            name="ROC",
            version="1.0.0",
            params={"period": period},
            required_columns=["close"],
            output_columns=[col_name],
            warm_up_period=period,
        )
        self.period = period
        self.output_col = col_name

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n <= self.period:
            return out

        past_prices = closes[: n - self.period]
        curr_prices = closes[self.period :]

        with np.errstate(divide="ignore", invalid="ignore"):
            valid_roc = ((curr_prices - past_prices) / past_prices) * 100.0
            out[self.period :] = np.where(past_prices != 0, valid_roc, np.nan)

        return out
