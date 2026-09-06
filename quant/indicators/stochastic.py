"""Stochastic Oscillator Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract
from quant.indicators.sma import SMA


class Stochastic(IndicatorContract):
    """Stochastic Oscillator (%K, %D).
    
    Momentum indicator comparing a closing price to its price range over a given time window.
    Normalized on a 0 to 100 scale.
    Evidence role: Location within recent range, momentum turns, overextension evidence.
    """

    def __init__(self, k_period: int = 14, d_period: int = 3, slowing: int = 3):
        if k_period <= 0 or d_period <= 0 or slowing <= 0:
            raise ValueError("Stochastic parameters must be positive integers.")

        super().__init__(
            name="Stochastic",
            version="1.0.0",
            params={
                "k_period": k_period,
                "d_period": d_period,
                "slowing": slowing,
            },
            required_columns=["high", "low", "close"],
            output_columns=["stoch_k", "stoch_d"],
            warm_up_period=k_period + slowing + d_period - 2,
        )
        self.k_period = k_period
        self.d_period = d_period
        self.slowing = slowing
        self._slow_sma = SMA(period=slowing)
        self._d_sma = SMA(period=d_period)

    def calculate(self, closes: np.ndarray, **kwargs) -> Dict[str, np.ndarray]:
        highs = kwargs.get("highs", kwargs.get("high"))
        lows = kwargs.get("lows", kwargs.get("low"))
        if highs is None or lows is None:
            raise ValueError("Stochastic calculation requires 'highs' and 'lows' arrays.")

        n = len(closes)
        fast_k = np.full(n, np.nan, dtype=float)
        stoch_k = np.full(n, np.nan, dtype=float)
        stoch_d = np.full(n, np.nan, dtype=float)

        if n < self.k_period:
            return {"stoch_k": stoch_k, "stoch_d": stoch_d}

        # Calculate Fast %K
        for i in range(self.k_period - 1, n):
            window_lows = lows[i - self.k_period + 1 : i + 1]
            window_highs = highs[i - self.k_period + 1 : i + 1]
            min_low = np.min(window_lows)
            max_high = np.max(window_highs)

            denom = max_high - min_low
            if denom == 0:
                fast_k[i] = 50.0
            else:
                fast_k[i] = 100.0 * ((closes[i] - min_low) / denom)

        # Smooth Fast %K with slowing SMA to get Slow %K (stoch_k)
        valid_fast = fast_k[self.k_period - 1 :]
        smoothed_k = self._slow_sma.calculate(valid_fast)
        stoch_k[self.k_period - 1 :] = smoothed_k

        # Smooth stoch_k with d_period SMA to get %D (stoch_d)
        valid_stoch_k = stoch_k[~np.isnan(stoch_k)]
        if len(valid_stoch_k) >= self.d_period:
            smoothed_d = self._d_sma.calculate(valid_stoch_k)
            stoch_d[~np.isnan(stoch_k)] = smoothed_d

        return {"stoch_k": stoch_k, "stoch_d": stoch_d}
