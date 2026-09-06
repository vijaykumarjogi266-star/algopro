"""Relative Volume (RVOL) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract
from quant.indicators.sma import SMA


class RelativeVolume(IndicatorContract):
    """Relative Volume (RVOL).
    
    Compares the current volume to a rolling historical moving average baseline of volume:
    RVOL_t = Volume_t / SMA(Volume, period)_t
    - RVOL = 1.0: Normal average activity.
    - RVOL > 2.0: Significant volume breakout / expansion.
    - RVOL < 0.5: Low-liquidity / low-participation contraction.
    
    Evidence role: Breakout validation, liquidity confirmation, interest surge evidence.
    """

    def __init__(self, period: int = 20):
        if period <= 0:
            raise ValueError("RVOL period must be a positive integer.")
        col_name = f"rvol_{period}"
        super().__init__(
            name="RelativeVolume",
            version="1.0.0",
            params={"period": period},
            required_columns=["volume"],
            output_columns=[col_name],
            warm_up_period=period,
        )
        self.period = period
        self.output_col = col_name
        self._vol_sma = SMA(period=period)

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        volumes = kwargs.get("volumes", kwargs.get("volume"))
        if volumes is None:
            raise ValueError("Relative Volume calculation requires 'volumes' array.")

        n = len(volumes)
        out = np.full(n, np.nan, dtype=float)
        if n < self.period:
            return out

        baseline_sma = self._vol_sma.calculate(volumes)

        with np.errstate(divide="ignore", invalid="ignore"):
            rvol = volumes / baseline_sma
            out = np.where(baseline_sma > 0, rvol, np.nan)

        return out
