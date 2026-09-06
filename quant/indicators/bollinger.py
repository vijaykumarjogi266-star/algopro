"""Bollinger Bands Volatility Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract
from quant.indicators.sma import SMA


class BollingerBands(IndicatorContract):
    """Bollinger Bands.
    
    Volatility bands placed above and below a moving average.
    Components:
    - Middle Band: n-period Simple Moving Average (SMA)
    - Upper Band: Middle Band + (k * standard deviation)
    - Lower Band: Middle Band - (k * standard deviation)
    - Bandwidth: ((Upper - Lower) / Middle) * 100 (measures volatility contraction/expansion)
    - %B: (Close - Lower) / (Upper - Lower) (measures price position within the bands)
    
    Evidence role: Volatility squeeze detection, dynamic support/resistance, mean-reversion boundary.
    """

    def __init__(self, period: int = 20, num_std: float = 2.0):
        if period <= 1:
            raise ValueError("Bollinger Bands period must be greater than 1.")
        if num_std <= 0:
            raise ValueError("num_std multiplier must be positive.")

        super().__init__(
            name="BollingerBands",
            version="1.0.0",
            params={"period": period, "num_std": num_std},
            required_columns=["close"],
            output_columns=[
                "bb_upper",
                "bb_middle",
                "bb_lower",
                "bb_bandwidth",
                "bb_percent_b",
            ],
            warm_up_period=period,
        )
        self.period = period
        self.num_std = num_std
        self._sma = SMA(period=period)

    def calculate(self, closes: np.ndarray, **kwargs) -> Dict[str, np.ndarray]:
        n = len(closes)
        bb_upper = np.full(n, np.nan, dtype=float)
        bb_middle = np.full(n, np.nan, dtype=float)
        bb_lower = np.full(n, np.nan, dtype=float)
        bb_bandwidth = np.full(n, np.nan, dtype=float)
        bb_percent_b = np.full(n, np.nan, dtype=float)

        if n < self.period:
            return {
                "bb_upper": bb_upper,
                "bb_middle": bb_middle,
                "bb_lower": bb_lower,
                "bb_bandwidth": bb_bandwidth,
                "bb_percent_b": bb_percent_b,
            }

        # Calculate Middle Band (SMA)
        bb_middle = self._sma.calculate(closes)

        # Calculate Rolling Standard Deviation (vectorized over sliding window)
        p = self.period
        for i in range(p - 1, n):
            window = closes[i - p + 1 : i + 1]
            std = float(np.std(window, ddof=0))
            mid = bb_middle[i]

            up = mid + (self.num_std * std)
            low = mid - (self.num_std * std)

            bb_upper[i] = up
            bb_lower[i] = low

            if mid > 0:
                bb_bandwidth[i] = ((up - low) / mid) * 100.0

            band_range = up - low
            if band_range > 0:
                bb_percent_b[i] = (closes[i] - low) / band_range
            else:
                bb_percent_b[i] = 0.5

        return {
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "bb_bandwidth": bb_bandwidth,
            "bb_percent_b": bb_percent_b,
        }
