"""Moving Average Convergence Divergence (MACD) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract
from quant.indicators.ema import EMA


class MACD(IndicatorContract):
    """Moving Average Convergence Divergence (MACD).
    
    Measures the relationship between two exponential moving averages of prices.
    Components:
    - MACD Line: fast_ema - slow_ema
    - Signal Line: signal_period EMA of MACD Line
    - Histogram: MACD Line - Signal Line
    Evidence role: Momentum shifts, acceleration/deceleration, and divergence evidence.
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ):
        if fast_period >= slow_period:
            raise ValueError("Fast period must be strictly less than slow period.")
        if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
            raise ValueError("All MACD periods must be positive integers.")

        super().__init__(
            name="MACD",
            version="1.0.0",
            params={
                "fast_period": fast_period,
                "slow_period": slow_period,
                "signal_period": signal_period,
            },
            required_columns=["close"],
            output_columns=["macd", "macd_signal", "macd_hist"],
            warm_up_period=slow_period + signal_period - 1,
        )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self._fast_ema = EMA(period=fast_period)
        self._slow_ema = EMA(period=slow_period)
        self._signal_ema = EMA(period=signal_period)

    def calculate(self, closes: np.ndarray, **kwargs) -> Dict[str, np.ndarray]:
        n = len(closes)
        macd_line = np.full(n, np.nan, dtype=float)
        signal_line = np.full(n, np.nan, dtype=float)
        hist = np.full(n, np.nan, dtype=float)

        if n < self.slow_period:
            return {
                "macd": macd_line,
                "macd_signal": signal_line,
                "macd_hist": hist,
            }

        fast_series = self._fast_ema.calculate(closes)
        slow_series = self._slow_ema.calculate(closes)

        # MACD Line is defined where slow_ema is valid
        valid_idx = ~np.isnan(slow_series)
        macd_line[valid_idx] = fast_series[valid_idx] - slow_series[valid_idx]

        # Calculate Signal Line as EMA of valid MACD Line
        valid_macd_vals = macd_line[valid_idx]
        if len(valid_macd_vals) >= self.signal_period:
            sig_vals = self._signal_ema.calculate(valid_macd_vals)
            signal_line[valid_idx] = sig_vals

            # Histogram is valid where both macd and signal are valid
            hist_valid = ~np.isnan(signal_line)
            hist[hist_valid] = macd_line[hist_valid] - signal_line[hist_valid]

        return {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": hist,
        }
